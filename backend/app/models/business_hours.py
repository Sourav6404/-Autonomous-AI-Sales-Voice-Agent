"""Operating hours per weekday and department."""

import uuid
from datetime import time
from typing import TYPE_CHECKING, Optional
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, SmallInteger, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import GUID, Base, TenantMixin, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.organization import Organization
    from backend.app.models.department import Department


class BusinessHours(Base, TenantMixin, TimestampMixin):
    """Weekly operating schedule."""

    __tablename__ = "business_hours"
    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_business_hours_day_of_week"),
        CheckConstraint("open_time < close_time", name="ck_business_hours_time_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    department_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("departments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0=Sunday, 6=Saturday
    open_time: Mapped[time] = mapped_column(Time, nullable=False)
    close_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization", back_populates="business_hours")
    department: Mapped[Optional["Department"]] = relationship("Department", back_populates="business_hours")
