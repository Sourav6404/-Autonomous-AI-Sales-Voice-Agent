"""Call session record."""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import GUID, Base, TenantMixin, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.organization import Organization
    from backend.app.models.customer import Customer
    from backend.app.models.department import Department
    from backend.app.models.employee import Employee
    from backend.app.models.conversation import Conversation
    from backend.app.models.call_summary import CallSummary
    from backend.app.models.lead import Lead


class Call(Base, TenantMixin, TimestampMixin):
    """Inbound or outbound telephone call session."""

    __tablename__ = "calls"
    __table_args__ = (
        CheckConstraint(
            "status IN ('initiated', 'in_progress', 'completed', 'handed_off', 'dropped', 'failed')",
            name="ck_calls_valid_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    department_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    taken_over_by_employee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    telephony_call_sid: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True, nullable=True)
    caller_phone_number: Mapped[str] = mapped_column(String(50), nullable=False)
    callee_phone_number: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="initiated", index=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    recording_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    recording_consent_given: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sentiment_overall: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization", back_populates="calls")
    customer: Mapped[Optional["Customer"]] = relationship("Customer", back_populates="calls")
    department: Mapped[Optional["Department"]] = relationship("Department", back_populates="calls")
    conversation: Mapped[Optional["Conversation"]] = relationship(
        "Conversation", back_populates="call", uselist=False, cascade="all, delete-orphan"
    )
    call_summary: Mapped[Optional["CallSummary"]] = relationship(
        "CallSummary", back_populates="call", uselist=False, cascade="all, delete-orphan"
    )
    lead: Mapped[Optional["Lead"]] = relationship("Lead", back_populates="call", uselist=False)
