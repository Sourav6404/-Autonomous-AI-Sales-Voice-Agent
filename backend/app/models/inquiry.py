"""Inquiry entity for customer support and sales inquiries."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import GUID, Base, TenantMixin, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.organization import Organization
    from backend.app.models.customer import Customer
    from backend.app.models.call import Call
    from backend.app.models.employee import Employee


class Inquiry(Base, TenantMixin, TimestampMixin):
    """Customer inquiry or support ticket raised from a call."""

    __tablename__ = "inquiries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'in_progress', 'resolved', 'closed')",
            name="ck_inquiries_valid_status",
        ),
        CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'urgent')",
            name="ck_inquiries_valid_priority",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    originating_call_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("calls.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assigned_employee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="open", nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization")
    customer: Mapped["Customer"] = relationship("Customer")
    originating_call: Mapped[Optional["Call"]] = relationship("Call", foreign_keys=[originating_call_id])
    assigned_employee: Mapped[Optional["Employee"]] = relationship("Employee", foreign_keys=[assigned_employee_id])
