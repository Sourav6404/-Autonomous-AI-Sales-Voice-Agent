"""Centralized AI Availability & Operating Schedule Resolution Service.

Evaluates multi-tiered precedence rules:
1. Emergency closure active
2. Manual status override (offline / maintenance / takeover_only)
3. Temporary offline window
4. Special date schedule overrides
5. Holidays and corporate closures
6. Weekly recurring business hours
7. Default closed state
"""

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Tuple
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.ai_availability import AIAvailability
from backend.app.models.business_hours import BusinessHours
from backend.app.models.business_settings import BusinessSettings
from backend.app.models.holiday import Holiday
from backend.app.models.organization import Organization
from backend.app.models.special_schedule import SpecialSchedule
from backend.app.schemas.ai_availability import AIAvailabilityStatusResponse

logger = logging.getLogger(__name__)


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensures datetime object is timezone-aware UTC, even on SQLite."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class AvailabilityService:
    """Evaluates business operating status and AI receptionist availability."""

    @staticmethod
    def get_tz(tz_name: Optional[str]) -> ZoneInfo:
        """Safely load timezone or fallback to UTC."""
        if not tz_name:
            return ZoneInfo("UTC")
        try:
            return ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError, Exception):
            logger.warning("Unrecognized timezone '%s', defaulting to UTC", tz_name)
            return ZoneInfo("UTC")

    @classmethod
    async def resolve_availability(
        cls,
        db: AsyncSession,
        org_id: UUID,
        timestamp: Optional[datetime] = None,
        department_id: Optional[UUID] = None,
    ) -> AIAvailabilityStatusResponse:
        """Evaluate complete availability status using strictly ordered precedence."""
        # 1. Fetch organization timezone
        org_result = await db.execute(
            select(Organization).where(Organization.id == org_id)
        )
        org = org_result.scalar_one_or_none()
        tz_name = org.default_timezone if org else "UTC"
        tz = cls.get_tz(tz_name)

        # Reference time in local organization timezone
        if timestamp is None:
            now_utc = datetime.now(timezone.utc)
            now_local = now_utc.astimezone(tz)
        else:
            if timestamp.tzinfo is None:
                now_local = timestamp.replace(tzinfo=tz)
            else:
                now_local = timestamp.astimezone(tz)
            now_utc = now_local.astimezone(timezone.utc)

        current_date = now_local.date()
        current_time = now_local.time()
        # Python weekday: 0=Monday..6=Sunday. In our schema: 0=Sunday..6=Saturday
        # Conversion: python_weekday (0=Mon..6=Sun) -> schema_weekday = (python_weekday + 1) % 7
        schema_day_of_week = (now_local.weekday() + 1) % 7

        # 2. Fetch AI Availability configuration
        ai_avail_query = select(AIAvailability).where(
            AIAvailability.org_id == org_id,
            AIAvailability.department_id == department_id,
        )
        ai_avail_result = await db.execute(ai_avail_query)
        ai_avail = ai_avail_result.scalar_one_or_none()

        # If not found for specific department, try org-level fallback
        if not ai_avail and department_id is not None:
            ai_avail_result = await db.execute(
                select(AIAvailability).where(
                    AIAvailability.org_id == org_id,
                    AIAvailability.department_id == None,  # noqa: E711
                )
            )
            ai_avail = ai_avail_result.scalar_one_or_none()

        # 3. Fetch Business Settings
        settings_result = await db.execute(
            select(BusinessSettings).where(BusinessSettings.org_id == org_id)
        )
        settings = settings_result.scalar_one_or_none()
        after_hours_behavior = settings.after_hours_behavior if settings else "ai_voicemail"

        # Check deferred scheduled status transition
        sched_change_utc = _ensure_utc(ai_avail.scheduled_status_change_at) if ai_avail else None
        if (
            ai_avail
            and ai_avail.scheduled_status
            and sched_change_utc
            and now_utc >= sched_change_utc
        ):
            ai_avail.status = ai_avail.scheduled_status
            ai_avail.scheduled_status = None
            ai_avail.scheduled_status_change_at = None
            ai_avail.last_status_change_at = now_utc
            await db.flush()

        # Tier 1: Emergency Closure
        if ai_avail and ai_avail.emergency_closure_active:
            return AIAvailabilityStatusResponse(
                org_id=org_id,
                department_id=department_id,
                business_status="closed",
                ai_status="offline",
                reason=ai_avail.emergency_reason or "Emergency closure in effect",
                current_time=now_local,
                timezone=tz_name,
                emergency_closure_active=True,
                emergency_reason=ai_avail.emergency_reason,
                temp_offline_until=ai_avail.temp_offline_until,
                next_status_change_at=None,
            )

        # Tier 2: Temporary Offline Mode
        temp_offline_utc = _ensure_utc(ai_avail.temp_offline_until) if ai_avail else None
        if (
            ai_avail
            and temp_offline_utc
            and now_utc < temp_offline_utc
        ):
            temp_offline_local = temp_offline_utc.astimezone(tz)
            return AIAvailabilityStatusResponse(
                org_id=org_id,
                department_id=department_id,
                business_status="closed",
                ai_status="offline",
                reason=f"Temporary offline until {temp_offline_local.strftime('%H:%M %Z')}",
                current_time=now_local,
                timezone=tz_name,
                emergency_closure_active=False,
                emergency_reason=None,
                temp_offline_until=ai_avail.temp_offline_until,
                next_status_change_at=ai_avail.temp_offline_until,
            )

        # Tier 3: Manual Status Override (if auto-schedule disabled or non-online)
        manual_override = False
        manual_ai_status = "online"
        if ai_avail:
            if not ai_avail.auto_schedule_enabled:
                manual_override = True
                manual_ai_status = ai_avail.status
            elif ai_avail.status in ("maintenance", "takeover_only", "offline"):
                manual_override = True
                manual_ai_status = ai_avail.status

        # Evaluate operating schedule (Special Schedules > Holidays > Regular Business Hours)
        is_business_open = False
        status_reason = "Closed outside operating hours"
        next_change: Optional[datetime] = None

        # Check Special Schedules for today
        special_query = select(SpecialSchedule).where(
            SpecialSchedule.org_id == org_id,
            SpecialSchedule.schedule_date == current_date,
            SpecialSchedule.department_id == department_id,
        )
        special_result = await db.execute(special_query)
        special = special_result.scalar_one_or_none()

        if special:
            if special.is_closed_all_day:
                is_business_open = False
                status_reason = special.reason or "Special schedule: Closed today"
            else:
                if special.open_time and special.close_time:
                    if special.open_time <= current_time <= special.close_time:
                        is_business_open = True
                        status_reason = special.reason or "Open under special schedule"
                        next_change = datetime.combine(current_date, special.close_time, tzinfo=tz)
                    elif current_time < special.open_time:
                        is_business_open = False
                        status_reason = special.reason or "Special schedule: Closed before opening"
                        next_change = datetime.combine(current_date, special.open_time, tzinfo=tz)
                    else:
                        is_business_open = False
                        status_reason = special.reason or "Special schedule: Closed after hours"
        else:
            # Check Holidays
            holidays_query = select(Holiday).where(Holiday.org_id == org_id)
            holidays_result = await db.execute(holidays_query)
            holidays = holidays_result.scalars().all()

            holiday_matched: Optional[Holiday] = None
            for h in holidays:
                if h.is_recurring_yearly:
                    # Match month and day
                    h_start = h.start_date.replace(year=current_date.year)
                    h_end = h.end_date.replace(year=current_date.year)
                    if h_start <= current_date <= h_end:
                        holiday_matched = h
                        break
                else:
                    if h.start_date <= current_date <= h.end_date:
                        holiday_matched = h
                        break

            if holiday_matched:
                is_business_open = False
                status_reason = holiday_matched.special_announcement or f"Holiday closure: {holiday_matched.name}"
            else:
                # Check Regular Business Hours
                bh_query = select(BusinessHours).where(
                    BusinessHours.org_id == org_id,
                    BusinessHours.day_of_week == schema_day_of_week,
                    BusinessHours.department_id == department_id,
                )
                bh_result = await db.execute(bh_query)
                bh_entries = bh_result.scalars().all()

                if not bh_entries and department_id is not None:
                    # Fallback to org level business hours
                    bh_query_fallback = select(BusinessHours).where(
                        BusinessHours.org_id == org_id,
                        BusinessHours.day_of_week == schema_day_of_week,
                        BusinessHours.department_id == None,  # noqa: E711
                    )
                    bh_result = await db.execute(bh_query_fallback)
                    bh_entries = bh_result.scalars().all()

                if not bh_entries or all(b.is_closed for b in bh_entries):
                    is_business_open = False
                    status_reason = "Regularly scheduled closed day"
                else:
                    # Check shifts
                    found_open_shift = False
                    earliest_upcoming_open: Optional[time] = None

                    for shift in bh_entries:
                        if shift.is_closed:
                            continue
                        if shift.open_time <= current_time <= shift.close_time:
                            found_open_shift = True
                            status_reason = "Regular business hours"
                            next_change = datetime.combine(current_date, shift.close_time, tzinfo=tz)
                            break
                        elif current_time < shift.open_time:
                            if earliest_upcoming_open is None or shift.open_time < earliest_upcoming_open:
                                earliest_upcoming_open = shift.open_time

                    if found_open_shift:
                        is_business_open = True
                    else:
                        is_business_open = False
                        if earliest_upcoming_open:
                            status_reason = "Closed before operating hours"
                            next_change = datetime.combine(current_date, earliest_upcoming_open, tzinfo=tz)
                        else:
                            status_reason = "Closed after operating hours"

        # Determine AI receptionist status
        business_status_str = "open" if is_business_open else "closed"

        if manual_override:
            computed_ai_status = manual_ai_status
            if computed_ai_status != "online":
                status_reason = f"Manual override: {computed_ai_status}"
        else:
            if is_business_open:
                computed_ai_status = "online"
            else:
                # Business is closed. Does AI answer after-hours?
                if after_hours_behavior == "reject":
                    computed_ai_status = "offline"
                else:
                    # ai_voicemail, ai_general_info_only, forward_to_number -> AI stays online!
                    computed_ai_status = "online"

        return AIAvailabilityStatusResponse(
            org_id=org_id,
            department_id=department_id,
            business_status=business_status_str,
            ai_status=computed_ai_status,
            reason=status_reason,
            current_time=now_local,
            timezone=tz_name,
            emergency_closure_active=False,
            emergency_reason=None,
            temp_offline_until=ai_avail.temp_offline_until if ai_avail else None,
            next_status_change_at=next_change,
        )
