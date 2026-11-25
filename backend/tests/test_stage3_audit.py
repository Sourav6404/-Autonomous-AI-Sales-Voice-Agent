"""Comprehensive pre-commit audit tests for Stage 3 AI Conversation Engine.

Covers:
- Same-conversation concurrent messages (row-locking & turn serialization)
- Provider streaming and tool-call parsing (OpenAI & Gemini REST contract mocks)
- Tool loop limits (MAX_TOOL_LOOPS cutoff)
- Role-based authorization failures on Tool Registry
- Atomic failure rollback on database during error
- Progressive summarization context preservation
- Request validation and blank message rejection
"""

import asyncio
import json
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional
import httpx
import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.ai.conversation.context_manager import ContextManager
from backend.app.ai.conversation.orchestrator import ConversationOrchestrator
from backend.app.ai.providers.base import (
    AIProviderTransientError,
    BaseLLMProvider,
    ChatMessage,
    LLMResponse,
    ToolCall,
    ToolDefinition,
)
from backend.app.ai.providers.gemini_provider import GeminiProvider
from backend.app.ai.providers.openai_provider import OpenAIProvider
from backend.app.ai.tools.registry import ToolExecutionContext, ToolRegistry
from backend.app.core.exceptions import AppException
from backend.app.models.conversation import Conversation
from backend.app.models.message import Message
from backend.app.models.organization import Organization
from backend.app.schemas.conversation import MessageCreateRequest
from backend.tests.test_stage2_rbac import create_user_with_role
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Mock Providers for Audit Tests
# ---------------------------------------------------------------------------

