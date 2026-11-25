"""Holiday and Corporate Closure Schedule Router."""

import logging
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import require_admin
from backend.app.core.database import get_db
from backend.app.core.tenant import TenantContext
from backend.app.models.holiday import Holiday
from backend.app.models.user import User
from backend.app.schemas.holiday import (
    HolidayCreateRequest,
    HolidayResponse,
    HolidayUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/holidays", tags=["Holidays"])


@router.get(
    "",
    response_model=List[HolidayResponse],
    summary="List all holidays for current organization",
)
async def list_holidays(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> List[HolidayResponse]:
    """Retrieve all corporate holidays and scheduled closures."""
    org_id = TenantContext.get_current_tenant_id()
    query = select(Holiday).where(Holiday.org_id == org_id).order_by(Holiday.start_date)
    res = await db.execute(query)
    holidays = res.scalars().all()
    return [HolidayResponse.model_validate(h) for h in holidays]


@router.post(
    "",
    response_model=HolidayResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new holiday",
)
async def create_holiday(
    payload: HolidayCreateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> HolidayResponse:
    """Register a new holiday or planned closure."""
    org_id = TenantContext.get_current_tenant_id()
    holiday = Holiday(
        org_id=org_id,
        name=payload.name.strip(),
        start_date=payload.start_date,
        end_date=payload.end_date,
        is_recurring_yearly=payload.is_recurring_yearly,
        special_announcement=payload.special_announcement,
    )
    db.add(holiday)
    await db.commit()
    await db.refresh(holiday)
    return HolidayResponse.model_validate(holiday)


@router.patch(
    "/{holiday_id}",
    response_model=HolidayResponse,
    summary="Update an existing holiday",
)
async def update_holiday(
    holiday_id: UUID,
    payload: HolidayUpdateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> HolidayResponse:
    """Modify a holiday record."""
    org_id = TenantContext.get_current_tenant_id()
    query = select(Holiday).where(Holiday.id == holiday_id, Holiday.org_id == org_id)
    res = await db.execute(query)
    holiday = res.scalar_one_or_none()

    if not holiday:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holiday not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        setattr(holiday, field, val)

    await db.commit()
    await db.refresh(holiday)
    return HolidayResponse.model_validate(holiday)


@router.delete(
    "/{holiday_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a holiday",
)
async def delete_holiday(
    holiday_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a holiday schedule."""
    org_id = TenantContext.get_current_tenant_id()
    query = select(Holiday).where(Holiday.id == holiday_id, Holiday.org_id == org_id)
    res = await db.execute(query)
    holiday = res.scalar_one_or_none()

    if not holiday:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holiday not found")

    await db.delete(holiday)
    await db.commit()
