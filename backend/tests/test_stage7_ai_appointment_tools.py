"""Stage 7 Integration Tests for AI Appointment Tools."""

import uuid
from datetime import date, datetime, time, timedelta, timezone
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.ai.tools.appointment_tools import (
    BookAppointmentInput,
    CancelAppointmentInput,
    CheckAppointmentAvailabilityInput,
    GetAvailableAppointmentSlotsInput,
    GetCustomerAppointmentsInput,
    RescheduleAppointmentInput,
    book_appointment,
    cancel_appointment,
    check_appointment_availability,
    get_available_appointment_slots,
    get_customer_appointments,
    reschedule_appointment,
)
from backend.app.ai.tools.registry import ToolExecutionContext
from backend.app.core.security import PasswordHasher
from backend.app.models.business_hours import BusinessHours
from backend.app.models.customer import Customer
from backend.app.models.employee import Employee
from backend.app.models.organization import Organization
from backend.app.models.user import User


async def setup_tool_env(db: AsyncSession):
    org = Organization(name="AI Tools Org", slug=f"ai-tool-{uuid.uuid4().hex[:6]}", default_timezone="UTC")
    db.add(org)
    await db.flush()

    # Operating hours: Monday to Friday 09:00 - 17:00
    for dow in range(1, 6):
        bh = BusinessHours(
            org_id=org.id,
            day_of_week=dow,
            open_time=time(9, 0),
            close_time=time(17, 0),
            is_closed=False,
        )
        db.add(bh)

    user = User(
        org_id=org.id,
        email="emp@aitools.com",
        password_hash=PasswordHasher.hash("Pass12345!"),
        full_name="Agent Smith",
        role="sales_employee",
        is_active=True,
    )
    db.add(user)
    await db.flush()

    emp = Employee(org_id=org.id, user_id=user.id, is_available_for_booking=True)
    db.add(emp)

    customer = Customer(org_id=org.id, phone_number="+15553334444", first_name="Neo")
    db.add(customer)
    await db.commit()

    context = ToolExecutionContext(
        org_id=org.id,
        db=db,
        conversation_id=uuid.uuid4(),
        caller_role="customer",
    )
    return org, emp, customer, context


@pytest.mark.asyncio
async def test_ai_appointment_tools_flow(db_session: AsyncSession):
    org, emp, customer, context = await setup_tool_env(db_session)

    target_date = "2026-12-09"  # Wednesday

    # 1. check_appointment_availability tool
    check_args = CheckAppointmentAvailabilityInput(date_str=target_date)
    check_res = await check_appointment_availability(check_args, context)
    assert check_res["business_open"] is True
    assert check_res["has_availability"] is True

    # 2. get_available_appointment_slots tool
    slots_args = GetAvailableAppointmentSlotsInput(date_str=target_date)
    slots_res = await get_available_appointment_slots(slots_args, context)
    assert len(slots_res["available_slots"]) > 0
    first_slot = slots_res["available_slots"][0]

    # 3. book_appointment without customer confirmation MUST FAIL
    unconfirmed_args = BookAppointmentInput(
        start_time_iso=first_slot["start_time"],
        end_time_iso=first_slot["end_time"],
        customer_phone=customer.phone_number,
        customer_confirmed=False,
    )
    unconf_res = await book_appointment(unconfirmed_args, context)
    assert unconf_res["status"] == "unconfirmed"
    assert "Explicit customer confirmation is required" in unconf_res["message"]

    # 4. book_appointment WITH customer_confirmed=True succeeds
    confirmed_args = BookAppointmentInput(
        start_time_iso=first_slot["start_time"],
        end_time_iso=first_slot["end_time"],
        customer_phone=customer.phone_number,
        meeting_type="Demo Session",
        customer_confirmed=True,
    )
    book_res = await book_appointment(confirmed_args, context)
    assert book_res["status"] == "success"
    appt_id = book_res["appointment_id"]
    assert "successfully booked" in book_res["message"]

    # 5. get_customer_appointments tool
    get_args = GetCustomerAppointmentsInput(customer_phone=customer.phone_number)
    cust_appts = await get_customer_appointments(get_args, context)
    assert cust_appts["count"] == 1
    assert cust_appts["appointments"][0]["id"] == appt_id

    # 6. cancel_appointment tool
    cancel_args = CancelAppointmentInput(appointment_id=appt_id, reason="Caller had an emergency")
    cancel_res = await cancel_appointment(cancel_args, context)
    assert cancel_res["status"] == "cancelled"
