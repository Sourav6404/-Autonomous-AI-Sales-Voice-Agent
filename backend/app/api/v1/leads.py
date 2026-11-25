"""Stage 6 Lead management API."""

import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.api.deps import (
    get_current_active_user,
    require_admin,
    require_receptionist,
    require_employee,
)
from backend.app.core.database import get_db
from backend.app.core.exceptions import AppException
from backend.app.models.employee import Employee
from backend.app.models.lead import Lead
from backend.app.models.customer import Customer
from backend.app.models.user import User
from backend.app.schemas.crm import (
    LeadAssignRequest,
    LeadCreate,
    LeadListResponse,
    LeadResponse,
    LeadUpdate,
    CustomerResponse,
)

router = APIRouter(prefix="/leads", tags=["CRM - Leads"])


def _build_lead_response(lead: Lead) -> LeadResponse:
    data = LeadResponse.model_validate(lead)
    if lead.customer:
        data.customer = CustomerResponse.model_validate(lead.customer)
    return data


@router.get("", response_model=LeadListResponse)
async def list_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    tier: Optional[str] = Query(None),
    assigned_to: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_receptionist),
):
    """List all leads in tenant with optional filters (admin/receptionist view)."""
    stmt = select(Lead).options(selectinload(Lead.customer))
    if status:
        stmt = stmt.where(Lead.status == status)
    if tier:
        stmt = stmt.where(Lead.qualification_tier == tier)
    if assigned_to:
        # Find employee by user_id
        emp_result = await db.execute(
            select(Employee).where(Employee.user_id == assigned_to)
        )
        emp = emp_result.scalar_one_or_none()
        if emp:
            stmt = stmt.where(Lead.assigned_employee_id == emp.id)
    stmt = stmt.order_by(Lead.created_at.desc())

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    leads = result.scalars().all()

    return LeadListResponse(
        items=[_build_lead_response(l) for l in leads],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/my", response_model=LeadListResponse)
async def list_my_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Sales employee: list only their assigned leads."""
    # Find the employee record for this user
    emp_result = await db.execute(
        select(Employee).where(Employee.user_id == current_user.id)
    )
    emp = emp_result.scalar_one_or_none()
    if not emp:
        return LeadListResponse(items=[], total=0, page=page, page_size=page_size)

    stmt = select(Lead).options(selectinload(Lead.customer)).where(
        Lead.assigned_employee_id == emp.id
    )
    if status:
        stmt = stmt.where(Lead.status == status)
    stmt = stmt.order_by(Lead.created_at.desc())

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    leads = result.scalars().all()

    return LeadListResponse(
        items=[_build_lead_response(l) for l in leads],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=LeadResponse, status_code=201)
async def create_lead(
    payload: LeadCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_receptionist),
):
    """Manually create a lead."""
    # Verify customer exists in tenant
    cust_result = await db.execute(
        select(Customer).where(Customer.id == payload.customer_id)
    )
    if not cust_result.scalar_one_or_none():
        raise AppException(message="Customer not found.", code="CUSTOMER_NOT_FOUND", status_code=404)

    lead = Lead(org_id=current_user.org_id, **payload.model_dump())
    db.add(lead)
    await db.commit()
    await db.refresh(lead)

    # Reload with customer
    result = await db.execute(
        select(Lead).options(selectinload(Lead.customer)).where(Lead.id == lead.id)
    )
    lead = result.scalar_one()
    return _build_lead_response(lead)


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get a single lead. Sales employees can only view their own."""
    result = await db.execute(
        select(Lead).options(selectinload(Lead.customer)).where(Lead.id == lead_id)
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise AppException(message="Lead not found.", code="LEAD_NOT_FOUND", status_code=404)

    # Enforce sales employee scope
    if current_user.role in ("sales_employee", "employee"):
        emp_result = await db.execute(
            select(Employee).where(Employee.user_id == current_user.id)
        )
        emp = emp_result.scalar_one_or_none()
        if not emp or lead.assigned_employee_id != emp.id:
            raise AppException(
                message="Access denied: not assigned to this lead.",
                code="INSUFFICIENT_PERMISSIONS",
                status_code=403,
            )

    return _build_lead_response(lead)


@router.patch("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: uuid.UUID,
    payload: LeadUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update a lead. Sales employees can only update their assigned leads."""
    result = await db.execute(
        select(Lead).options(selectinload(Lead.customer)).where(Lead.id == lead_id)
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise AppException(message="Lead not found.", code="LEAD_NOT_FOUND", status_code=404)

    if current_user.role in ("sales_employee", "employee"):
        emp_result = await db.execute(
            select(Employee).where(Employee.user_id == current_user.id)
        )
        emp = emp_result.scalar_one_or_none()
        if not emp or lead.assigned_employee_id != emp.id:
            raise AppException(
                message="Access denied: not assigned to this lead.",
                code="INSUFFICIENT_PERMISSIONS",
                status_code=403,
            )

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(lead, field, value)
    await db.commit()
    await db.refresh(lead)

    result = await db.execute(
        select(Lead).options(selectinload(Lead.customer)).where(Lead.id == lead_id)
    )
    lead = result.scalar_one()
    return _build_lead_response(lead)


@router.post("/{lead_id}/assign", response_model=LeadResponse)
async def assign_lead(
    lead_id: uuid.UUID,
    payload: LeadAssignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Assign a lead to a sales employee (admin only)."""
    result = await db.execute(
        select(Lead).options(selectinload(Lead.customer)).where(Lead.id == lead_id)
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise AppException(message="Lead not found.", code="LEAD_NOT_FOUND", status_code=404)

    emp_result = await db.execute(
        select(Employee).where(Employee.id == payload.employee_id)
    )
    emp = emp_result.scalar_one_or_none()
    if not emp:
        raise AppException(message="Employee not found.", code="EMPLOYEE_NOT_FOUND", status_code=404)

    lead.assigned_employee_id = emp.id
    if lead.status == "new":
        lead.status = "contacted"
    await db.commit()

    result = await db.execute(
        select(Lead).options(selectinload(Lead.customer)).where(Lead.id == lead_id)
    )
    lead = result.scalar_one()
    return _build_lead_response(lead)
