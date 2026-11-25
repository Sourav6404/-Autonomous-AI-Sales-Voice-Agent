"""Employee profile entity linked to user and department."""

import uuid
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import GUID, Base, TenantMixin, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.user import User
    from backend.app.models.department import Department
    from backend.app.models.appointment import Appointment
    from backend.app.models.follow_up_task import FollowUpTask


class Employee(Base, TenantMixin, TimestampMixin):
    """Staff employee profile."""

    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    department_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    calendar_sync_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    appointment_slot_duration_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    is_available_for_takeover: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_available_for_booking: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="employee")
    department: Mapped[Optional["Department"]] = relationship("Department", back_populates="employees")
    appointments: Mapped[List["Appointment"]] = relationship("Appointment", back_populates="employee")
    follow_up_tasks: Mapped[List["FollowUpTask"]] = relationship("FollowUpTask", back_populates="assigned_employee")
