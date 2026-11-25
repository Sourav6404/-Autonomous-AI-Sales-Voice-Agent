"""Tests for Stage 8: Basic Human Handoff and AI Fallback."""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.ai.conversation.orchestrator import ConversationOrchestrator
from backend.app.ai.providers.base import BaseLLMProvider, ChatMessage, LLMResponse
from backend.app.ai.tools.initial_tools import tool_registry
from backend.app.ai.tools.registry import ToolExecutionContext
from backend.app.ai.tools.schemas import RequestHumanHandoffInput
from backend.app.core.security import PasswordHasher, create_access_token
from backend.app.core.tenant import TenantContext
from backend.app.models.call import Call
from backend.app.models.conversation import Conversation
from backend.app.models.customer import Customer
from backend.app.models.employee import Employee
from backend.app.models.inquiry import Inquiry
from backend.app.models.lead import Lead
from backend.app.models.organization import Organization
from backend.app.models.user import User


class FailingLLMProvider(BaseLLMProvider):
    """Mock provider that always raises an unrecoverable exception for fallback testing."""

    def __init__(self):
        super().__init__(provider_name="failing_mock", model="mock")

    async def generate_response(
        self,
        messages,
        tools=None,
        response_schema=None,
        temperature=0.7,
        max_tokens=1024,
    ):
        raise RuntimeError("Simulated remote AI provider timeout or model outage")

    async def generate_stream(
        self,
        messages,
        tools=None,
        temperature=0.7,
        max_tokens=1024,
    ):
        raise RuntimeError("Simulated streaming provider outage")
        yield ""


async def create_test_tenant(db: AsyncSession, name: str = "Handoff Test Org"):
    org = Organization(
        name=name,
        slug=f"org-{uuid.uuid4().hex[:8]}",
        default_timezone="UTC",
    )
    db.add(org)
    await db.flush()

    user = User(
        org_id=org.id,
        email=f"receptionist_{uuid.uuid4().hex[:6]}@handoff.com",
        password_hash=PasswordHasher.hash("Pass12345!"),
        full_name="Receptionist Staff",
        role="receptionist",
        is_active=True,
    )
    db.add(user)
    await db.flush()

    emp = Employee(
        org_id=org.id,
        user_id=user.id,
        title="Front Desk Coordinator",
        is_available_for_takeover=True,
    )
    db.add(emp)
    await db.commit()
    await db.refresh(org)
    await db.refresh(user)
    await db.refresh(emp)

    token = create_access_token(
        subject=str(user.id),
        org_id=str(org.id),
        role=user.role,
        email=user.email,
    )
    return org, user, emp, token


