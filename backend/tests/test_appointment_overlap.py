"""Tests for appointment constraints and collision prevention logic."""

import uuid
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.models.appointment import Appointment
from backend.app.models.customer import Customer
from backend.app.models.department import Department
from backend.app.models.employee import Employee
from backend.app.models.organization import Organization
from backend.app.models.user import User


@pytest.mark.asyncio
async def test_appointment_time_order_constraint(db_session: AsyncSession):
    """Tests that an appointment with start_time >= end_time violates check constraint."""
    org = Organization(name="Booking Org", slug="booking-org")
    db_session.add(org)
    await db_session.commit()

    cust = Customer(org_id=org.id, phone_number="+1999999999")
    user = User(org_id=org.id, email="emp@test.com", password_hash="hash", full_name="Emp")
    db_session.add_all([cust, user])
    await db_session.commit()

    emp = Employee(org_id=org.id, user_id=user.id)
    db_session.add(emp)
    await db_session.commit()

    now = datetime.now(timezone.utc)
    # Invalid: start_time is AFTER end_time
    invalid_appt = Appointment(
        org_id=org.id,
        customer_id=cust.id,
        employee_id=emp.id,
        start_time=now + timedelta(hours=2),
        end_time=now + timedelta(hours=1),
        status="scheduled",
    )
    db_session.add(invalid_appt)

    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_appointment_overlap_detection_logic(db_session: AsyncSession):
    """Tests overlap detection logic ensuring employee cannot be double-booked."""
    org = Organization(name="Overlap Org", slug="overlap-org")
    db_session.add(org)
    await db_session.commit()

    cust1 = Customer(org_id=org.id, phone_number="+1111111111")
    cust2 = Customer(org_id=org.id, phone_number="+2222222222")
    user = User(org_id=org.id, email="rep@test.com", password_hash="hash", full_name="Sales Rep")
    db_session.add_all([cust1, cust2, user])
    await db_session.commit()

    emp = Employee(org_id=org.id, user_id=user.id)
    db_session.add(emp)
    await db_session.commit()

    slot_start = datetime(2026, 12, 1, 14, 0, tzinfo=timezone.utc)
    slot_end = datetime(2026, 12, 1, 14, 30, tzinfo=timezone.utc)

    # 1. First appointment booked
    appt1 = Appointment(
        org_id=org.id,
        customer_id=cust1.id,
        employee_id=emp.id,
        start_time=slot_start,
        end_time=slot_end,
        status="scheduled",
    )
    db_session.add(appt1)
    await db_session.commit()

    # 2. Query to detect collision for a new requested appointment
    overlap_query = select(Appointment).where(
        Appointment.employee_id == emp.id,
        Appointment.status.notin_(["cancelled", "no_show"]),
        Appointment.start_time < slot_end,
        Appointment.end_time > slot_start,
    )
    conflicting_slots = (await db_session.execute(overlap_query)).scalars().all()
    assert len(conflicting_slots) == 1
    assert conflicting_slots[0].id == appt1.id
