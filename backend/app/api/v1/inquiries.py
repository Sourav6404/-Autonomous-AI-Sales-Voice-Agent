"""Stage 6 Inquiry management API."""

import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.api.deps import (
    get_current_active_user,
    require_admin,
    require_receptionist,
)
from backend.app.core.database import get_db
from backend.app.core.exceptions import AppException
from backend.app.models.employee import Employee
from backend.app.models.inquiry import Inquiry
from backend.app.models.user import User
from backend.app.schemas.crm import (
    InquiryCreate,
    InquiryListResponse,
    InquiryResponse,
    InquiryUpdate,
    CustomerResponse,
)

router = APIRouter(prefix="/inquiries", tags=["CRM - Inquiries"])


def _build_inquiry_response(inq: Inquiry) -> InquiryResponse:
    data = InquiryResponse.model_validate(inq)
    if inq.customer:
        data.customer = CustomerResponse.model_validate(inq.customer)
    return data


@router.get("", response_model=InquiryListResponse)
async def list_inquiries(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_receptionist),
):
    """List tenant inquiries."""
    stmt = select(Inquiry).options(selectinload(Inquiry.customer))
    if status:
        stmt = stmt.where(Inquiry.status == status)
    if priority:
        stmt = stmt.where(Inquiry.priority == priority)
    stmt = stmt.order_by(Inquiry.created_at.desc())

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    inquiries = result.scalars().all()

    return InquiryListResponse(
        items=[_build_inquiry_response(i) for i in inquiries],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=InquiryResponse, status_code=201)
async def create_inquiry(
    payload: InquiryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_receptionist),
):
    """Create a new inquiry."""
    inq = Inquiry(org_id=current_user.org_id, **payload.model_dump())
    db.add(inq)
    await db.commit()
    await db.refresh(inq)

    result = await db.execute(
        select(Inquiry).options(selectinload(Inquiry.customer)).where(Inquiry.id == inq.id)
    )
    inq = result.scalar_one()
    return _build_inquiry_response(inq)


@router.get("/{inquiry_id}", response_model=InquiryResponse)
async def get_inquiry(
    inquiry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_receptionist),
):
    """Get a single inquiry."""
    result = await db.execute(
        select(Inquiry).options(selectinload(Inquiry.customer)).where(Inquiry.id == inquiry_id)
    )
    inq = result.scalar_one_or_none()
    if not inq:
        raise AppException(message="Inquiry not found.", code="INQUIRY_NOT_FOUND", status_code=404)
    return _build_inquiry_response(inq)


@router.patch("/{inquiry_id}", response_model=InquiryResponse)
async def update_inquiry(
    inquiry_id: uuid.UUID,
    payload: InquiryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_receptionist),
):
    """Update an inquiry (status, resolution, assignment)."""
    result = await db.execute(
        select(Inquiry).options(selectinload(Inquiry.customer)).where(Inquiry.id == inquiry_id)
    )
    inq = result.scalar_one_or_none()
    if not inq:
        raise AppException(message="Inquiry not found.", code="INQUIRY_NOT_FOUND", status_code=404)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(inq, field, value)

    if payload.status in ("resolved", "closed") and not inq.resolved_at:
        inq.resolved_at = datetime.now(timezone.utc)

    await db.commit()

    result = await db.execute(
        select(Inquiry).options(selectinload(Inquiry.customer)).where(Inquiry.id == inquiry_id)
    )
    inq = result.scalar_one()
    return _build_inquiry_response(inq)
