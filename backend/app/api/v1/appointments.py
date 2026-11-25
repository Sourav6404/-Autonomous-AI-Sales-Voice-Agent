"""Stage 7 Appointment and Calendar Management REST API."""

import uuid
from datetime import date, datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.api.deps import (
    get_current_active_user,
    require_admin,
    require_employee,
    require_receptionist,
)
from backend.app.core.database import get_db
from backend.app.core.exceptions import AppException
from backend.app.models.appointment import Appointment
from backend.app.models.customer import Customer
from backend.app.models.employee import Employee
from backend.app.models.user import User
from backend.app.schemas.appointment import (
    AppointmentAvailabilityResponse,
    AppointmentCancel,
    AppointmentCreate,
    AppointmentListResponse,
    AppointmentReschedule,
    AppointmentResponse,
    AppointmentStatsResponse,
)
from backend.app.services.appointments.availability import AppointmentAvailabilityService
from backend.app.services.appointments.booking import AppointmentBookingService

router = APIRouter(prefix="/appointments", tags=["Appointments & Calendar"])


def _build_appointment_response(appt: Appointment) -> AppointmentResponse:
    data = AppointmentResponse.model_validate(appt)
    if appt.customer:
        data.customer_name = f"{appt.customer.first_name or ''} {appt.customer.last_name or ''}".strip() or None
        data.customer_phone = appt.customer.phone_number
    if appt.employee and appt.employee.user:
        data.employee_name = appt.employee.user.full_name
    return data


