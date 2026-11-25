"""Follow-up action item entity assigned to staff."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import GUID, Base, TenantMixin, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.lead import Lead
    from backend.app.models.employee import Employee


class FollowUpTask(Base, TenantMixin, TimestampMixin):
    """Action item generated for employee following a call or lead event."""

    __tablename__ = "follow_up_tasks"
    __table_args__ = (
        CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'urgent')",
            name="ck_follow_up_tasks_valid_priority",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("leads.id", ondelete="CASCADE"), nullable=True, index=True
    )
    assigned_employee_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    lead: Mapped[Optional["Lead"]] = relationship("Lead", back_populates="follow_up_tasks")
    assigned_employee: Mapped["Employee"] = relationship("Employee", back_populates="follow_up_tasks")
