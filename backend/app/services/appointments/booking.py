"""Appointment Booking & Lifecycle Service.

Enforces:
- Collision prevention & immediate revalidation before booking
- Explicit customer ownership & tenant boundary validation
- Rescheduling with availability checking
- Cancellation with audit reason tracking
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.core.exceptions import AppException
from backend.app.models.appointment import Appointment
from backend.app.models.customer import Customer
from backend.app.models.employee import Employee
from backend.app.models.lead import Lead
from backend.app.models.user import User

logger = logging.getLogger(__name__)


class AppointmentBookingService:
    """Manages transactional booking, rescheduling, and cancellation."""

    @classmethod
    async def book_appointment(
        cls,
        db: AsyncSession,
        org_id: UUID,
        customer_id: UUID,
        start_time: datetime,
        end_time: datetime,
        employee_id: Optional[UUID] = None,
        lead_id: Optional[UUID] = None,
        title: Optional[str] = None,
        purpose: Optional[str] = None,
        meeting_type: str = "Sales Discovery Call",
        meeting_link_or_phone: Optional[str] = None,
        notes: Optional[str] = None,
        booking_source: str = "ai_receptionist",
        created_by_user_id: Optional[UUID] = None,
    ) -> Appointment:
        """Creates a validated, conflict-free appointment record."""
        # 1. Validate customer in tenant
        cust_res = await db.execute(
            select(Customer).where(Customer.id == customer_id, Customer.org_id == org_id)
        )
        customer = cust_res.scalar_one_or_none()
        if not customer:
            raise AppException(message="Customer not found.", code="CUSTOMER_NOT_FOUND", status_code=404)

        # 2. Time order validation
        start_utc = start_time if start_time.tzinfo else start_time.replace(tzinfo=timezone.utc)
        end_utc = end_time if end_time.tzinfo else end_time.replace(tzinfo=timezone.utc)
        if start_utc >= end_utc:
            raise AppException(
                message="Appointment start time must be before end time.",
                code="INVALID_TIME_ORDER",
                status_code=400,
            )

        # 3. Select employee
        if not employee_id:
            # Pick first active booking-available employee
            emp_res = await db.execute(
                select(Employee).where(
                    Employee.org_id == org_id,
                    Employee.is_available_for_booking == True,
                )
            )
            emp = emp_res.scalars().first()
            if not emp:
                raise AppException(
                    message="No staff members are currently available for booking.",
                    code="NO_STAFF_AVAILABLE",
                    status_code=400,
                )
            target_emp_id = emp.id
        else:
            emp_res = await db.execute(
                select(Employee).where(
                    Employee.id == employee_id,
                    Employee.org_id == org_id,
                )
            )
            emp = emp_res.scalar_one_or_none()
            if not emp:
                raise AppException(
                    message="Specified staff employee was not found.",
                    code="EMPLOYEE_NOT_FOUND",
                    status_code=404,
                )
            target_emp_id = emp.id

        # 4. Immediate revalidation: check for overlapping active appointment
        conflict_query = select(Appointment).where(
            Appointment.employee_id == target_emp_id,
            Appointment.status.notin_(["cancelled", "no_show"]),
            Appointment.start_time < end_utc,
            Appointment.end_time > start_utc,
        )
        conflict_res = await db.execute(conflict_query)
        if conflict_res.scalar_one_or_none():
            raise AppException(
                message="Requested time slot is no longer available due to a booking collision.",
                code="SLOT_CONFLICT",
                status_code=409,
            )

        # 5. Create Appointment
        appt = Appointment(
            org_id=org_id,
            customer_id=customer_id,
            employee_id=target_emp_id,
            lead_id=lead_id,
            created_by_user_id=created_by_user_id,
            title=title or f"{meeting_type} with {customer.first_name or customer.phone_number}",
            purpose=purpose or notes,
            start_time=start_utc,
            end_time=end_utc,
            status="confirmed",
            meeting_type=meeting_type,
            meeting_link_or_phone=meeting_link_or_phone or customer.phone_number,
            booking_source=booking_source,
            notes=notes,
        )
        db.add(appt)
        await db.commit()
        await db.refresh(appt)

        # Load with customer and employee relations
        res = await db.execute(
            select(Appointment)
            .options(selectinload(Appointment.customer), selectinload(Appointment.employee).selectinload(Employee.user))
            .where(Appointment.id == appt.id)
        )
        return res.scalar_one()

    @classmethod
    async def reschedule_appointment(
        cls,
        db: AsyncSession,
        org_id: UUID,
        appointment_id: UUID,
        new_start_time: datetime,
        new_end_time: datetime,
        reason: Optional[str] = None,
    ) -> Appointment:
        """Reschedules an existing appointment to a new validated slot."""
        res = await db.execute(
            select(Appointment).where(
                Appointment.id == appointment_id,
                Appointment.org_id == org_id,
            )
        )
        appt = res.scalar_one_or_none()
        if not appt:
            raise AppException(message="Appointment not found.", code="APPOINTMENT_NOT_FOUND", status_code=404)

        if appt.status in ("cancelled", "completed"):
            raise AppException(
                message=f"Cannot reschedule an appointment in '{appt.status}' status.",
                code="INVALID_STATUS_TRANSITION",
                status_code=400,
            )

        start_utc = new_start_time if new_start_time.tzinfo else new_start_time.replace(tzinfo=timezone.utc)
        end_utc = new_end_time if new_end_time.tzinfo else new_end_time.replace(tzinfo=timezone.utc)
        if start_utc >= end_utc:
            raise AppException(
                message="Start time must be before end time.",
                code="INVALID_TIME_ORDER",
                status_code=400,
            )

        # Check collision with other appointments
        conflict_query = select(Appointment).where(
            Appointment.employee_id == appt.employee_id,
            Appointment.id != appt.id,
            Appointment.status.notin_(["cancelled", "no_show"]),
            Appointment.start_time < end_utc,
            Appointment.end_time > start_utc,
        )
        conflict_res = await db.execute(conflict_query)
        if conflict_res.scalar_one_or_none():
            raise AppException(
                message="Requested reschedule slot conflicts with an existing booking.",
                code="SLOT_CONFLICT",
                status_code=409,
            )

        appt.start_time = start_utc
        appt.end_time = end_utc
        appt.status = "scheduled"
        if reason:
            appt.notes = f"{appt.notes or ''}\nRescheduled: {reason}".strip()

        await db.commit()
        await db.refresh(appt)

        res = await db.execute(
            select(Appointment)
            .options(selectinload(Appointment.customer), selectinload(Appointment.employee).selectinload(Employee.user))
            .where(Appointment.id == appt.id)
        )
        return res.scalar_one()

    @classmethod
    async def cancel_appointment(
        cls,
        db: AsyncSession,
        org_id: UUID,
        appointment_id: UUID,
        reason: str,
    ) -> Appointment:
        """Cancels an existing appointment."""
        res = await db.execute(
            select(Appointment).where(
                Appointment.id == appointment_id,
                Appointment.org_id == org_id,
            )
        )
        appt = res.scalar_one_or_none()
        if not appt:
            raise AppException(message="Appointment not found.", code="APPOINTMENT_NOT_FOUND", status_code=404)

        if appt.status == "cancelled":
            return appt

        appt.status = "cancelled"
        appt.cancellation_reason = reason
        await db.commit()
        await db.refresh(appt)
        return appt
