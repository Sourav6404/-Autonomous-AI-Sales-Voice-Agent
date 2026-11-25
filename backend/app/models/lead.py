"""Lead entity representing qualified sales prospects."""

import uuid
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import GUID, Base, TenantMixin, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.organization import Organization
    from backend.app.models.customer import Customer
    from backend.app.models.call import Call
    from backend.app.models.employee import Employee
    from backend.app.models.follow_up_task import FollowUpTask


class Lead(Base, TenantMixin, TimestampMixin):
    """Qualified sales opportunity extracted from customer conversations."""

    __tablename__ = "leads"
    __table_args__ = (
        CheckConstraint("score BETWEEN 0 AND 100", name="ck_leads_score_range"),
        CheckConstraint(
            "status IN ('new', 'contacted', 'qualified', 'unqualified', 'converted', 'lost')",
            name="ck_leads_valid_status",
        ),
        CheckConstraint(
            "qualification_tier IN ('cold', 'warm', 'hot')",
            name="ck_leads_valid_tier",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    originating_call_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("calls.id", ondelete="SET NULL"), unique=True, nullable=True
    )
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="new", nullable=False)
    qualification_tier: Mapped[str] = mapped_column(String(20), default="cold", nullable=False)
    budget_range: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    decision_timeline: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    authority_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    extracted_needs: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    assigned_employee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization", back_populates="leads")
    customer: Mapped["Customer"] = relationship("Customer", back_populates="leads")
    call: Mapped[Optional["Call"]] = relationship("Call", back_populates="lead")
    follow_up_tasks: Mapped[List["FollowUpTask"]] = relationship("FollowUpTask", back_populates="lead")
