"""Special date overrides and temporary schedules."""

import uuid
from datetime import date, time
from typing import Optional
from sqlalchemy import Boolean, Date, ForeignKey, String, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.models.base import GUID, Base, TenantMixin, TimestampMixin


class SpecialSchedule(Base, TenantMixin, TimestampMixin):
    """Overrides for irregular dates, split shifts, or temporary office closures."""

    __tablename__ = "special_schedules"
    __table_args__ = (
        UniqueConstraint("org_id", "department_id", "schedule_date", name="uq_special_schedules_org_dept_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    department_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("departments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    schedule_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    open_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    close_time: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    is_closed_all_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
