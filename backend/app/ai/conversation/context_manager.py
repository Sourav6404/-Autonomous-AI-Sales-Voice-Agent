"""Conversation history windowing, context construction, and token bounds management."""

import logging
from typing import List, Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.ai.providers.base import BaseLLMProvider, ChatMessage
from backend.app.core.config import settings
from backend.app.models.conversation import Conversation
from backend.app.models.message import Message

logger = logging.getLogger(__name__)


class ContextManager:
    """Manages context assembly, bounded history loading, and progressive summarization."""

    @classmethod
    async def load_context(
        cls,
        db: AsyncSession,
        conversation_id: UUID,
        org_id: UUID,
        history_limit: Optional[int] = None,
    ) -> List[ChatMessage]:
        """Loads bounded historical turns and prepends past conversation summary if present."""
        limit = history_limit or settings.CONVERSATION_HISTORY_LIMIT

        # Fetch conversation
        conv_res = await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.org_id == org_id,
            )
        )
        conv = conv_res.scalar_one_or_none()

        context_messages: List[ChatMessage] = []

        # If summary exists from older pruned turns, inject as system memory
        if conv and conv.summary:
            context_messages.append(
                ChatMessage(
                    role="system",
                    content=f"[Context Memory - Previous Conversation Summary]: {conv.summary}",
                )
            )

        # Fetch recent messages ordered by turn_number ASC
        # Fetch up to `limit` most recent messages
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.turn_number.desc())
            .limit(limit)
        )
        res = await db.execute(stmt)
        recent_messages = list(reversed(res.scalars().all()))

        for m in recent_messages:
            # Map DB speaker_role to LLM role
            llm_role = "user" if m.speaker_role == "caller" else "assistant"
            if m.speaker_role == "system":
                llm_role = "system"
            elif m.speaker_role == "human_agent":
                llm_role = "assistant"

            context_messages.append(
                ChatMessage(
                    role=llm_role,
                    content=m.content,
                )
            )

        return context_messages

    @classmethod
    async def generate_and_update_summary(
        cls,
        db: AsyncSession,
        conversation: Conversation,
        provider: BaseLLMProvider,
    ) -> Optional[str]:
        """Progressively generates an analytical summary when transcript exceeds threshold."""
        # Load all messages for complete summarization
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.turn_number.asc())
        )
        res = await db.execute(stmt)
        messages = res.scalars().all()

        if len(messages) < 4:
            return None

        transcript = "\n".join(
            f"{m.speaker_role.upper()}: {m.content}" for m in messages
        )

        prior_context = (
            f"Prior Conversation Summary:\n{conversation.summary}\n\n"
            if conversation.summary
            else ""
        )

        prompt = [
            ChatMessage(
                role="system",
                content=(
                    "You are an analytical AI receptionist summarizer. "
                    "Produce a concise 2-3 sentence executive summary of the following customer conversation. "
                    "Highlight customer intent, key points discussed, and any pending questions."
                ),
            ),
            ChatMessage(role="user", content=f"{prior_context}Transcript of conversation:\n{transcript}"),
        ]

        try:
            summary_resp = await provider.generate_response(
                messages=prompt,
                temperature=0.3,
                max_tokens=256,
            )
            if summary_resp.content:
                conversation.summary = summary_resp.content.strip()
                await db.flush()
                return conversation.summary
        except Exception as e:
            logger.warning("Failed to generate opportunistic conversation summary: %s", e)

        return None
