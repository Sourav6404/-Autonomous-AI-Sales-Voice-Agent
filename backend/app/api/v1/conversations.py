"""Conversation Lifecycle & Messaging Router."""

import logging
from datetime import datetime, timezone
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.ai.conversation.orchestrator import ConversationOrchestrator
from backend.app.api.deps import get_current_active_user
from backend.app.core.database import get_db
from backend.app.core.exceptions import AppException
from backend.app.core.tenant import TenantContext
from backend.app.models.call import Call
from backend.app.models.conversation import Conversation
from backend.app.models.customer import Customer
from backend.app.models.lead import Lead
from backend.app.models.message import Message
from backend.app.models.user import User
from backend.app.schemas.conversation import (
    ConversationCreateRequest,
    ConversationResponse,
    MessageCreateRequest,
    MessageResponse,
    OrchestrationTurnResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["Conversations"])


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initialize a new independent conversation session",
)
async def create_conversation(
    payload: ConversationCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Creates a new isolated conversation session and linked call record for the tenant."""
    org_id = TenantContext.get_current_tenant_id()

    # 1. Resolve or create Customer record if phone number provided
    customer_id = None
    if payload.customer_phone:
        cust_stmt = select(Customer).where(
            Customer.org_id == org_id,
            Customer.phone_number == payload.customer_phone,
        )
        cust_res = await db.execute(cust_stmt)
        customer = cust_res.scalar_one_or_none()
        if not customer:
            customer = Customer(
                org_id=org_id,
                phone_number=payload.customer_phone,
                total_calls_count=1,
                last_called_at=datetime.now(timezone.utc),
            )
            db.add(customer)
            await db.flush()
        else:
            customer.total_calls_count += 1
            customer.last_called_at = datetime.now(timezone.utc)
        customer_id = customer.id

    # 2. Create underlying Call record for auditability
    call = Call(
        org_id=org_id,
        customer_id=customer_id,
        caller_phone_number=payload.customer_phone or "+10000000000",
        callee_phone_number="AI-Receptionist",
        status="in_progress",
        started_at=datetime.now(timezone.utc),
    )
    db.add(call)
    await db.flush()

    # 3. Create Conversation record
    conv = Conversation(
        org_id=org_id,
        call_id=call.id,
        language=payload.language,
        status="active",
        turn_count=0,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)

    return ConversationResponse.model_validate(conv)


@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="Get conversation session metadata",
)
async def get_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Retrieves conversation metadata, verifying tenant boundary."""
    org_id = TenantContext.get_current_tenant_id()
    query = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.org_id == org_id,
    )
    res = await db.execute(query)
    conv = res.scalar_one_or_none()

    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' was not found.",
        )

    return ConversationResponse.model_validate(conv)


@router.post(
    "/{conversation_id}/messages",
    response_model=OrchestrationTurnResponse,
    summary="Post customer message and execute AI dialogue turn",
)
async def send_message(
    conversation_id: UUID,
    payload: MessageCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> OrchestrationTurnResponse:
    """Executes a dialogue turn through the Conversation Orchestrator."""
    org_id = TenantContext.get_current_tenant_id()

    turn_result = await ConversationOrchestrator.handle_message(
        db=db,
        conversation_id=conversation_id,
        org_id=org_id,
        user_message_text=payload.content,
        user_id=current_user.id,
    )
    return turn_result


@router.get(
    "/{conversation_id}/messages",
    response_model=List[MessageResponse],
    summary="Retrieve all dialogue turns for conversation",
)
async def list_messages(
    conversation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> List[MessageResponse]:
    """Returns chronological messages for the conversation session."""
    org_id = TenantContext.get_current_tenant_id()

    # Verify conversation ownership
    conv_query = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.org_id == org_id,
    )
    conv_res = await db.execute(conv_query)
    if not conv_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' was not found.",
        )

    query = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.turn_number.asc())
    )
    res = await db.execute(query)
    messages = res.scalars().all()
    return [MessageResponse.model_validate(m) for m in messages]


@router.post(
    "/{conversation_id}/end",
    response_model=ConversationResponse,
    summary="Close or end conversation session",
)
async def end_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Marks conversation session and underlying call record as completed."""
    org_id = TenantContext.get_current_tenant_id()

    query = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.org_id == org_id,
    )
    res = await db.execute(query)
    conv = res.scalar_one_or_none()

    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' was not found.",
        )

    conv.status = "completed"

    if conv.call_id:
        call_query = select(Call).where(Call.id == conv.call_id, Call.org_id == org_id)
        call_res = await db.execute(call_query)
        call = call_res.scalar_one_or_none()
        if call:
            call.status = "completed"
            call.ended_at = datetime.now(timezone.utc)
            if call.started_at:
                started_at = call.started_at if call.started_at.tzinfo else call.started_at.replace(tzinfo=timezone.utc)
                ended_at = call.ended_at if call.ended_at.tzinfo else call.ended_at.replace(tzinfo=timezone.utc)
                call.duration_seconds = int((ended_at - started_at).total_seconds())

            # Auto-create Lead if customer exists and no lead yet for this call
            if call.customer_id:
                lead_query = select(Lead).where(Lead.originating_call_id == call.id)
                lead_res = await db.execute(lead_query)
                if not lead_res.scalar_one_or_none():
                    new_lead = Lead(
                        org_id=org_id,
                        customer_id=call.customer_id,
                        originating_call_id=call.id,
                        title=f"Call inquiry from {call.caller_phone_number}",
                        status="new",
                        qualification_tier="warm",
                        score=50,
                        notes=conv.summary or "Generated from completed AI call session",
                    )
                    db.add(new_lead)

    await db.commit()
    await db.refresh(conv)
    return ConversationResponse.model_validate(conv)
