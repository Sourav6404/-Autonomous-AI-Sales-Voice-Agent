"""Frequently Asked Questions (FAQ) model."""

import uuid
from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.models.base import GUID, Base, TenantMixin, TimestampMixin


class FAQ(Base, TenantMixin, TimestampMixin):
    """Business FAQ entry for AI knowledge retrieval."""

    __tablename__ = "faqs"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(100), default="General", index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