@router.get("/availability", response_model=AppointmentAvailabilityResponse)
async def check_availability(
    target_date: date = Query(..., alias="date", description="Target booking date (YYYY-MM-DD)"),
    employee_id: Optional[uuid.UUID] = Query(None, description="Optional specific staff member UUID"),
    duration_minutes: int = Query(30, ge=15, le=120),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Calculates all open, conflict-free appointment time slots for a given date."""
    return await AppointmentAvailabilityService.get_available_slots(
        db=db,
        org_id=current_user.org_id,
        target_date=target_date,
        employee_id=employee_id,
        duration_minutes=duration_minutes,
    )


@router.get("/stats", response_model=AppointmentStatsResponse)
async def get_appointment_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_receptionist),
):
    """Returns appointment overview statistics."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    total = (await db.execute(select(func.count(Appointment.id)))).scalar_one()
    upcoming = (
        await db.execute(
            select(func.count(Appointment.id)).where(
                Appointment.start_time >= now,
                Appointment.status.in_(["scheduled", "confirmed"]),
            )
        )
    ).scalar_one()
    completed = (
        await db.execute(
            select(func.count(Appointment.id)).where(Appointment.status == "completed")
        )
    ).scalar_one()
    cancelled = (
        await db.execute(
            select(func.count(Appointment.id)).where(Appointment.status == "cancelled")
        )
    ).scalar_one()
    today = (
        await db.execute(
            select(func.count(Appointment.id)).where(
                Appointment.start_time >= today_start,
                Appointment.status.in_(["scheduled", "confirmed"]),
            )
        )
    ).scalar_one()

    return AppointmentStatsResponse(
        total_appointments=total,
        upcoming_appointments=upcoming,
        completed_appointments=completed,
        cancelled_appointments=cancelled,
        today_appointments=today,
    )


@router.get("/my-calendar", response_model=AppointmentListResponse)
async def get_my_calendar(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Sales employee: read-only access strictly to their assigned appointments."""
    emp_res = await db.execute(select(Employee).where(Employee.user_id == current_user.id))
    emp = emp_res.scalar_one_or_none()
    if not emp:
        return AppointmentListResponse(items=[], total=0, page=page, page_size=page_size)

    stmt = (
        select(Appointment)
        .options(selectinload(Appointment.customer), selectinload(Appointment.employee).selectinload(Employee.user))
        .where(Appointment.employee_id == emp.id)
    )
    if status:
        stmt = stmt.where(Appointment.status == status)
    stmt = stmt.order_by(Appointment.start_time.asc())

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    appts = result.scalars().all()

    return AppointmentListResponse(
        items=[_build_appointment_response(a) for a in appts],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("", response_model=AppointmentListResponse)
async def list_appointments(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    customer_id: Optional[uuid.UUID] = Query(None),
    employee_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_receptionist),
):
    """Receptionist/Admin: list all tenant appointments with multi-criteria filtering."""
    stmt = (
        select(Appointment)
        .options(selectinload(Appointment.customer), selectinload(Appointment.employee).selectinload(Employee.user))
    )
    if status:
        stmt = stmt.where(Appointment.status == status)
    if date_from:
        stmt = stmt.where(Appointment.start_time >= date_from)
    if date_to:
        stmt = stmt.where(Appointment.end_time <= date_to)
    if customer_id:
        stmt = stmt.where(Appointment.customer_id == customer_id)
    if employee_id:
        stmt = stmt.where(Appointment.employee_id == employee_id)

    stmt = stmt.order_by(Appointment.start_time.asc())

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    appts = result.scalars().all()

    return AppointmentListResponse(
        items=[_build_appointment_response(a) for a in appts],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
async def create_appointment(
    payload: AppointmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_receptionist),
):
    """Manually schedule an appointment (receptionist or admin)."""
    appt = await AppointmentBookingService.book_appointment(
        db=db,
        org_id=current_user.org_id,
        customer_id=payload.customer_id,
        employee_id=payload.employee_id,
        lead_id=payload.lead_id,
        start_time=payload.start_time,
        end_time=payload.end_time,
        meeting_type=payload.meeting_type,
        title=payload.title,
        purpose=payload.purpose,
        meeting_link_or_phone=payload.meeting_link_or_phone,
        notes=payload.notes,
        booking_source="manual",
        created_by_user_id=current_user.id,
    )
    return _build_appointment_response(appt)


@router.get("/{appointment_id}", response_model=AppointmentResponse)
async def get_appointment(
    appointment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Retrieve appointment details. Sales employees can only access their assigned appointments."""
    stmt = (
        select(Appointment)
        .options(selectinload(Appointment.customer), selectinload(Appointment.employee).selectinload(Employee.user))
        .where(Appointment.id == appointment_id)
    )
    res = await db.execute(stmt)
    appt = res.scalar_one_or_none()
    if not appt:
        raise AppException(message="Appointment not found.", code="APPOINTMENT_NOT_FOUND", status_code=404)

    # Sales restriction
    if current_user.role in ("sales_employee", "employee"):
        emp_res = await db.execute(select(Employee).where(Employee.user_id == current_user.id))
        emp = emp_res.scalar_one_or_none()
        if not emp or appt.employee_id != emp.id:
            raise AppException(
                message="Access denied: you are not assigned to this appointment.",
                code="INSUFFICIENT_PERMISSIONS",
                status_code=403,
            )

    return _build_appointment_response(appt)


@router.patch("/{appointment_id}/reschedule", response_model=AppointmentResponse)
async def reschedule_appointment(
    appointment_id: uuid.UUID,
    payload: AppointmentReschedule,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_receptionist),
):
    """Reschedule an existing appointment to a new validated slot."""
    appt = await AppointmentBookingService.reschedule_appointment(
        db=db,
        org_id=current_user.org_id,
        appointment_id=appointment_id,
        new_start_time=payload.new_start_time,
        new_end_time=payload.new_end_time,
        reason=payload.reason,
    )
    return _build_appointment_response(appt)


@router.post("/{appointment_id}/cancel", response_model=AppointmentResponse)
async def cancel_appointment(
    appointment_id: uuid.UUID,
    payload: AppointmentCancel,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_receptionist),
):
    """Cancel an existing appointment with required reason."""
    appt = await AppointmentBookingService.cancel_appointment(
        db=db,
        org_id=current_user.org_id,
        appointment_id=appointment_id,
        reason=payload.reason,
    )
    # Reload with relations
    res = await db.execute(
        select(Appointment)
        .options(selectinload(Appointment.customer), selectinload(Appointment.employee).selectinload(Employee.user))
        .where(Appointment.id == appt.id)
    )
    return _build_appointment_response(res.scalar_one())
