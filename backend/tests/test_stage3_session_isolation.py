"""Tests for Session Isolation across Users, Organizations, and Concurrent Conversations."""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.ai.conversation.orchestrator import ConversationOrchestrator
from backend.app.models.conversation import Conversation
from backend.tests.test_stage2_rbac import create_user_with_role
from backend.tests.test_stage3_ai_providers import MockLLMProvider


@pytest.mark.asyncio
async def test_cross_tenant_conversation_isolation(client: AsyncClient, db_session: AsyncSession):
    """Verifies that Tenant A cannot view, message, or end Tenant B's conversation."""
    user_a, token_a = await create_user_with_role(db_session, "admin")
    user_b, token_b = await create_user_with_role(db_session, "admin")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 1. Tenant A starts conversation
    res_a = await client.post("/v1/conversations", json={"customer_phone": "+11111111111"}, headers=headers_a)
    assert res_a.status_code == 201
    conv_a_id = res_a.json()["id"]

    # 2. Tenant B attempts to read Tenant A's conversation -> MUST return 404
    get_b = await client.get(f"/v1/conversations/{conv_a_id}", headers=headers_b)
    assert get_b.status_code == 404

    # 3. Tenant B attempts to post message to Tenant A's conversation -> MUST return 404
    msg_b = await client.post(
        f"/v1/conversations/{conv_a_id}/messages",
        json={"content": "Unauthorized message"},
        headers=headers_b,
    )
    assert msg_b.status_code == 404

    # 4. Tenant B attempts to end Tenant A's conversation -> MUST return 404
    end_b = await client.post(f"/v1/conversations/{conv_a_id}/end", headers=headers_b)
    assert end_b.status_code == 404


@pytest.mark.asyncio
async def test_simultaneous_conversations_maintain_independent_context(db_session: AsyncSession):
    """Verifies that multiple concurrent conversations for the same tenant
    maintain completely isolated turn counters and message contexts without crosstalk.
    """
    user, _ = await create_user_with_role(db_session, "admin")

    # Session 1: Customer Alice inquiring about cybersecurity
    conv1 = Conversation(org_id=user.org_id, language="en", status="active", turn_count=0)
    # Session 2: Customer Bob inquiring about cloud hosting
    conv2 = Conversation(org_id=user.org_id, language="en", status="active", turn_count=0)
    db_session.add_all([conv1, conv2])
    await db_session.commit()

    provider1 = MockLLMProvider(["Cybersecurity solutions include managed firewall and endpoint security."])
    provider2 = MockLLMProvider(["Cloud hosting packages start at scalable dedicated clusters."])

    # Interleave turns
    turn1 = await ConversationOrchestrator.handle_message(
        db=db_session,
        conversation_id=conv1.id,
        org_id=user.org_id,
        user_message_text="I am Alice and I need cybersecurity.",
        provider=provider1,
    )
    turn2 = await ConversationOrchestrator.handle_message(
        db=db_session,
        conversation_id=conv2.id,
        org_id=user.org_id,
        user_message_text="I am Bob and I need cloud hosting.",
        provider=provider2,
    )

    # Assert Session 1 isolated state
    assert turn1.turn_number == 2
    assert turn1.customer_message.content == "I am Alice and I need cybersecurity."
    assert "Cybersecurity" in turn1.assistant_reply.content

    # Assert Session 2 isolated state
    assert turn2.turn_number == 2
    assert turn2.customer_message.content == "I am Bob and I need cloud hosting."
    assert "Cloud hosting" in turn2.assistant_reply.content

    # Inspect messages received by mock provider 2: MUST NOT contain Alice's query
    received_by_provider2 = provider2.received_messages[0]
    provider2_texts = [m.content for m in received_by_provider2 if m.content]
    assert not any("Alice" in t for t in provider2_texts)
    assert not any("cybersecurity" in t.lower() for t in provider2_texts)
