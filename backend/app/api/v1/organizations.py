"""Organization Management Router."""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_current_org, require_admin
from backend.app.core.database import get_db
from backend.app.models.organization import Organization
from backend.app.models.user import User
from backend.app.schemas.organization import OrganizationResponse, OrganizationUpdateRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/organizations", tags=["Organizations"])


@router.get(
    "/me",
    response_model=OrganizationResponse,
    summary="Get current tenant organization details",
)
async def get_my_organization(
    current_org: Organization = Depends(get_current_org),
) -> OrganizationResponse:
    """Return organization details for currently authenticated tenant."""
    return OrganizationResponse.model_validate(current_org)


@router.patch(
    "/me",
    response_model=OrganizationResponse,
    summary="Update current tenant organization details",
)
async def update_my_organization(
    payload: OrganizationUpdateRequest,
    current_org: Organization = Depends(get_current_org),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> OrganizationResponse:
    """Update organization name or timezone. Restricted to Admin and Owner roles."""
    if payload.name is not None:
        current_org.name = payload.name.strip()
    if payload.default_timezone is not None:
        current_org.default_timezone = payload.default_timezone.strip()

    await db.commit()
    await db.refresh(current_org)
    return OrganizationResponse.model_validate(current_org)
