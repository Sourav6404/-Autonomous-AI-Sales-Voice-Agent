"""Business policies model (cancellation, refunds, warranties, privacy)."""

import uuid
from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.models.base import GUID, Base, TenantMixin, TimestampMixin


class BusinessPolicy(Base, TenantMixin, TimestampMixin):
    """Organizational policy defining terms, conditions, cancellations, and rules."""

    __tablename__ = "business_policies"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    policy_type: Mapped[str] = mapped_column(
        String(100), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