@pytest.mark.asyncio
async def test_human_handoff_tool_execution(db_session: AsyncSession):
    """Verifies that request_human_handoff updates Conversation, Call, Inquiry, and Lead."""
    org, user, emp, _ = await create_test_tenant(db_session, "Tool Exec Org")

    customer = Customer(
        org_id=org.id,
        phone_number="+15551234567",
        first_name="Alice",
        last_name="Smith",
    )
    db_session.add(customer)
    await db_session.flush()

    call = Call(
        org_id=org.id,
        customer_id=customer.id,
        caller_phone_number="+15551234567",
        callee_phone_number="AI-Receptionist",
        status="in_progress",
    )
    db_session.add(call)
    await db_session.flush()

    lead = Lead(
        org_id=org.id,
        customer_id=customer.id,
        originating_call_id=call.id,
        title="Inquiry from Alice",
        status="new",
        qualification_tier="warm",
        score=50,
    )
    db_session.add(lead)
    await db_session.flush()

    conv = Conversation(
        org_id=org.id,
        call_id=call.id,
        language="en",
        status="active",
        turn_count=2,
    )
    db_session.add(conv)
    await db_session.commit()

    # Execute handoff tool
    context = ToolExecutionContext(
        org_id=org.id,
        conversation_id=conv.id,
        db=db_session,
    )

    args = RequestHumanHandoffInput(
        reason="Customer requested to speak with a human sales supervisor",
        urgency="high",
        customer_callback_phone="+15551234567",
    )

    result = await tool_registry.execute_tool(
        name="request_human_handoff",
        arguments=args.model_dump(),
        context=context,
    )

    await db_session.commit()

    assert result["handoff_status"] == "queued"
    assert "ticket_reference" in result
    assert result["ticket_reference"].startswith("ESC-")

    # Verify conversation & call statuses
    await db_session.refresh(conv)
    await db_session.refresh(call)
    await db_session.refresh(lead)

    assert conv.status == "handed_off"
    assert call.status == "handed_off"
    assert call.outcome == "handed_off"
    assert "sales supervisor" in (call.notes or "")

    # Verify inquiry ticket creation
    inq_res = await db_session.execute(
        select(Inquiry).where(Inquiry.originating_call_id == call.id)
    )
    inquiry = inq_res.scalar_one_or_none()
    assert inquiry is not None
    assert inquiry.status == "open"
    assert inquiry.priority == "high"
    assert "sales supervisor" in inquiry.subject or "sales supervisor" in inquiry.description

    # Verify lead updated
    assert lead.priority == "high"
    assert lead.qualification_tier == "hot"
    assert "Escalated to human" in (lead.notes or "")


@pytest.mark.asyncio
async def test_turn_intelligence_human_intent_detection():
    """Verifies that diverse human handoff phrases trigger needs_human_intervention=True."""
    phrases = [
        "Can I speak to a person please?",
        "Please connect to sales representative",
        "I need human assistance right now",
        "Transfer call to your supervisor",
        "Transfer me to an operator",
        "I want to talk to human",
        "Put me through to a real person",
    ]

    for phrase in phrases:
        extraction = ConversationOrchestrator._extract_turn_intelligence(
            user_text=phrase,
            assistant_text="One moment please.",
        )
        assert extraction.needs_human_intervention is True, f"Failed for phrase: '{phrase}'"

    # Negative check for normal inquiries
    normal = ConversationOrchestrator._extract_turn_intelligence(
        user_text="What are your opening hours on Friday?",
        assistant_text="We are open from 9 AM to 6 PM.",
    )
    assert normal.needs_human_intervention is False


@pytest.mark.asyncio
async def test_ai_fallback_on_provider_failure(db_session: AsyncSession):
    """Verifies that an AI provider failure gracefully triggers handoff without crashing."""
    org, user, emp, _ = await create_test_tenant(db_session, "Fallback Test Org")

    call = Call(
        org_id=org.id,
        caller_phone_number="+15559998888",
        callee_phone_number="AI-Receptionist",
        status="in_progress",
    )
    db_session.add(call)
    await db_session.flush()

    conv = Conversation(
        org_id=org.id,
        call_id=call.id,
        status="active",
        turn_count=0,
    )
    db_session.add(conv)
    await db_session.commit()

    failing_provider = FailingLLMProvider()

    # handle_message should catch provider error and return a fallback handoff turn
    turn_response = await ConversationOrchestrator.handle_message(
        db=db_session,
        conversation_id=conv.id,
        org_id=org.id,
        user_message_text="Hello, I have an urgent complex inquiry.",
        provider=failing_provider,
        user_id=user.id,
        enable_ai_fallback=True,
    )

    assert turn_response is not None
    assert turn_response.conversation_status == "handed_off"
    assert "technical difficulties" in turn_response.assistant_reply.content.lower()

    # Verify conversation and call in DB
    await db_session.refresh(conv)
    await db_session.refresh(call)

    assert conv.status == "handed_off"
    assert call.status == "handed_off"
    assert call.outcome == "ai_fallback_handoff"


