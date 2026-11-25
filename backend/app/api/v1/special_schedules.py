"""Special Schedules & Date Overrides Router."""

import logging
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import require_admin
from backend.app.core.database import get_db
from backend.app.core.tenant import TenantContext
from backend.app.models.special_schedule import SpecialSchedule
from backend.app.models.user import User
from backend.app.schemas.special_schedule import (
    SpecialScheduleCreateRequest,
    SpecialScheduleResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/special-schedules", tags=["Special Schedules"])


@router.get(
    "",
    response_model=List[SpecialScheduleResponse],
    summary="List special schedules and overrides",
)
async def list_special_schedules(
    department_id: Optional[UUID] = Query(None, description="Filter by department"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> List[SpecialScheduleResponse]:
    """Retrieve date overrides and irregular schedules."""
    org_id = TenantContext.get_current_tenant_id()
    query = select(SpecialSchedule).where(
        SpecialSchedule.org_id == org_id,
        SpecialSchedule.department_id == department_id,
    ).order_by(SpecialSchedule.schedule_date)

    res = await db.execute(query)
    schedules = res.scalars().all()
    return [SpecialScheduleResponse.model_validate(s) for s in schedules]


@router.post(
    "",
    response_model=SpecialScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or update special schedule override",
)
async def create_special_schedule(
    payload: SpecialScheduleCreateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SpecialScheduleResponse:
    """Create or update date override."""
    org_id = TenantContext.get_current_tenant_id()

    # Check if entry already exists for org_id, department_id, schedule_date
    query = select(SpecialSchedule).where(
        SpecialSchedule.org_id == org_id,
        SpecialSchedule.department_id == payload.department_id,
        SpecialSchedule.schedule_date == payload.schedule_date,
    )
    res = await db.execute(query)
    schedule = res.scalar_one_or_none()

    if schedule:
        schedule.open_time = payload.open_time
        schedule.close_time = payload.close_time
        schedule.is_closed_all_day = payload.is_closed_all_day
        schedule.reason = payload.reason
    else:
        schedule = SpecialSchedule(
            org_id=org_id,
            department_id=payload.department_id,
            schedule_date=payload.schedule_date,
            open_time=payload.open_time,
            close_time=payload.close_time,
            is_closed_all_day=payload.is_closed_all_day,
            reason=payload.reason,
        )
        db.add(schedule)

    await db.commit()
    await db.refresh(schedule)
    return SpecialScheduleResponse.model_validate(schedule)


@router.delete(
    "/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a special schedule override",
)
async def delete_special_schedule(
    schedule_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a special schedule override."""
    org_id = TenantContext.get_current_tenant_id()
    query = select(SpecialSchedule).where(
        SpecialSchedule.id == schedule_id,
        SpecialSchedule.org_id == org_id,
    )
    res = await db.execute(query)
    schedule = res.scalar_one_or_none()

    if not schedule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Special schedule not found")

    await db.delete(schedule)
    await db.commit()
