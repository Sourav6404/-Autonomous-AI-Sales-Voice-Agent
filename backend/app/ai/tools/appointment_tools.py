"""Stage 7 AI Receptionist Appointment & Calendar Tools.

Tools:
1. check_appointment_availability: Check if business is open and has booking capacity on a date.
2. get_available_appointment_slots: List concrete available start/end times on a date.
3. book_appointment: Confirm and schedule a slot. Requires customer_confirmed=True.
4. get_customer_appointments: Retrieve existing appointments for the customer.
5. reschedule_appointment: Move an existing appointment to a new open slot.
6. cancel_appointment: Cancel an appointment with a documented reason.
"""

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.ai.tools.registry import ToolExecutionContext, tool_registry
from backend.app.models.appointment import Appointment
from backend.app.models.call import Call
from backend.app.models.customer import Customer
from backend.app.models.employee import Employee
from backend.app.models.lead import Lead
from backend.app.services.appointments.availability import AppointmentAvailabilityService
from backend.app.services.appointments.booking import AppointmentBookingService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CheckAppointmentAvailabilityInput(BaseModel):
    date_str: str = Field(..., description="Target date in YYYY-MM-DD format (e.g., '2026-12-01')")
    employee_id: Optional[str] = Field(None, description="Optional UUID of specific staff employee")


class GetAvailableAppointmentSlotsInput(BaseModel):
    date_str: str = Field(..., description="Target date in YYYY-MM-DD format (e.g., '2026-12-01')")
    employee_id: Optional[str] = Field(None, description="Optional UUID of specific staff employee")
    duration_minutes: int = Field(30, description="Duration in minutes (default 30)")


class BookAppointmentInput(BaseModel):
    start_time_iso: str = Field(..., description="Chosen appointment start time in ISO-8601 format")
    end_time_iso: str = Field(..., description="Chosen appointment end time in ISO-8601 format")
    customer_phone: Optional[str] = Field(None, description="Customer phone number")
    customer_name: Optional[str] = Field(None, description="Customer full name")
    meeting_type: str = Field("Sales Discovery Call", description="Meeting type / purpose")
    notes: Optional[str] = Field(None, description="Discussion notes or agenda")
    customer_confirmed: bool = Field(
        ...,
        description="MUST be True. Explicit customer confirmation is mandatory before booking.",
    )


class GetCustomerAppointmentsInput(BaseModel):
    customer_phone: Optional[str] = Field(None, description="Customer phone number")


class RescheduleAppointmentInput(BaseModel):
    appointment_id: str = Field(..., description="UUID of the existing appointment to reschedule")
    new_start_time_iso: str = Field(..., description="New appointment start time in ISO-8601 format")
    new_end_time_iso: str = Field(..., description="New appointment end time in ISO-8601 format")
    reason: Optional[str] = Field(None, description="Reason for rescheduling")


class CancelAppointmentInput(BaseModel):
    appointment_id: str = Field(..., description="UUID of the appointment to cancel")
    reason: str = Field(..., description="Mandatory reason for cancellation")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(d_str: str) -> Optional[date]:
    try:
        return date.fromisoformat(d_str.strip())
    except Exception:
        return None


