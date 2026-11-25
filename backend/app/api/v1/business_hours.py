"""Weekly Operating Hours Router."""

import logging
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import require_admin
from backend.app.core.database import get_db
from backend.app.core.tenant import TenantContext
from backend.app.models.business_hours import BusinessHours
from backend.app.models.user import User
from backend.app.schemas.business_hours import (
    BusinessHoursBulkUpdateRequest,
    BusinessHoursResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/business-hours", tags=["Business Hours"])


@router.get(
    "",
    response_model=List[BusinessHoursResponse],
    summary="Get weekly operating hours",
)
async def get_business_hours(
    department_id: Optional[UUID] = Query(None, description="Filter by department"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> List[BusinessHoursResponse]:
    """Retrieve recurring weekly business hours."""
    org_id = TenantContext.get_current_tenant_id()
    query = select(BusinessHours).where(
        BusinessHours.org_id == org_id,
        BusinessHours.department_id == department_id,
    ).order_by(BusinessHours.day_of_week, BusinessHours.open_time)

    res = await db.execute(query)
    hours = res.scalars().all()
    return [BusinessHoursResponse.model_validate(h) for h in hours]


@router.put(
    "",
    response_model=List[BusinessHoursResponse],
    summary="Bulk update or replace weekly operating hours",
)
async def update_business_hours(
    payload: BusinessHoursBulkUpdateRequest,
    department_id: Optional[UUID] = Query(None, description="Target department UUID"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> List[BusinessHoursResponse]:
    """Atomic replacement of weekly schedule for organization or department."""
    org_id = TenantContext.get_current_tenant_id()

    # Delete existing business hours for this org and department scope
    delete_stmt = delete(BusinessHours).where(
        BusinessHours.org_id == org_id,
        BusinessHours.department_id == department_id,
    )
    await db.execute(delete_stmt)

    new_records = []
    for item in payload.schedules:
        record = BusinessHours(
            org_id=org_id,
            department_id=department_id,
            day_of_week=item.day_of_week,
            open_time=item.open_time,
            close_time=item.close_time,
            is_closed=item.is_closed,
        )
        db.add(record)
        new_records.append(record)

    await db.commit()
    for rec in new_records:
        await db.refresh(rec)

    return [BusinessHoursResponse.model_validate(r) for r in new_records]
