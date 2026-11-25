"""Tests for Conversation Lifecycle, Message Persistence, and Orchestration."""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.ai.conversation.context_manager import ContextManager
from backend.app.ai.conversation.orchestrator import ConversationOrchestrator
from backend.app.ai.conversation.prompt_manager import PromptManager
from backend.app.ai.providers.base import LLMResponse, ToolCall
from backend.app.models.conversation import Conversation
from backend.app.models.message import Message
from backend.tests.test_stage2_rbac import create_user_with_role
from backend.tests.test_stage3_ai_providers import MockLLMProvider


@pytest.mark.asyncio
async def test_conversation_lifecycle_endpoints(client: AsyncClient, db_session: AsyncSession):
    """Tests session creation, retrieval, and closing via REST API."""
    user, token = await create_user_with_role(db_session, "receptionist")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Start new conversation session
    create_res = await client.post(
        "/v1/conversations",
        json={"customer_phone": "+15554443333", "language": "en"},
        headers=headers,
    )
    assert create_res.status_code == 201, create_res.text
    conv_data = create_res.json()
    conv_id = conv_data["id"]
    assert conv_data["status"] == "active"
    assert conv_data["turn_count"] == 0

    # 2. Get conversation
    get_res = await client.get(f"/v1/conversations/{conv_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == conv_id

    # 3. Close conversation session
    end_res = await client.post(f"/v1/conversations/{conv_id}/end", headers=headers)
    assert end_res.status_code == 200
    assert end_res.json()["status"] == "completed"

    # 4. Attempting to post message to closed conversation returns 400
    msg_res = await client.post(
        f"/v1/conversations/{conv_id}/messages",
        json={"content": "Are you still there?"},
        headers=headers,
    )
    assert msg_res.status_code == 400
    data = msg_res.json()
    err_msg = data.get("detail") or data.get("error", {}).get("message", "")
    assert "closed" in err_msg.lower()


@pytest.mark.asyncio
async def test_orchestrator_multi_turn_with_mock_llm(db_session: AsyncSession):
    """Tests orchestrator message handling, turn progression, and DB persistence."""
    user, _ = await create_user_with_role(db_session, "admin")

    conv = Conversation(org_id=user.org_id, language="en", status="active", turn_count=0)
    db_session.add(conv)
    await db_session.commit()
    await db_session.refresh(conv)

    mock_provider = MockLLMProvider(["Thank you for reaching out! We specialize in AI receptionist solutions."])

    turn_resp = await ConversationOrchestrator.handle_message(
        db=db_session,
        conversation_id=conv.id,
        org_id=user.org_id,
        user_message_text="Hello, what services do you offer?",
        provider=mock_provider,
    )

    assert turn_resp.turn_number == 2
    assert turn_resp.customer_message.content == "Hello, what services do you offer?"
    assert turn_resp.assistant_reply.content == "Thank you for reaching out! We specialize in AI receptionist solutions."
    assert turn_resp.extracted_intelligence is not None

    # Verify messages in DB
    msgs_stmt = select(Message).where(Message.conversation_id == conv.id).order_by(Message.turn_number.asc())
    msgs = (await db_session.execute(msgs_stmt)).scalars().all()
    assert len(msgs) == 2
    assert msgs[0].speaker_role == "caller"
    assert msgs[1].speaker_role == "ai_agent"


@pytest.mark.asyncio
async def test_orchestrator_tool_calling_loop(db_session: AsyncSession):
    """Tests that when an LLM returns a tool call, orchestrator executes the tool and re-queries the LLM."""
    user, _ = await create_user_with_role(db_session, "admin")

    conv = Conversation(org_id=user.org_id, language="en", status="active", turn_count=0)
    db_session.add(conv)
    await db_session.commit()

    # Provider emits a tool call first, then natural language response
    tool_call_resp = LLMResponse(
        content=None,
        role="assistant",
        tool_calls=[
            ToolCall(
                id="call_hours_1",
                name="get_business_hours",
                arguments={"day_of_week": 1},
            )
        ],
        provider="mock",
    )
    final_reply_resp = LLMResponse(
        content="We are open Monday from 9:00 AM to 5:00 PM.",
        role="assistant",
        provider="mock",
    )

    mock_provider = MockLLMProvider([tool_call_resp, final_reply_resp])

    result = await ConversationOrchestrator.handle_message(
        db=db_session,
        conversation_id=conv.id,
        org_id=user.org_id,
        user_message_text="What are your hours on Monday?",
        provider=mock_provider,
    )

    assert len(result.tool_calls_executed) == 1
    assert result.tool_calls_executed[0]["tool"] == "get_business_hours"
    assert result.assistant_reply.content == "We are open Monday from 9:00 AM to 5:00 PM."


@pytest.mark.asyncio
async def test_context_manager_pruning_and_summary_memory(db_session: AsyncSession):
    """Tests that ContextManager bounds message history to configured limit and prepends summary."""
    user, _ = await create_user_with_role(db_session, "admin")

    conv = Conversation(
        org_id=user.org_id,
        language="en",
        status="active",
        turn_count=10,
        summary="Customer inquired about pricing for enterprise tier and agreed to callback.",
    )
    db_session.add(conv)
    await db_session.commit()

    # Add 10 messages
    for i in range(1, 11):
        role = "caller" if i % 2 == 1 else "ai_agent"
        m = Message(conversation_id=conv.id, turn_number=i, speaker_role=role, content=f"Message {i}")
        db_session.add(m)
    await db_session.commit()

    # Load context with history_limit=4
    context = await ContextManager.load_context(
        db=db_session,
        conversation_id=conv.id,
        org_id=user.org_id,
        history_limit=4,
    )

    # 1 system summary message + 4 recent messages = 5
    assert len(context) == 5
    assert context[0].role == "system"
    assert "Previous Conversation Summary" in context[0].content
    assert context[1].content == "Message 7"
    assert context[4].content == "Message 10"
