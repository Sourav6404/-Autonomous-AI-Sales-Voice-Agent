"""Appointment booking entity with schedule constraints."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import GUID, Base, TenantMixin, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.customer import Customer
    from backend.app.models.employee import Employee
    from backend.app.models.lead import Lead
    from backend.app.models.user import User


class Appointment(Base, TenantMixin, TimestampMixin):
    """Scheduled calendar meeting between customer and sales/support staff."""

    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("start_time < end_time", name="ck_appointments_time_order"),
        CheckConstraint(
            "status IN ('scheduled', 'confirmed', 'completed', 'cancelled', 'no_show')",
            name="ck_appointments_valid_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    originating_call_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("calls.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    purpose: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="scheduled", index=True, nullable=False)
    booking_source: Mapped[str] = mapped_column(String(50), default="ai_receptionist", nullable=False)
    meeting_type: Mapped[str] = mapped_column(String(100), default="Sales Discovery Call", nullable=False)
    meeting_link_or_phone: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    calendar_event_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    customer: Mapped["Customer"] = relationship("Customer", back_populates="appointments")
    employee: Mapped["Employee"] = relationship("Employee", back_populates="appointments")
    lead: Mapped[Optional["Lead"]] = relationship("Lead", foreign_keys=[lead_id])
