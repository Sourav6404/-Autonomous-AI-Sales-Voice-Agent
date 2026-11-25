"""Organization model representing the tenant boundary."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import GUID, Base, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.user import User
    from backend.app.models.department import Department
    from backend.app.models.business_settings import BusinessSettings
    from backend.app.models.business_hours import BusinessHours
    from backend.app.models.holiday import Holiday
    from backend.app.models.customer import Customer
    from backend.app.models.call import Call
    from backend.app.models.lead import Lead


class Organization(Base, TimestampMixin):
    """Tenant organization entity."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    default_timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    users: Mapped[List["User"]] = relationship(
        "User", back_populates="organization", cascade="all, delete-orphan"
    )
    departments: Mapped[List["Department"]] = relationship(
        "Department", back_populates="organization", cascade="all, delete-orphan"
    )
    business_settings: Mapped[Optional["BusinessSettings"]] = relationship(
        "BusinessSettings", back_populates="organization", uselist=False, cascade="all, delete-orphan"
    )
    business_hours: Mapped[List["BusinessHours"]] = relationship(
        "BusinessHours", back_populates="organization", cascade="all, delete-orphan"
    )
    holidays: Mapped[List["Holiday"]] = relationship(
        "Holiday", back_populates="organization", cascade="all, delete-orphan"
    )
    customers: Mapped[List["Customer"]] = relationship(
        "Customer", back_populates="organization", cascade="all, delete-orphan"
    )
    calls: Mapped[List["Call"]] = relationship(
        "Call", back_populates="organization", cascade="all, delete-orphan"
    )
    leads: Mapped[List["Lead"]] = relationship(
        "Lead", back_populates="organization", cascade="all, delete-orphan"
    )
