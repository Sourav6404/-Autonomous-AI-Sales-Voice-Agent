"""AI Receptionist Availability & Operating Resolution Router."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import require_admin, require_receptionist
from backend.app.core.database import get_db
from backend.app.core.tenant import TenantContext
from backend.app.models.ai_availability import AIAvailability
from backend.app.models.user import User
from backend.app.schemas.ai_availability import (
    AIAvailabilityStatusResponse,
    AIAvailabilityUpdateRequest,
    ScheduledStatusChangeRequest,
    TempOfflineRequest,
)
from backend.app.services.availability_service import AvailabilityService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai-availability", tags=["AI Availability"])


@router.get(
    "/status",
    response_model=AIAvailabilityStatusResponse,
    summary="Compute current real-time AI availability and operating status",
)
async def get_availability_status(
    department_id: Optional[UUID] = Query(None, description="Optional department context"),
    timestamp: Optional[datetime] = Query(None, description="Optional target evaluation timestamp (ISO)"),
    current_user: User = Depends(require_receptionist),
    db: AsyncSession = Depends(get_db),
) -> AIAvailabilityStatusResponse:
    """Execute precedence resolution engine across emergency, overrides, holidays, and business hours."""
    org_id = TenantContext.get_current_tenant_id()
    return await AvailabilityService.resolve_availability(
        db=db,
        org_id=org_id,
        timestamp=timestamp,
        department_id=department_id,
    )


@router.patch(
    "",
    response_model=AIAvailabilityStatusResponse,
    summary="Update AI availability status or toggle emergency closure",
)
async def update_ai_availability(
    payload: AIAvailabilityUpdateRequest,
    department_id: Optional[UUID] = Query(None, description="Target department UUID"),
    current_user: User = Depends(require_receptionist),
    db: AsyncSession = Depends(get_db),
) -> AIAvailabilityStatusResponse:
    """Manual status toggle (online/offline/maintenance/takeover) or emergency shutdown."""
    org_id = TenantContext.get_current_tenant_id()
    query = select(AIAvailability).where(
        AIAvailability.org_id == org_id,
        AIAvailability.department_id == department_id,
    )
    res = await db.execute(query)
    avail = res.scalar_one_or_none()

    if not avail:
        avail = AIAvailability(org_id=org_id, department_id=department_id)
        db.add(avail)

    if payload.status is not None:
        avail.status = payload.status
        avail.last_status_change_at = datetime.now(timezone.utc)
        avail.changed_by_user_id = current_user.id
        # Clearing temp offline if manually set back online
        if payload.status == "online":
            avail.temp_offline_until = None

    if payload.emergency_closure_active is not None:
        avail.emergency_closure_active = payload.emergency_closure_active
        avail.emergency_reason = payload.emergency_reason if payload.emergency_closure_active else None
        avail.last_status_change_at = datetime.now(timezone.utc)
        avail.changed_by_user_id = current_user.id

    if payload.auto_schedule_enabled is not None:
        avail.auto_schedule_enabled = payload.auto_schedule_enabled

    await db.commit()
    await db.refresh(avail)

    return await AvailabilityService.resolve_availability(
        db=db,
        org_id=org_id,
        department_id=department_id,
    )


@router.post(
    "/temp-offline",
    response_model=AIAvailabilityStatusResponse,
    summary="Set temporary offline window with duration",
)
async def set_temp_offline(
    payload: TempOfflineRequest,
    department_id: Optional[UUID] = Query(None, description="Target department UUID"),
    current_user: User = Depends(require_receptionist),
    db: AsyncSession = Depends(get_db),
) -> AIAvailabilityStatusResponse:
    """Take AI offline for a specific duration (e.g. lunch break, staff meeting)."""
    org_id = TenantContext.get_current_tenant_id()
    query = select(AIAvailability).where(
        AIAvailability.org_id == org_id,
        AIAvailability.department_id == department_id,
    )
    res = await db.execute(query)
    avail = res.scalar_one_or_none()

    if not avail:
        avail = AIAvailability(org_id=org_id, department_id=department_id)
        db.add(avail)

    offline_until = datetime.now(timezone.utc) + timedelta(minutes=payload.duration_minutes)
    avail.temp_offline_until = offline_until
    avail.last_status_change_at = datetime.now(timezone.utc)
    avail.changed_by_user_id = current_user.id

    await db.commit()
    await db.refresh(avail)

    return await AvailabilityService.resolve_availability(
        db=db,
        org_id=org_id,
        department_id=department_id,
    )


@router.post(
    "/scheduled-change",
    response_model=AIAvailabilityStatusResponse,
    summary="Schedule deferred status transition",
)
async def schedule_status_change(
    payload: ScheduledStatusChangeRequest,
    department_id: Optional[UUID] = Query(None, description="Target department UUID"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AIAvailabilityStatusResponse:
    """Schedule future status transition (e.g. maintenance window). Admin only."""
    org_id = TenantContext.get_current_tenant_id()
    query = select(AIAvailability).where(
        AIAvailability.org_id == org_id,
        AIAvailability.department_id == department_id,
    )
    res = await db.execute(query)
    avail = res.scalar_one_or_none()

    if not avail:
        avail = AIAvailability(org_id=org_id, department_id=department_id)
        db.add(avail)

    avail.scheduled_status = payload.scheduled_status
    avail.scheduled_status_change_at = payload.scheduled_status_change_at

    await db.commit()
    await db.refresh(avail)

    return await AvailabilityService.resolve_availability(
        db=db,
        org_id=org_id,
        department_id=department_id,
    )
