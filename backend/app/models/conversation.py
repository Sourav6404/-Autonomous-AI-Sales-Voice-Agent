"""Conversation dialog entity for a call session."""

import uuid
from typing import TYPE_CHECKING, List
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import GUID, Base, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.call import Call
    from backend.app.models.message import Message


class Conversation(Base, TimestampMixin):
    """Dialogue session tied 1:1 to a call."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    call_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("calls.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    turn_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    call: Mapped["Call"] = relationship("Call", back_populates="conversation")
    messages: Mapped[List["Message"]] = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.turn_number"
    )
