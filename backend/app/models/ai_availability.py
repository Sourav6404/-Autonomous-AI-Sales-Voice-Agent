"""Real-time operational status and emergency overrides for AI Receptionist."""

import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.models.base import GUID, Base, TenantMixin, TimestampMixin


class AIAvailability(Base, TenantMixin, TimestampMixin):
    """Dynamic operational state and manual overrides for AI Receptionist."""

    __tablename__ = "ai_availability"
    __table_args__ = (
        UniqueConstraint("org_id", "department_id", name="uq_ai_availability_org_dept"),
        CheckConstraint(
            "status IN ('online', 'offline', 'maintenance', 'takeover_only')",
            name="ck_ai_availability_valid_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    department_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("departments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(50), default="online", nullable=False)
    auto_schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    emergency_closure_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    emergency_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    temp_offline_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scheduled_status: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    scheduled_status_change_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status_change_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    changed_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
