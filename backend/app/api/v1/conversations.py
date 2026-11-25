"""Conversation Lifecycle & Messaging Router."""

import logging
from datetime import datetime, timezone
from typing import List, Optional
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
from backend.app.models.employee import Employee
from backend.app.models.lead import Lead
from backend.app.models.message import Message
from backend.app.models.user import User
from backend.app.schemas.conversation import (
    ConversationCreateRequest,
    ConversationResponse,
    HandoffCreateRequest,
    HandoffItemResponse,
    HandoffTakeoverRequest,
    MessageCreateRequest,
    MessageResponse,
    OrchestrationTurnResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["Conversations"])


def _extract_customer_name(cust: Optional[Customer]) -> Optional[str]:
    """Helper to assemble customer display name."""
    if not cust:
        return None
    name_parts = [p for p in (cust.first_name, cust.last_name) if p]
    if name_parts:
        return " ".join(name_parts)
    return cust.company_name or None


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
    "/handoffs",
    response_model=List[HandoffItemResponse],
    summary="List all handed-off conversations and calls requiring human intervention",
)
async def list_handoffs(
    include_taken_over: bool = False,
    limit: int = 50,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> List[HandoffItemResponse]:
    """Returns pending handed-off calls and conversations scoped to the active tenant."""
    org_id = TenantContext.get_current_tenant_id()

    query = (
        select(Conversation, Call, Customer, Employee)
        .outerjoin(Call, Conversation.call_id == Call.id)
        .outerjoin(Customer, Call.customer_id == Customer.id)
        .outerjoin(Employee, Call.taken_over_by_employee_id == Employee.id)
        .where(
            Conversation.org_id == org_id,
            Conversation.status == "handed_off",
        )
    )

    if not include_taken_over:
        query = query.where(Call.taken_over_by_employee_id.is_(None))

    query = query.order_by(Conversation.updated_at.desc()).limit(limit)
    res = await db.execute(query)
    rows = res.all()

    items = []
    for conv, call, cust, emp in rows:
        caller_phone = call.caller_phone_number if call else None
        cust_name = _extract_customer_name(cust)
        taken_over_name = None
        if emp and hasattr(emp, "title") and emp.title:
            taken_over_name = emp.title

        items.append(
            HandoffItemResponse(
                conversation_id=conv.id,
                call_id=conv.call_id,
                caller_phone_number=caller_phone,
                customer_id=call.customer_id if call else None,
                customer_name=cust_name,
                status=conv.status,
                turn_count=conv.turn_count,
                summary=conv.summary,
                started_at=call.started_at if call else conv.created_at,
                taken_over_by_employee_id=call.taken_over_by_employee_id if call else None,
                taken_over_by_name=taken_over_name,
                notes=call.notes if call else None,
                outcome=call.outcome if call else None,
                created_at=conv.created_at,
            )
        )
    return items


@router.post(
    "/{conversation_id}/handoff",
    response_model=HandoffItemResponse,
    summary="Directly trigger human handoff for an active conversation",
)
async def escalate_conversation(
    conversation_id: UUID,
    payload: HandoffCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> HandoffItemResponse:
    """Escalates conversation and linked call to human staff queue."""
    org_id = TenantContext.get_current_tenant_id()

    conv_query = (
        select(Conversation, Call, Customer)
        .outerjoin(Call, Conversation.call_id == Call.id)
        .outerjoin(Customer, Call.customer_id == Customer.id)
        .where(
            Conversation.id == conversation_id,
            Conversation.org_id == org_id,
        )
    )
    res = await db.execute(conv_query)
    row = res.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' was not found.",
        )
    conv, call, cust = row

    conv.status = "handed_off"
    ticket_id = f"ESC-{str(conversation_id)[:8].upper()}"

    if call:
        call.status = "handed_off"
        call.outcome = "handed_off"
        notes_str = f"Handoff escalation: {payload.reason}. Urgency: {payload.urgency}."
        if payload.customer_callback_phone:
            notes_str += f" Callback: {payload.customer_callback_phone}."
        call.notes = f"{call.notes}\n{notes_str}" if call.notes else notes_str

    await db.commit()
    await db.refresh(conv)
    if call:
        await db.refresh(call)

    return HandoffItemResponse(
        conversation_id=conv.id,
        call_id=conv.call_id,
        caller_phone_number=call.caller_phone_number if call else None,
        customer_id=call.customer_id if call else None,
        customer_name=_extract_customer_name(cust),
        status=conv.status,
        turn_count=conv.turn_count,
        summary=conv.summary,
        started_at=call.started_at if call else conv.created_at,
        taken_over_by_employee_id=call.taken_over_by_employee_id if call else None,
        taken_over_by_name=None,
        notes=call.notes if call else None,
        outcome=call.outcome if call else None,
        created_at=conv.created_at,
    )


@router.post(
    "/{conversation_id}/takeover",
    response_model=HandoffItemResponse,
    summary="Take over a handed-off conversation session as staff",
)
async def takeover_conversation(
    conversation_id: UUID,
    payload: Optional[HandoffTakeoverRequest] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> HandoffItemResponse:
    """Assigns the handed-off conversation/call to an employee and updates status."""
    org_id = TenantContext.get_current_tenant_id()

    conv_query = (
        select(Conversation, Call, Customer)
        .outerjoin(Call, Conversation.call_id == Call.id)
        .outerjoin(Customer, Call.customer_id == Customer.id)
        .where(
            Conversation.id == conversation_id,
            Conversation.org_id == org_id,
        )
    )
    res = await db.execute(conv_query)
    row = res.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' was not found.",
        )
    conv, call, cust = row

    # Resolve Employee
    target_emp_id = payload.employee_id if payload and payload.employee_id else None
    if not target_emp_id:
        emp_query = select(Employee).where(Employee.user_id == current_user.id, Employee.org_id == org_id)
        emp_res = await db.execute(emp_query)
        emp = emp_res.scalar_one_or_none()
        if emp:
            target_emp_id = emp.id
        else:
            first_emp_query = select(Employee).where(Employee.org_id == org_id).limit(1)
            first_emp_res = await db.execute(first_emp_query)
            first_emp = first_emp_res.scalar_one_or_none()
            if first_emp:
                target_emp_id = first_emp.id

    takeover_notes = payload.notes if payload and payload.notes else f"Taken over by {current_user.full_name or current_user.email}."
    if call:
        call.taken_over_by_employee_id = target_emp_id
        call.status = "in_progress"
        call.notes = f"{call.notes}\n[Takeover]: {takeover_notes}" if call.notes else f"[Takeover]: {takeover_notes}"

    conv.summary = f"{conv.summary or ''}\n[Human Takeover by {current_user.email}]".strip()
    await db.commit()
    await db.refresh(conv)
    if call:
        await db.refresh(call)

    return HandoffItemResponse(
        conversation_id=conv.id,
        call_id=conv.call_id,
        caller_phone_number=call.caller_phone_number if call else None,
        customer_id=call.customer_id if call else None,
        customer_name=_extract_customer_name(cust),
        status=call.status if call else conv.status,
        turn_count=conv.turn_count,
        summary=conv.summary,
        started_at=call.started_at if call else conv.created_at,
        taken_over_by_employee_id=call.taken_over_by_employee_id if call else None,
        taken_over_by_name=current_user.full_name or current_user.email,
        notes=call.notes if call else None,
        outcome=call.outcome if call else None,
        created_at=conv.created_at,
    )


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
