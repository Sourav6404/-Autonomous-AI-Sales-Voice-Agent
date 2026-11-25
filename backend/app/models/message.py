"""Message turn entity within a conversation."""

import uuid
from typing import TYPE_CHECKING, Optional
from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import GUID, Base, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.conversation import Conversation


class Message(Base, TimestampMixin):
    """Individual speaker turn in a call conversation."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "turn_number", name="uq_messages_conversation_turn"),
        CheckConstraint(
            "speaker_role IN ('caller', 'ai_agent', 'human_agent', 'system')",
            name="ck_messages_valid_speaker",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker_role: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(Numeric(4, 3), nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")
