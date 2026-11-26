"""Appointment Availability Engine.

Calculates available appointment booking slots considering:
- Business operating hours (0=Sun..6=Sat)
- Holidays & corporate closures
- Special date schedules
- Emergency closures
- Employee booking availability & assignment
- Existing appointments & overlap collision prevention
"""

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.models.appointment import Appointment
from backend.app.models.business_hours import BusinessHours
from backend.app.models.business_settings import BusinessSettings
from backend.app.models.employee import Employee
from backend.app.models.holiday import Holiday
from backend.app.models.organization import Organization
from backend.app.models.special_schedule import SpecialSchedule
from backend.app.models.user import User
from backend.app.schemas.appointment import (
    AppointmentAvailabilityResponse,
    AppointmentSlot,
)
from backend.app.services.availability_service import AvailabilityService, _ensure_utc

logger = logging.getLogger(__name__)


class AppointmentAvailabilityService:
    """Calculates and checks valid, collision-free appointment time slots."""

    @classmethod
    async def get_available_slots(
        cls,
        db: AsyncSession,
        org_id: UUID,
        target_date: date,
        employee_id: Optional[UUID] = None,
        duration_minutes: int = 30,
    ) -> AppointmentAvailabilityResponse:
        """Computes all open, conflict-free appointment slots for the given date."""
        # 1. Fetch organization and timezone
        org_res = await db.execute(select(Organization).where(Organization.id == org_id))
        org = org_res.scalar_one_or_none()
        tz_name = org.default_timezone if org else "UTC"
        tz = AvailabilityService.get_tz(tz_name)

        # 2. Check emergency closure
        settings_res = await db.execute(
            select(BusinessSettings).where(BusinessSettings.org_id == org_id)
        )
        settings = settings_res.scalar_one_or_none()
        if settings and getattr(settings, "is_emergency_closure", False):
            return AppointmentAvailabilityResponse(
                date=target_date,
                timezone=tz_name,
                business_open=False,
                reason=getattr(settings, "emergency_closure_reason", None) or "Emergency closure in effect",
                slots=[],
            )

        # 3. Check Holidays
        holiday_res = await db.execute(
            select(Holiday).where(
                Holiday.org_id == org_id,
                Holiday.start_date <= target_date,
                Holiday.end_date >= target_date,
            )
        )
        holiday = holiday_res.scalar_one_or_none()
        if holiday:
            return AppointmentAvailabilityResponse(
                date=target_date,
                timezone=tz_name,
                business_open=False,
                reason=f"Closed for holiday: {holiday.name}",
                slots=[],
            )

        # 4. Check Special Schedules vs Business Hours
        special_res = await db.execute(
            select(SpecialSchedule).where(
                SpecialSchedule.org_id == org_id,
                SpecialSchedule.schedule_date == target_date,
            )
        )
        special = special_res.scalar_one_or_none()

        open_t: Optional[time] = None
        close_t: Optional[time] = None

        if special:
            if special.is_closed_all_day:
                return AppointmentAvailabilityResponse(
                    date=target_date,
                    timezone=tz_name,
                    business_open=False,
                    reason=special.reason or "Closed by special schedule",
                    slots=[],
                )
            open_t = special.open_time
            close_t = special.close_time
        else:
            # Day of week: in BusinessHours model 0=Sunday..6=Saturday
            py_weekday = target_date.weekday()  # Mon=0..Sun=6
            dow = (py_weekday + 1) % 7  # Sun=0, Mon=1..Sat=6

            bh_res = await db.execute(
                select(BusinessHours).where(
                    BusinessHours.org_id == org_id,
                    BusinessHours.day_of_week == dow,
                )
            )
            bh = bh_res.scalar_one_or_none()
            if not bh or bh.is_closed:
                return AppointmentAvailabilityResponse(
                    date=target_date,
                    timezone=tz_name,
                    business_open=False,
                    reason="Closed on this day of week",
                    slots=[],
                )
            open_t = bh.open_time
            close_t = bh.close_time

        if not open_t or not close_t or open_t >= close_t:
            return AppointmentAvailabilityResponse(
                date=target_date,
                timezone=tz_name,
                business_open=False,
                reason="No operating hours configured",
                slots=[],
            )

        # 5. Fetch eligible staff
        emp_stmt = (
            select(Employee)
            .options(selectinload(Employee.user))
            .where(
                Employee.org_id == org_id,
                Employee.is_available_for_booking == True,
            )
        )
        if employee_id:
            emp_stmt = emp_stmt.where(Employee.id == employee_id)

        emp_res = await db.execute(emp_stmt)
        employees = emp_res.scalars().all()

        if not employees:
            return AppointmentAvailabilityResponse(
                date=target_date,
                timezone=tz_name,
                business_open=True,
                reason="No booking-available staff members found",
                slots=[],
            )

        # 6. Fetch existing appointments for date window to avoid double-booking
        day_start_local = datetime.combine(target_date, open_t, tzinfo=tz)
        day_end_local = datetime.combine(target_date, close_t, tzinfo=tz)
        day_start_utc = day_start_local.astimezone(timezone.utc)
        day_end_utc = day_end_local.astimezone(timezone.utc)

        appts_res = await db.execute(
            select(Appointment).where(
                Appointment.org_id == org_id,
                Appointment.status.notin_(["cancelled", "no_show"]),
                Appointment.start_time < day_end_utc,
                Appointment.end_time > day_start_utc,
            )
        )
        existing_appts = appts_res.scalars().all()

        # 7. Generate candidate slots
        slots: List[AppointmentSlot] = []
        curr_local = day_start_local
        delta = timedelta(minutes=duration_minutes)

        while curr_local + delta <= day_end_local:
            slot_end_local = curr_local + delta
            slot_start_utc = curr_local.astimezone(timezone.utc)
            slot_end_utc = slot_end_local.astimezone(timezone.utc)

            # Check each eligible employee
            for emp in employees:
                # Collision check
                has_conflict = any(
                    a.employee_id == emp.id
                    and _ensure_utc(a.start_time) < slot_end_utc
                    and _ensure_utc(a.end_time) > slot_start_utc
                    for a in existing_appts
                )

                if not has_conflict:
                    emp_name = emp.user.full_name if emp.user else "Sales Representative"
                    slots.append(
                        AppointmentSlot(
                            start_time=slot_start_utc,
                            end_time=slot_end_utc,
                            duration_minutes=duration_minutes,
                            employee_id=emp.id,
                            employee_name=emp_name,
                            available=True,
                        )
                    )

            curr_local += delta

        return AppointmentAvailabilityResponse(
            date=target_date,
            timezone=tz_name,
            business_open=True,
            slots=slots,
        )
