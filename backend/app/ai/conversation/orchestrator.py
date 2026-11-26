"""Centralized conversation orchestrator executing multi-turn dialog and tool execution."""

import json
import logging
import time
from typing import Any, Dict, List, Optional, Union
from uuid import UUID
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.ai.conversation.context_manager import ContextManager
from backend.app.ai.conversation.prompt_manager import PromptManager
from backend.app.ai.providers.base import BaseLLMProvider, ChatMessage, LLMResponse
from backend.app.ai.providers.factory import get_ai_provider
from backend.app.ai.tools.initial_tools import tool_registry
import backend.app.ai.tools.appointment_tools  # Register appointment tools
from backend.app.ai.tools.registry import ToolExecutionContext
from backend.app.core.config import settings
from backend.app.core.exceptions import AppException
from backend.app.models.call import Call
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
        provider: Optional[Union[BaseLLMProvider, str]] = None,
        user_id: Optional[UUID] = None,
        enable_ai_fallback: bool = False,
    ) -> OrchestrationTurnResponse:
        """Processes a customer message turn through context loading, LLM inference, tools, and DB persistence."""
        start_time = time.time()
        if isinstance(provider, str):
            active_provider = get_ai_provider(provider)
        elif provider is not None:
            active_provider = provider
        else:
            active_provider = get_ai_provider()

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

            try:
                response: LLMResponse = await active_provider.generate_response(
                    messages=full_dialogue,
                    tools=tool_definitions,
                )
            except Exception as provider_err:
                fallback_provider = None
                if active_provider.provider_name == "openai" and settings.GEMINI_API_KEY:
                    logger.warning(
                        "Primary provider 'openai' failed (%s). Attempting automatic failover to 'gemini'.",
                        provider_err,
                    )
                    from backend.app.ai.providers.gemini_provider import GeminiProvider
                    fallback_provider = GeminiProvider(api_key=settings.GEMINI_API_KEY, model=settings.GEMINI_MODEL)
                elif active_provider.provider_name == "gemini" and settings.OPENAI_API_KEY and settings.OPENAI_API_KEY.startswith("sk-"):
                    logger.warning(
                        "Primary provider 'gemini' failed (%s). Attempting automatic failover to 'openai'.",
                        provider_err,
                    )
                    from backend.app.ai.providers.openai_provider import OpenAIProvider
                    fallback_provider = OpenAIProvider(api_key=settings.OPENAI_API_KEY, model=settings.OPENAI_MODEL)

                if fallback_provider:
                    active_provider = fallback_provider
                    response = await active_provider.generate_response(
                        messages=full_dialogue,
                        tools=tool_definitions,
                    )
                else:
                    raise

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
        except AppException:
            await db.rollback()
            raise
        except Exception as exc:
            if not enable_ai_fallback:
                await db.rollback()
                raise

            logger.exception(
                "AI generation failed for conversation %s: %s. Initiating graceful AI fallback.",
                conversation_id, exc
            )
            try:
                await db.rollback()
                conv_query = select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.org_id == org_id,
                )
                conv_res = await db.execute(conv_query)
                conv = conv_res.scalar_one_or_none()
                if conv:
                    turn_num = conv.turn_count + 1
                    cust_msg = Message(
                        conversation_id=conv.id,
                        turn_number=turn_num,
                        speaker_role="caller",
                        content=user_message_text,
                    )
                    db.add(cust_msg)

                    fallback_text = (
                        "I apologize, but I am currently experiencing technical difficulties retrieving that information. "
                        "I have escalated this conversation to our support team, and a representative will follow up with you promptly."
                    )
                    asst_turn_num = turn_num + 1
                    asst_msg = Message(
                        conversation_id=conv.id,
                        turn_number=asst_turn_num,
                        speaker_role="ai_agent",
                        content=fallback_text,
                        latency_ms=0,
                    )
                    db.add(asst_msg)
                    conv.turn_count = asst_turn_num
                    conv.status = "handed_off"

                    if conv.call_id:
                        call_res = await db.execute(select(Call).where(Call.id == conv.call_id, Call.org_id == org_id))
                        call = call_res.scalar_one_or_none()
                        if call:
                            call.status = "handed_off"
                            call.outcome = "ai_fallback_handoff"
                            call.notes = f"AI fallback triggered: {str(exc)[:150]}"

                    await db.commit()
                    await db.refresh(cust_msg)
                    await db.refresh(asst_msg)
                    await db.refresh(conv)

                    return OrchestrationTurnResponse(
                        conversation_id=conv.id,
                        turn_number=asst_turn_num,
                        customer_message=MessageResponse.model_validate(cust_msg),
                        assistant_reply=MessageResponse.model_validate(asst_msg),
                        tool_calls_executed=[],
                        extracted_intelligence=CustomerIntentExtraction(
                            primary_intent="support",
                            urgency="high",
                            sentiment="neutral",
                            needs_human_intervention=True,
                            confidence_score=0.5,
                        ),
                        conversation_status="handed_off",
                    )
            except Exception as fallback_err:
                logger.error("Fallback handler failed: %s", fallback_err)
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

        handoff_keywords = [
            "human", "person", "representative", "agent", "supervisor",
            "operator", "talk to someone", "speak to someone", "real person",
            "sales rep", "transfer me", "connect me", "live person",
            "speak to human", "speak to person", "connect to sales",
            "transfer call", "human assistance", "manager"
        ]
        needs_handoff = any(w in lower for w in handoff_keywords)

        return CustomerIntentExtraction(
            primary_intent=intent,
            urgency=urgency,
            sentiment=sentiment,
            needs_human_intervention=needs_handoff,
            confidence_score=0.88,
        )
