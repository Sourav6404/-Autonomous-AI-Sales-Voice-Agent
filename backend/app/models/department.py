"""Department model for organizational routing and hours isolation."""

import uuid
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import GUID, Base, TenantMixin, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.organization import Organization
    from backend.app.models.employee import Employee
    from backend.app.models.business_hours import BusinessHours
    from backend.app.models.call import Call


class Department(Base, TenantMixin, TimestampMixin):
    """Department unit within an organization."""

    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_departments_org_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fallback_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization", back_populates="departments")
    employees: Mapped[List["Employee"]] = relationship(
        "Employee", back_populates="department"
    )
    business_hours: Mapped[List["BusinessHours"]] = relationship(
        "BusinessHours", back_populates="department"
    )
    calls: Mapped[List["Call"]] = relationship(
        "Call", back_populates="department"
    )
