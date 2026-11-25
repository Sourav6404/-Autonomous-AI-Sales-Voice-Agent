"""Conversation dialog entity for a call or chat session."""

import uuid
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import GUID, Base, TenantMixin, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.call import Call
    from backend.app.models.message import Message
    from backend.app.models.organization import Organization


class Conversation(Base, TenantMixin, TimestampMixin):
    """Dialogue session tied 1:1 to a call or chat interaction."""

    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'completed', 'handed_off', 'abandoned')",
            name="ck_conversations_valid_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    call_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("calls.id", ondelete="CASCADE"), unique=True, nullable=True
    )
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False, index=True)
    turn_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization")
    call: Mapped[Optional["Call"]] = relationship("Call", back_populates="conversation")
    messages: Mapped[List["Message"]] = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.turn_number"
    )