class InfiniteToolLoopMockProvider(BaseLLMProvider):
    """Always returns a tool call to test that MAX_TOOL_LOOPS halts execution."""

    def __init__(self):
        super().__init__(provider_name="mock_loop", model="loop-model")
        self.call_count = 0

    async def generate_response(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolDefinition]] = None,
        response_schema: Optional[Dict[str, Any]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        self.call_count += 1
        return LLMResponse(
            content=None,
            role="assistant",
            tool_calls=[
                ToolCall(
                    id=f"call_{self.call_count}",
                    name="get_business_hours",
                    arguments={"day_of_week": 1},
                )
            ],
            provider=self.provider_name,
        )

    async def generate_stream(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[str, None]:
        yield "mock"


class FailingProvider(BaseLLMProvider):
    """Simulates provider outage mid-dialogue to test atomic database rollback."""

    def __init__(self):
        super().__init__(provider_name="failing_mock", model="fail-model")

    async def generate_response(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolDefinition]] = None,
        response_schema: Optional[Dict[str, Any]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        raise AIProviderTransientError("External AI provider upstream service unavailable 503.", self.provider_name)

    async def generate_stream(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[str, None]:
        raise AIProviderTransientError("Stream connection dropped.", self.provider_name)
        yield ""  # pragma: no cover


class MockSummarizerProvider(BaseLLMProvider):
    """Echoes received prompt to verify prior summary retention."""

    def __init__(self):
        super().__init__(provider_name="mock_summarizer", model="sum-model")
        self.received_prompt: Optional[str] = None

    async def generate_response(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolDefinition]] = None,
        response_schema: Optional[Dict[str, Any]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        user_msg = next((m.content for m in messages if m.role == "user"), "")
        self.received_prompt = user_msg
        return LLMResponse(
            content="Customer inquired about services and pricing.",
            role="assistant",
            provider=self.provider_name,
        )

    async def generate_stream(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[str, None]:
        yield "summary"


# ---------------------------------------------------------------------------
# Audit Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_loop_limit_strictly_enforced(db_session: AsyncSession):
    """Verifies that an agent emitting tool calls repeatedly is cut off at MAX_TOOL_LOOPS."""
    org = Organization(name="Loop Corp", slug=f"loop-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.flush()

    conv = Conversation(org_id=org.id, language="en", status="active", turn_count=0)
    db_session.add(conv)
    await db_session.commit()

    loop_provider = InfiniteToolLoopMockProvider()

    res = await ConversationOrchestrator.handle_message(
        db=db_session,
        conversation_id=conv.id,
        org_id=org.id,
        user_message_text="Trigger infinite loop",
        provider=loop_provider,
    )

    # loop_count in orchestrator must not exceed MAX_TOOL_LOOPS (3)
    assert len(res.tool_calls_executed) == ConversationOrchestrator.MAX_TOOL_LOOPS
    assert res.assistant_reply.content is not None
    assert res.turn_number == 2


@pytest.mark.asyncio
async def test_tool_registry_rbac_authorization_failure():
    """Verifies that ToolRegistry rejects callers with insufficient role privileges."""
    reg = ToolRegistry()

    class AdminOnlyInput(BaseModel):
        target: str = Field(..., description="Target name")

    @reg.register(
        name="admin_action",
        description="Restricted admin action",
        input_schema=AdminOnlyInput,
        required_role="admin",
    )
    async def admin_tool(args: AdminOnlyInput, ctx: ToolExecutionContext):
        return {"success": True}

    # 1. Customer caller fails
    cust_ctx = ToolExecutionContext(
        org_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        caller_role="customer",
    )
    res_cust = await reg.execute_tool("admin_action", {"target": "cluster"}, cust_ctx)
    assert "error" in res_cust
    assert "Permission denied" in res_cust["error"]

    # 2. Receptionist caller fails
    rec_ctx = ToolExecutionContext(
        org_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        caller_role="receptionist",
    )
    res_rec = await reg.execute_tool("admin_action", {"target": "cluster"}, rec_ctx)
    assert "error" in res_rec
    assert "Permission denied" in res_rec["error"]

    # 3. Admin caller succeeds
    admin_ctx = ToolExecutionContext(
        org_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        caller_role="admin",
    )
    res_admin = await reg.execute_tool("admin_action", {"target": "cluster"}, admin_ctx)
    assert res_admin == {"success": True}


@pytest.mark.asyncio
async def test_orchestrator_failure_atomic_rollback(db_session: AsyncSession):
    """Verifies that an LLM failure leaves zero partially written messages in the database."""
    org = Organization(name="Fail Corp", slug=f"fail-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.flush()

    conv = Conversation(org_id=org.id, language="en", status="active", turn_count=0)
    db_session.add(conv)
    await db_session.commit()
    conv_id = conv.id
    org_id = org.id

    failing_provider = FailingProvider()

    with pytest.raises(AIProviderTransientError):
        await ConversationOrchestrator.handle_message(
            db=db_session,
            conversation_id=conv_id,
            org_id=org_id,
            user_message_text="This will fail during generation",
            provider=failing_provider,
        )

    # Verify no customer or assistant messages were committed
    msg_stmt = select(Message).where(Message.conversation_id == conv_id)
    msg_res = await db_session.execute(msg_stmt)
    messages = msg_res.scalars().all()
    assert len(messages) == 0

    # Verify conversation turn_count remains 0
    conv_stmt = select(Conversation).where(Conversation.id == conv_id)
    conv_res = await db_session.execute(conv_stmt)
    refreshed_conv = conv_res.scalar_one()
    assert refreshed_conv.turn_count == 0


@pytest.mark.asyncio
async def test_progressive_summarization_preserves_cumulative_context(db_session: AsyncSession):
    """Verifies that existing conversation summaries are passed into subsequent summarization turns."""
    org = Organization(name="Memory Corp", slug=f"mem-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.flush()

    conv = Conversation(
        org_id=org.id,
        language="en",
        status="active",
        turn_count=4,
        summary="Customer previously requested pricing for 50 licenses.",
    )
    db_session.add(conv)
    await db_session.flush()

    # Add 4 messages
    for i in range(1, 5):
        m = Message(
            conversation_id=conv.id,
            turn_number=i,
            speaker_role="caller" if i % 2 == 1 else "ai_agent",
            content=f"Message turn number {i}",
        )
        db_session.add(m)
    await db_session.commit()

    sum_provider = MockSummarizerProvider()

    # Generate summary
    new_summary = await ContextManager.generate_and_update_summary(
        db=db_session,
        conversation=conv,
        provider=sum_provider,
    )

    assert new_summary is not None
    assert sum_provider.received_prompt is not None
    # Crucial assertion: prior summary must be explicitly injected in the summarization prompt
    assert "Prior Conversation Summary:" in sum_provider.received_prompt
    assert "50 licenses" in sum_provider.received_prompt


@pytest.mark.asyncio
async def test_whitespace_message_validation():
    """Verifies that MessageCreateRequest rejects whitespace-only messages."""
    with pytest.raises(ValueError, match="cannot be blank"):
        MessageCreateRequest(content="    \n\t  ")

    # Valid non-empty message passes and strips
    req = MessageCreateRequest(content="   Hello sales!   ")
    assert req.content == "Hello sales!"


@pytest.mark.asyncio
async def test_openai_provider_mock_transport_parsing():
    """Tests OpenAIProvider parsing with simulated HTTP responses (tool calls and usage)."""
    mock_payload = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Checking the hours for you.",
                    "tool_calls": [
                        {
                            "id": "call_12345",
                            "type": "function",
                            "function": {
                                "name": "get_business_hours",
                                "arguments": "{\"day_of_week\": 2}",
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {
            "prompt_tokens": 15,
            "completion_tokens": 20,
            "total_tokens": 35,
        },
    }

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_payload)

    transport = httpx.MockTransport(mock_handler)
    provider = OpenAIProvider(api_key="sk-test-mock-key")

    async with httpx.AsyncClient(transport=transport) as mock_client:
        messages = [ChatMessage(role="user", content="What are your hours on Tuesday?")]
        res = await provider.generate_response(messages, client=mock_client)

        assert res.model == "gpt-4o-mini"
        assert res.content == "Checking the hours for you."
        assert res.finish_reason == "tool_calls"
        assert res.usage == {"prompt_tokens": 15, "completion_tokens": 20, "total_tokens": 35}
        assert res.tool_calls is not None
        assert len(res.tool_calls) == 1
        assert res.tool_calls[0].name == "get_business_hours"
        assert res.tool_calls[0].arguments == {"day_of_week": 2}


@pytest.mark.asyncio
async def test_gemini_provider_mock_contract_formatting():
    """Tests Google Gemini provider payload formatting, system instruction, and model prefix removal."""
    provider = GeminiProvider(api_key="gemini-mock-key", model="models/gemini-1.5-flash")

    messages = [
        ChatMessage(role="system", content="You are a helpful receptionist."),
        ChatMessage(role="user", content="Hello!"),
        ChatMessage(role="assistant", content="Hi there!", tool_calls=[
            ToolCall(id="tc_1", name="get_business_information", arguments={})
        ]),
        ChatMessage(role="tool", name="get_business_information", content="{\"name\": \"Acme\"}"),
    ]

    system_instruction, contents = provider._format_contents(messages)
    assert system_instruction == {"parts": [{"text": "You are a helpful receptionist."}]}
    assert len(contents) == 3
    assert contents[0]["role"] == "user"
    assert contents[1]["role"] == "model"
    assert "functionCall" in contents[1]["parts"][1]
    assert contents[2]["role"] == "function"


@pytest.mark.asyncio
async def test_openai_provider_sse_streaming_mock():
    """Tests SSE streaming parser in OpenAIProvider with chunk boundaries."""
    sse_body = (
        b"data: {\"choices\": [{\"delta\": {\"content\": \"Hello\"}}]}\n\n"
        b"data: {\"choices\": [{\"delta\": {\"content\": \" from\"}}]}\n\n"
        b"data: {\"choices\": [{\"delta\": {\"content\": \" FortiSales\"}}]}\n\n"
        b"data: [DONE]\n\n"
    )

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_body)

    transport = httpx.MockTransport(mock_handler)
    provider = OpenAIProvider(api_key="sk-test-stream")

    chunks = []
    async with httpx.AsyncClient(transport=transport) as mock_client:
        messages = [ChatMessage(role="user", content="Hi")]
        async for chunk in provider.generate_stream(messages, client=mock_client):
            chunks.append(chunk)

    assert chunks == ["Hello", " from", " FortiSales"]


@pytest.mark.asyncio
async def test_gemini_provider_sse_streaming_mock():
    """Tests SSE streaming parser in GeminiProvider with chunk boundaries."""
    sse_body = (
        b"data: {\"candidates\": [{\"content\": {\"parts\": [{\"text\": \"Welcome\"}]}}]}\n\n"
        b"data: {\"candidates\": [{\"content\": {\"parts\": [{\"text\": \" to AI Reception\"}]}}]}\n\n"
    )

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_body)

    transport = httpx.MockTransport(mock_handler)
    provider = GeminiProvider(api_key="gemini-test-stream")

    chunks = []
    async with httpx.AsyncClient(transport=transport) as mock_client:
        messages = [ChatMessage(role="user", content="Hi")]
        async for chunk in provider.generate_stream(messages, client=mock_client):
            chunks.append(chunk)

    assert chunks == ["Welcome", " to AI Reception"]


# ---------------------------------------------------------------------------
# PostgreSQL Concurrency Integration Test
# ---------------------------------------------------------------------------

from backend.tests.test_appointment_postgres_concurrency import POSTGRES_ONLINE
from backend.app.core.config import settings
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


class DeterministicMockProvider(BaseLLMProvider):
    def __init__(self, reply: str = "Default reply"):
        super().__init__(provider_name="det_mock", model="mock")
        self.reply = reply

    async def generate_response(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolDefinition]] = None,
        response_schema: Optional[Dict[str, Any]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        return LLMResponse(content=self.reply, role="assistant", provider=self.provider_name)

    async def generate_stream(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[str, None]:
        yield self.reply


@pytest.mark.skipif(not POSTGRES_ONLINE, reason="Live PostgreSQL required for row-lock concurrency test")
@pytest.mark.asyncio
async def test_postgres_same_conversation_concurrent_messages():
    """Verifies PostgreSQL row-level locking (with_for_update) serializes simultaneous messages
    to the same conversation session without race conditions or integrity errors.
    """
    engine = create_async_engine(settings.async_database_url, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as setup_session:
        org = Organization(name="PG Concurrency Org", slug=f"pg-conc-{uuid.uuid4().hex[:8]}")
        setup_session.add(org)
        await setup_session.flush()

        conv = Conversation(org_id=org.id, language="en", status="active", turn_count=0)
        setup_session.add(conv)
        await setup_session.commit()
        conv_id = conv.id
        org_id = org.id

    # Define 2 concurrent message senders with separate sessions
    async def send_msg(text_val: str, reply_val: str):
        provider = DeterministicMockProvider(reply=reply_val)
        async with session_factory() as session:
            return await ConversationOrchestrator.handle_message(
                db=session,
                conversation_id=conv_id,
                org_id=org_id,
                user_message_text=text_val,
                provider=provider,
            )

    # Launch both concurrently
    res1, res2 = await asyncio.gather(
        send_msg("Message A from user", "Reply A from AI"),
        send_msg("Message B from user", "Reply B from AI"),
    )

    # Validate results
    assert res1.conversation_id == conv_id
    assert res2.conversation_id == conv_id

    # One turn must be 2, other must be 4
    turn_numbers = {res1.turn_number, res2.turn_number}
    assert turn_numbers == {2, 4}

    # Verify database state in PostgreSQL
    async with session_factory() as verify_session:
        msg_stmt = (
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.turn_number.asc())
        )
        msg_res = await verify_session.execute(msg_stmt)
        all_msgs = msg_res.scalars().all()

        assert len(all_msgs) == 4
        assert [m.turn_number for m in all_msgs] == [1, 2, 3, 4]
        assert [m.speaker_role for m in all_msgs] == ["caller", "ai_agent", "caller", "ai_agent"]

        conv_stmt = select(Conversation).where(Conversation.id == conv_id)
        conv_res = await verify_session.execute(conv_stmt)
        final_conv = conv_res.scalar_one()
        assert final_conv.turn_count == 4

    await engine.dispose()
