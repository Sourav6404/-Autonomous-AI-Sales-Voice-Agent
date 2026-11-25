"""Customer entity representing external callers and contacts."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import GUID, Base, TenantMixin, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.organization import Organization
    from backend.app.models.call import Call
    from backend.app.models.lead import Lead
    from backend.app.models.appointment import Appointment


class Customer(Base, TenantMixin, TimestampMixin):
    """Customer or caller contact record."""

    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("org_id", "phone_number", name="uq_customers_org_phone"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    phone_number: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    company_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    total_calls_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_called_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(100), default="inbound_call", nullable=True)
    tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization", back_populates="customers")
    calls: Mapped[List["Call"]] = relationship("Call", back_populates="customer")
    leads: Mapped[List["Lead"]] = relationship("Lead", back_populates="customer")
    appointments: Mapped[List["Appointment"]] = relationship("Appointment", back_populates="customer")
