"""Stage 6 Employee management API (admin only)."""

import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.api.deps import require_admin, require_employee, get_current_active_user
from backend.app.core.database import get_db
from backend.app.core.exceptions import AppException
from backend.app.core.security import PasswordHasher
from backend.app.models.department import Department
from backend.app.models.employee import Employee
from backend.app.models.organization import Organization
from backend.app.models.user import User
from backend.app.schemas.crm import (
    EmployeeListResponse,
    EmployeeResponse,
    EmployeeUserCreate,
    EmployeeUserUpdate,
)

router = APIRouter(prefix="/employees", tags=["CRM - Employees"])

ALLOWED_ROLES = {"admin", "receptionist", "employee", "sales_employee"}


def _build_employee_response(emp: Employee) -> EmployeeResponse:
    return EmployeeResponse(
        id=emp.id,
        user_id=emp.user_id,
        org_id=emp.org_id,
        title=emp.title,
        department_id=emp.department_id,
        is_available_for_takeover=emp.is_available_for_takeover,
        is_available_for_booking=emp.is_available_for_booking,
        created_at=emp.created_at,
        email=emp.user.email,
        full_name=emp.user.full_name,
        role=emp.user.role,
        phone_number=emp.user.phone_number,
        is_active=emp.user.is_active,
    )


@router.get("", response_model=EmployeeListResponse)
async def list_employees(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    role: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """List all employees/staff in the tenant."""
    stmt = (
        select(Employee)
        .options(selectinload(Employee.user))
        .join(User, User.id == Employee.user_id)
    )
    if role:
        stmt = stmt.where(User.role == role)
    stmt = stmt.order_by(Employee.created_at.desc())

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    employees = result.scalars().all()

    return EmployeeListResponse(
        items=[_build_employee_response(e) for e in employees],
        total=total,
    )


@router.post("", response_model=EmployeeResponse, status_code=201)
async def create_employee(
    payload: EmployeeUserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Create a new staff user and employee profile."""
    if payload.role not in ALLOWED_ROLES:
        raise AppException(
            message=f"Role must be one of: {ALLOWED_ROLES}",
            code="INVALID_ROLE",
            status_code=400,
        )

    # Check email uniqueness in org
    existing = await db.execute(
        select(User).where(User.email == payload.email, User.org_id == current_user.org_id)
    )
    if existing.scalar_one_or_none():
        raise AppException(
            message="Email already registered in this organization.",
            code="EMAIL_TAKEN",
            status_code=409,
        )

    user = User(
        org_id=current_user.org_id,
        email=payload.email,
        full_name=payload.full_name,
        password_hash=PasswordHasher.hash(payload.password),
        role=payload.role,
        phone_number=payload.phone_number,
        is_active=True,
    )
    db.add(user)
    await db.flush()  # Get user.id

    emp = Employee(
        org_id=current_user.org_id,
        user_id=user.id,
        title=payload.title,
        department_id=payload.department_id,
    )
    db.add(emp)
    await db.commit()
    await db.refresh(emp)

    result = await db.execute(
        select(Employee).options(selectinload(Employee.user)).where(Employee.id == emp.id)
    )
    emp = result.scalar_one()
    return _build_employee_response(emp)


@router.get("/me", response_model=EmployeeResponse)
async def get_my_employee_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get the current user's employee profile."""
    result = await db.execute(
        select(Employee)
        .options(selectinload(Employee.user))
        .where(Employee.user_id == current_user.id)
    )
    emp = result.scalar_one_or_none()
    if not emp:
        raise AppException(message="Employee profile not found.", code="EMPLOYEE_NOT_FOUND", status_code=404)
    return _build_employee_response(emp)


@router.get("/{employee_id}", response_model=EmployeeResponse)
async def get_employee(
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Get a single employee by ID."""
    result = await db.execute(
        select(Employee).options(selectinload(Employee.user)).where(Employee.id == employee_id)
    )
    emp = result.scalar_one_or_none()
    if not emp:
        raise AppException(message="Employee not found.", code="EMPLOYEE_NOT_FOUND", status_code=404)
    return _build_employee_response(emp)


@router.patch("/{employee_id}", response_model=EmployeeResponse)
async def update_employee(
    employee_id: uuid.UUID,
    payload: EmployeeUserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Update employee and user profile (admin only)."""
    result = await db.execute(
        select(Employee).options(selectinload(Employee.user)).where(Employee.id == employee_id)
    )
    emp = result.scalar_one_or_none()
    if not emp:
        raise AppException(message="Employee not found.", code="EMPLOYEE_NOT_FOUND", status_code=404)

    update_data = payload.model_dump(exclude_unset=True)

    # User fields
    for field in ("full_name", "phone_number", "role", "is_active"):
        if field in update_data:
            if field == "role" and update_data[field] not in ALLOWED_ROLES:
                raise AppException(message=f"Role must be one of: {ALLOWED_ROLES}", code="INVALID_ROLE", status_code=400)
            setattr(emp.user, field, update_data.pop(field))

    # Employee fields
    for field in ("title", "department_id", "is_available_for_takeover", "is_available_for_booking"):
        if field in update_data:
            setattr(emp, field, update_data[field])

    await db.commit()

    result = await db.execute(
        select(Employee).options(selectinload(Employee.user)).where(Employee.id == employee_id)
    )
    emp = result.scalar_one()
    return _build_employee_response(emp)


@router.delete("/{employee_id}", status_code=204)
async def deactivate_employee(
    employee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Deactivate an employee (soft delete — sets is_active=False)."""
    result = await db.execute(
        select(Employee).options(selectinload(Employee.user)).where(Employee.id == employee_id)
    )
    emp = result.scalar_one_or_none()
    if not emp:
        raise AppException(message="Employee not found.", code="EMPLOYEE_NOT_FOUND", status_code=404)
    emp.user.is_active = False
    await db.commit()