def _parse_datetime(dt_str: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(dt_str.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


async def _resolve_customer(context: ToolExecutionContext, phone: Optional[str], name: Optional[str] = None) -> Optional[Customer]:
    target_phone = phone
    if not target_phone and context.conversation_id:
        # Check call linked to conversation
        call_res = await context.db.execute(
            select(Call).where(Call.org_id == context.org_id).order_by(Call.started_at.desc())
        )
        call = call_res.scalars().first()
        if call:
            target_phone = call.caller_phone_number

    if not target_phone:
        return None

    cust_res = await context.db.execute(
        select(Customer).where(Customer.org_id == context.org_id, Customer.phone_number == target_phone)
    )
    customer = cust_res.scalar_one_or_none()
    if not customer:
        customer = Customer(
            org_id=context.org_id,
            phone_number=target_phone,
            first_name=name,
            total_calls_count=1,
            last_called_at=datetime.now(timezone.utc),
        )
        context.db.add(customer)
        await context.db.flush()
    return customer


# ---------------------------------------------------------------------------
# Tool Implementations
# ---------------------------------------------------------------------------

@tool_registry.register(
    name="check_appointment_availability",
    description="Check whether the business is open and has staff availability on a specific date.",
    input_schema=CheckAppointmentAvailabilityInput,
)
async def check_appointment_availability(
    args: CheckAppointmentAvailabilityInput,
    context: ToolExecutionContext,
) -> Dict[str, Any]:
    target_date = _parse_date(args.date_str)
    if not target_date:
        return {"error": f"Invalid date format '{args.date_str}'. Please specify YYYY-MM-DD."}

    emp_id = None
    if args.employee_id:
        try:
            emp_id = UUID(args.employee_id)
        except Exception:
            pass

    avail = await AppointmentAvailabilityService.get_available_slots(
        db=context.db,
        org_id=context.org_id,
        target_date=target_date,
        employee_id=emp_id,
        duration_minutes=30,
    )

    return {
        "date": str(avail.date),
        "timezone": avail.timezone,
        "business_open": avail.business_open,
        "reason": avail.reason,
        "available_slot_count": len(avail.slots),
        "has_availability": len(avail.slots) > 0,
    }


@tool_registry.register(
    name="get_available_appointment_slots",
    description="Retrieve concrete available appointment start and end times on a date.",
    input_schema=GetAvailableAppointmentSlotsInput,
)
async def get_available_appointment_slots(
    args: GetAvailableAppointmentSlotsInput,
    context: ToolExecutionContext,
) -> Dict[str, Any]:
    target_date = _parse_date(args.date_str)
    if not target_date:
        return {"error": f"Invalid date format '{args.date_str}'. Please use YYYY-MM-DD."}

    emp_id = None
    if args.employee_id:
        try:
            emp_id = UUID(args.employee_id)
        except Exception:
            pass

    avail = await AppointmentAvailabilityService.get_available_slots(
        db=context.db,
        org_id=context.org_id,
        target_date=target_date,
        employee_id=emp_id,
        duration_minutes=args.duration_minutes,
    )

    if not avail.business_open:
        return {
            "business_open": False,
            "reason": avail.reason,
            "available_slots": [],
        }

    formatted_slots = [
        {
            "start_time": s.start_time.isoformat(),
            "end_time": s.end_time.isoformat(),
            "duration_minutes": s.duration_minutes,
            "staff_member": s.employee_name,
            "employee_id": str(s.employee_id),
        }
        for s in avail.slots[:8]  # Limit to 8 slots for concise voice responses
    ]

    return {
        "date": str(avail.date),
        "timezone": avail.timezone,
        "available_slots": formatted_slots,
        "total_slots_found": len(avail.slots),
    }


@tool_registry.register(
    name="book_appointment",
    description="Book a confirmed appointment. MUST only be called after the customer has explicitly agreed to the date and time.",
    input_schema=BookAppointmentInput,
)
async def book_appointment(
    args: BookAppointmentInput,
    context: ToolExecutionContext,
) -> Dict[str, Any]:
    if not args.customer_confirmed:
        return {
            "status": "unconfirmed",
            "message": "Explicit customer confirmation is required before booking can be completed. Please ask the customer to confirm.",
        }

    start_dt = _parse_datetime(args.start_time_iso)
    end_dt = _parse_datetime(args.end_time_iso)
    if not start_dt or not end_dt:
        return {"error": "Invalid start or end time format. Please provide valid ISO-8601 datetimes."}

    customer = await _resolve_customer(context, args.customer_phone, args.customer_name)
    if not customer:
        return {"error": "Could not identify customer. Please provide caller phone number."}

    # Optional lead linkage
    lead_res = await context.db.execute(
        select(Lead).where(Lead.customer_id == customer.id, Lead.org_id == context.org_id).order_by(Lead.created_at.desc())
    )
    lead = lead_res.scalars().first()

    try:
        appt = await AppointmentBookingService.book_appointment(
            db=context.db,
            org_id=context.org_id,
            customer_id=customer.id,
            start_time=start_dt,
            end_time=end_dt,
            lead_id=lead.id if lead else None,
            title=f"{args.meeting_type} with {customer.first_name or customer.phone_number}",
            purpose=args.notes or args.meeting_type,
            meeting_type=args.meeting_type,
            booking_source="ai_receptionist",
            notes=args.notes,
        )
        return {
            "status": "success",
            "appointment_id": str(appt.id),
            "start_time": appt.start_time.isoformat(),
            "end_time": appt.end_time.isoformat(),
            "customer_phone": customer.phone_number,
            "meeting_type": appt.meeting_type,
            "message": f"Appointment successfully booked for {appt.start_time.strftime('%A, %B %d, %Y at %I:%M %p UTC')}.",
        }
    except Exception as e:
        logger.warning("Appointment booking failed: %s", e)
        return {"error": str(e)}


@tool_registry.register(
    name="get_customer_appointments",
    description="Look up scheduled and upcoming appointments for the caller.",
    input_schema=GetCustomerAppointmentsInput,
)
async def get_customer_appointments(
    args: GetCustomerAppointmentsInput,
    context: ToolExecutionContext,
) -> Dict[str, Any]:
    customer = await _resolve_customer(context, args.customer_phone)
    if not customer:
        return {"appointments": [], "count": 0}

    now = datetime.now(timezone.utc)
    res = await context.db.execute(
        select(Appointment)
        .where(
            Appointment.customer_id == customer.id,
            Appointment.org_id == context.org_id,
            Appointment.status.notin_(["cancelled", "no_show"]),
        )
        .order_by(Appointment.start_time.asc())
    )
    appts = res.scalars().all()

    return {
        "customer_phone": customer.phone_number,
        "count": len(appts),
        "appointments": [
            {
                "id": str(a.id),
                "title": a.title,
                "start_time": a.start_time.isoformat(),
                "end_time": a.end_time.isoformat(),
                "status": a.status,
                "meeting_type": a.meeting_type,
            }
            for a in appts
        ],
    }


@tool_registry.register(
    name="reschedule_appointment",
    description="Reschedule an existing appointment to a new validated time slot.",
    input_schema=RescheduleAppointmentInput,
)
async def reschedule_appointment(
    args: RescheduleAppointmentInput,
    context: ToolExecutionContext,
) -> Dict[str, Any]:
    try:
        appt_id = UUID(args.appointment_id)
    except Exception:
        return {"error": f"Invalid appointment UUID '{args.appointment_id}'."}

    start_dt = _parse_datetime(args.new_start_time_iso)
    end_dt = _parse_datetime(args.new_end_time_iso)
    if not start_dt or not end_dt:
        return {"error": "Invalid new start or end time format."}

    try:
        appt = await AppointmentBookingService.reschedule_appointment(
            db=context.db,
            org_id=context.org_id,
            appointment_id=appt_id,
            new_start_time=start_dt,
            new_end_time=end_dt,
            reason=args.reason,
        )
        return {
            "status": "success",
            "appointment_id": str(appt.id),
            "new_start_time": appt.start_time.isoformat(),
            "new_end_time": appt.end_time.isoformat(),
            "message": f"Appointment successfully moved to {appt.start_time.strftime('%A, %B %d, %Y at %I:%M %p UTC')}.",
        }
    except Exception as e:
        return {"error": str(e)}


@tool_registry.register(
    name="cancel_appointment",
    description="Cancel a scheduled appointment with a documented cancellation reason.",
    input_schema=CancelAppointmentInput,
)
async def cancel_appointment(
    args: CancelAppointmentInput,
    context: ToolExecutionContext,
) -> Dict[str, Any]:
    try:
        appt_id = UUID(args.appointment_id)
    except Exception:
        return {"error": f"Invalid appointment UUID '{args.appointment_id}'."}

    try:
        appt = await AppointmentBookingService.cancel_appointment(
            db=context.db,
            org_id=context.org_id,
            appointment_id=appt_id,
            reason=args.reason,
        )
        return {
            "status": "cancelled",
            "appointment_id": str(appt.id),
            "message": "Appointment has been cancelled.",
        }
    except Exception as e:
        return {"error": str(e)}
