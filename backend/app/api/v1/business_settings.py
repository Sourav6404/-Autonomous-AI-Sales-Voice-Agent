"""Business Settings & Telephony Configuration Router."""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import require_admin
from backend.app.core.database import get_db
from backend.app.core.tenant import TenantContext
from backend.app.models.business_settings import BusinessSettings
from backend.app.models.user import User
from backend.app.schemas.business_settings import (
    BusinessSettingsResponse,
    BusinessSettingsUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/business-settings", tags=["Business Settings"])


@router.get(
    "",
    response_model=BusinessSettingsResponse,
    summary="Get organization business settings and telephony configuration",
)
async def get_business_settings(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BusinessSettingsResponse:
    """Fetch business and receptionist settings for current tenant."""
    org_id = TenantContext.get_current_tenant_id()
    query = select(BusinessSettings).where(BusinessSettings.org_id == org_id)
    res = await db.execute(query)
    settings = res.scalar_one_or_none()

    if not settings:
        # Create default if missing
        settings = BusinessSettings(org_id=org_id)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)

    return BusinessSettingsResponse.model_validate(settings)


@router.patch(
    "",
    response_model=BusinessSettingsResponse,
    summary="Update organization business settings and telephony configuration",
)
async def update_business_settings(
    payload: BusinessSettingsUpdateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BusinessSettingsResponse:
    """Update business settings, contact profile, after-hours behavior, or recording consent."""
    org_id = TenantContext.get_current_tenant_id()
    query = select(BusinessSettings).where(BusinessSettings.org_id == org_id)
    res = await db.execute(query)
    settings = res.scalar_one_or_none()

    if not settings:
        settings = BusinessSettings(org_id=org_id)
        db.add(settings)

    update_data = payload.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        setattr(settings, field, val)

    await db.commit()
    await db.refresh(settings)
    return BusinessSettingsResponse.model_validate(settings)
