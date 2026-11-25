"""Centralized conversation orchestrator executing multi-turn dialog and tool execution."""

import json
import logging
import time
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.ai.conversation.context_manager import ContextManager
from backend.app.ai.conversation.prompt_manager import PromptManager
from backend.app.ai.providers.base import BaseLLMProvider, ChatMessage, LLMResponse
from backend.app.ai.providers.factory import get_ai_provider
from backend.app.ai.tools.initial_tools import tool_registry
from backend.app.ai.tools.registry import ToolExecutionContext
from backend.app.core.config import settings
from backend.app.core.exceptions import AppException
from backend.app.models.conversation import Conversation
from backend.app.models.message import Message
from backend.app.schemas.conversation import (
    CustomerIntentExtraction,
    MessageResponse,
    OrchestrationTurnResponse,
)

logger = logging.getLogger(__name__)


class ConversationOrchestrator:
    """Orchestrates incoming customer messages, LLM queries, tool loops, and persistence."""

    MAX_TOOL_LOOPS = 3

    @classmethod
    async def handle_message(
        cls,
        db: AsyncSession,
        conversation_id: UUID,
        org_id: UUID,
        user_message_text: str,
        provider: Optional[BaseLLMProvider] = None,
        user_id: Optional[UUID] = None,
    ) -> OrchestrationTurnResponse:
        """Processes a customer message turn through context loading, LLM inference, tools, and DB persistence."""
        start_time = time.time()
        active_provider = provider or get_ai_provider()

        try:
            # 1. Load Conversation session with row lock and enforce lifecycle state
            conv_res = await db.execute(
                select(Conversation)
                .where(
                    Conversation.id == conversation_id,
                    Conversation.org_id == org_id,
                )
                .with_for_update()
            )
            conversation = conv_res.scalar_one_or_none()

            if not conversation:
                raise AppException(
                    message=f"Conversation '{conversation_id}' was not found.",
                    code="CONVERSATION_NOT_FOUND",
                    status_code=404,
                )

            if conversation.status in ("completed", "abandoned"):
                raise AppException(
                    message=f"Conversation session '{conversation_id}' is closed ({conversation.status}). Further messages are rejected.",
                    code="CONVERSATION_CLOSED",
                    status_code=400,
                )

            # 2. Persist Customer Message turn
            customer_turn_num = conversation.turn_count + 1
            customer_msg = Message(
                conversation_id=conversation.id,
                turn_number=customer_turn_num,
                speaker_role="caller",
                content=user_message_text.strip(),
            )
            db.add(customer_msg)
            conversation.turn_count = customer_turn_num
            await db.flush()
            await db.refresh(customer_msg)

            # 3. Construct System Prompt & Bounded Context
            system_prompt = await PromptManager.build_system_prompt(db=db, org_id=org_id)
            context_messages = await ContextManager.load_context(
                db=db,
                conversation_id=conversation_id,
                org_id=org_id,
            )

            full_dialogue: List[ChatMessage] = [
                ChatMessage(role="system", content=system_prompt),
                *context_messages,
            ]

            # 4. LLM Generation & Tool Loop
            tool_definitions = tool_registry.get_tool_definitions()
            executed_tools: List[Dict[str, Any]] = []

            response: LLMResponse = await active_provider.generate_response(
                messages=full_dialogue,
                tools=tool_definitions,
            )

            # Loop if LLM emits tool calls (bounded by MAX_TOOL_LOOPS)
            loop_count = 0
            while response.tool_calls and loop_count < cls.MAX_TOOL_LOOPS:
                loop_count += 1
                # Append model turn with tool calls to prompt history
                full_dialogue.append(
                    ChatMessage(
                        role="assistant",
                        content=response.content,
                        tool_calls=response.tool_calls,
                    )
                )

                tool_context = ToolExecutionContext(
                    org_id=org_id,
                    conversation_id=conversation_id,
                    db=db,
                    user_id=user_id,
                    caller_role="customer",
                )

                for tc in response.tool_calls:
                    logger.info("Executing tool '%s' for conversation %s", tc.name, conversation_id)
                    tool_output = await tool_registry.execute_tool(
                        name=tc.name,
                        arguments=tc.arguments,
                        context=tool_context,
                    )
                    executed_tools.append({
                        "tool": tc.name,
                        "arguments": tc.arguments,
                        "result": tool_output,
                    })

                    # Append tool result to dialogue
                    full_dialogue.append(
                        ChatMessage(
                            role="tool",
                            name=tc.name,
                            tool_call_id=tc.id,
                            content=json.dumps(tool_output) if isinstance(tool_output, dict) else str(tool_output),
                        )
                    )

                # Re-query provider with tool outputs
                response = await active_provider.generate_response(
                    messages=full_dialogue,
                    tools=tool_definitions,
                )

            assistant_text = response.content or "Thank you for contacting us. How else may I assist you today?"
            elapsed_ms = int((time.time() - start_time) * 1000)

            # 5. Persist Assistant Message turn
            assistant_turn_num = conversation.turn_count + 1
            assistant_msg = Message(
                conversation_id=conversation.id,
                turn_number=assistant_turn_num,
                speaker_role="ai_agent",
                content=assistant_text,
                latency_ms=elapsed_ms,
            )
            db.add(assistant_msg)
            conversation.turn_count = assistant_turn_num
            await db.flush()
            await db.refresh(assistant_msg)

            # 6. Opportunistic Structured Extraction
            extracted = cls._extract_turn_intelligence(user_message_text, assistant_text)

            # 7. Progressive Summarization if threshold reached
            if conversation.turn_count >= settings.CONVERSATION_SUMMARY_THRESHOLD:
                await ContextManager.generate_and_update_summary(db, conversation, active_provider)

            await db.commit()
            await db.refresh(conversation)

            return OrchestrationTurnResponse(
                conversation_id=conversation.id,
                turn_number=assistant_turn_num,
                customer_message=MessageResponse.model_validate(customer_msg),
                assistant_reply=MessageResponse.model_validate(assistant_msg),
                tool_calls_executed=executed_tools,
                extracted_intelligence=extracted,
                conversation_status=conversation.status,
            )
        except Exception:
            await db.rollback()
            raise

    @classmethod
    def _extract_turn_intelligence(cls, user_text: str, assistant_text: str) -> CustomerIntentExtraction:
        """Performs structured extraction of customer purpose, urgency, and sentiment."""
        lower = user_text.lower()

        # Heuristic intent detection
        intent = "general_inquiry"
        if any(w in lower for w in ["price", "pricing", "cost", "quote", "rate"]):
            intent = "pricing"
        elif any(w in lower for w in ["appointment", "book", "schedule", "meet", "demo"]):
            intent = "booking"
        elif any(w in lower for w in ["broken", "help", "issue", "problem", "support"]):
            intent = "support"

        # Urgency
        urgency = "medium"
        if any(w in lower for w in ["asap", "emergency", "urgent", "immediately", "right now"]):
            urgency = "high"

        # Sentiment
        sentiment = "neutral"
        if any(w in lower for w in ["thank", "great", "awesome", "perfect", "good", "helpful"]):
            sentiment = "positive"
        elif any(w in lower for w in ["angry", "bad", "terrible", "ridiculous", "frustrated", "hate"]):
            sentiment = "negative"

        needs_handoff = any(w in lower for w in ["human", "person", "representative", "agent", "supervisor"])

        return CustomerIntentExtraction(
            primary_intent=intent,
            urgency=urgency,
            sentiment=sentiment,
            needs_human_intervention=needs_handoff,
            confidence_score=0.88,
        )