@pytest.mark.asyncio
async def test_handoffs_api_endpoints_and_tenant_isolation(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Verifies listing handoffs, takeover, and tenant isolation over HTTP API."""
    # Tenant 1
    org1, user1, emp1, token1 = await create_test_tenant(db_session, "Handoff Org 1")
    # Tenant 2
    org2, user2, emp2, token2 = await create_test_tenant(db_session, "Handoff Org 2")

    # Create handed-off conversation in Org 1
    call1 = Call(
        org_id=org1.id,
        caller_phone_number="+15551111111",
        callee_phone_number="AI-Receptionist",
        status="handed_off",
        outcome="handed_off",
        notes="Handoff requested: urgent pricing clarification",
    )
    db_session.add(call1)
    await db_session.flush()

    conv1 = Conversation(
        org_id=org1.id,
        call_id=call1.id,
        status="handed_off",
        turn_count=3,
        summary="Customer asked for human sales manager.",
    )
    db_session.add(conv1)

    # Create handed-off conversation in Org 2
    call2 = Call(
        org_id=org2.id,
        caller_phone_number="+15552222222",
        callee_phone_number="AI-Receptionist",
        status="handed_off",
        outcome="handed_off",
        notes="Handoff in Org 2",
    )
    db_session.add(call2)
    await db_session.flush()

    conv2 = Conversation(
        org_id=org2.id,
        call_id=call2.id,
        status="handed_off",
        turn_count=1,
    )
    db_session.add(conv2)
    await db_session.commit()

    # 1. Org 1 receptionist queries handoffs
    resp1 = await client.get(
        "/api/v1/conversations/handoffs",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert resp1.status_code == 200
    handoffs_org1 = resp1.json()
    assert len(handoffs_org1) == 1
    assert handoffs_org1[0]["conversation_id"] == str(conv1.id)
    assert handoffs_org1[0]["caller_phone_number"] == "+15551111111"

    # Tenant isolation: Org 2 handoff must NOT appear for Org 1
    assert not any(h["conversation_id"] == str(conv2.id) for h in handoffs_org1)

    # 2. Org 1 receptionist takes over the call
    takeover_resp = await client.post(
        f"/api/v1/conversations/{conv1.id}/takeover",
        json={"notes": "Front desk receptionist taking over now"},
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert takeover_resp.status_code == 200
    takeover_data = takeover_resp.json()
    assert takeover_data["taken_over_by_employee_id"] == str(emp1.id)
    assert "taking over now" in (takeover_data["notes"] or "")

    # 3. Query without taken-over items should now be empty for Org 1
    resp_pending = await client.get(
        "/api/v1/conversations/handoffs?include_taken_over=false",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert resp_pending.status_code == 200
    assert len(resp_pending.json()) == 0

    # Query with include_taken_over=true returns it
    resp_all = await client.get(
        "/api/v1/conversations/handoffs?include_taken_over=true",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert resp_all.status_code == 200
    assert len(resp_all.json()) == 1


@pytest.mark.asyncio
async def test_explicit_handoff_api_endpoint(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Verifies triggering handoff via POST /api/v1/conversations/{id}/handoff."""
    org, user, emp, token = await create_test_tenant(db_session, "Explicit Handoff Org")

    call = Call(
        org_id=org.id,
        caller_phone_number="+15553334444",
        callee_phone_number="AI-Receptionist",
        status="in_progress",
    )
    db_session.add(call)
    await db_session.flush()

    conv = Conversation(
        org_id=org.id,
        call_id=call.id,
        status="active",
        turn_count=1,
    )
    db_session.add(conv)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/conversations/{conv.id}/handoff",
        json={
            "reason": "Customer needs custom enterprise quote",
            "urgency": "high",
            "customer_callback_phone": "+15553334444",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "handed_off"
    assert "enterprise quote" in (data["notes"] or "")

    # Verify database state
    await db_session.refresh(conv)
    await db_session.refresh(call)
    assert conv.status == "handed_off"
    assert call.status == "handed_off"
    assert call.outcome == "handed_off"
