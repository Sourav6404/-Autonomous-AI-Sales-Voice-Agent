"""Stage 6 Customer management API."""

import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import (
    get_current_active_user,
    require_admin,
    require_receptionist,
    require_employee,
)
from backend.app.core.database import get_db
from backend.app.core.exceptions import AppException
from backend.app.models.customer import Customer
from backend.app.models.user import User
from backend.app.schemas.crm import (
    CustomerCreate,
    CustomerListResponse,
    CustomerResponse,
    CustomerUpdate,
)

router = APIRouter(prefix="/customers", tags=["CRM - Customers"])


@router.get("", response_model=CustomerListResponse)
async def list_customers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_receptionist),
):
    """List all customers in the tenant, with optional search."""
    stmt = select(Customer)
    if search:
        search_clean = search.strip()
        term = f"%{search_clean}%"
        alt_term = f"%+{search_clean}%"
        stmt = stmt.where(
            Customer.phone_number.ilike(term)
            | Customer.phone_number.ilike(alt_term)
            | Customer.first_name.ilike(term)
            | Customer.last_name.ilike(term)
            | Customer.email.ilike(term)
            | Customer.company_name.ilike(term)
        )
    stmt = stmt.order_by(Customer.created_at.desc())

    total_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
    total = total_result.scalar_one()

    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    customers = result.scalars().all()

    return CustomerListResponse(
        items=[CustomerResponse.model_validate(c) for c in customers],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_receptionist),
):
    """Create a new customer record."""
    customer = Customer(
        org_id=current_user.org_id,
        **payload.model_dump(),
    )
    db.add(customer)
    await db.commit()
    await db.refresh(customer)
    return CustomerResponse.model_validate(customer)


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_receptionist),
):
    """Get a single customer by ID."""
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise AppException(
            message="Customer not found.",
            code="CUSTOMER_NOT_FOUND",
            status_code=404,
        )
    return CustomerResponse.model_validate(customer)


@router.patch("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: uuid.UUID,
    payload: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_receptionist),
):
    """Update a customer record."""
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise AppException(
            message="Customer not found.",
            code="CUSTOMER_NOT_FOUND",
            status_code=404,
        )
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(customer, field, value)
    await db.commit()
    await db.refresh(customer)
    return CustomerResponse.model_validate(customer)
