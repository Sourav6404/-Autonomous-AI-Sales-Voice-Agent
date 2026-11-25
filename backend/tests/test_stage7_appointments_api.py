"""Stage 7 Integration Tests for Appointments REST API & RBAC."""

import uuid
from datetime import date, datetime, time, timedelta, timezone
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.security import PasswordHasher, create_access_token
from backend.app.models.appointment import Appointment
from backend.app.models.business_hours import BusinessHours
from backend.app.models.customer import Customer
from backend.app.models.employee import Employee
from backend.app.models.holiday import Holiday
from backend.app.models.organization import Organization
from backend.app.models.special_schedule import SpecialSchedule
from backend.app.models.user import User


async def setup_stage7_env(db: AsyncSession):
    org = Organization(name="Stage7 Org", slug=f"s7-{uuid.uuid4().hex[:6]}", default_timezone="UTC")
    db.add(org)
    await db.flush()

    # 1. Operating hours: Monday to Friday 09:00 - 17:00
    # Day of week: 0=Sun, 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat
    for dow in range(1, 6):
        bh = BusinessHours(
            org_id=org.id,
            day_of_week=dow,
            open_time=time(9, 0),
            close_time=time(17, 0),
            is_closed=False,
        )
        db.add(bh)

    # 2. Staff users
    admin_user = User(
        org_id=org.id,
        email=f"admin_{uuid.uuid4().hex[:4]}@s7.com",
        password_hash=PasswordHasher.hash("Pass12345!"),
        full_name="Admin Boss",
        role="admin",
        is_active=True,
    )
    rec_user = User(
        org_id=org.id,
        email=f"rec_{uuid.uuid4().hex[:4]}@s7.com",
        password_hash=PasswordHasher.hash("Pass12345!"),
        full_name="Receptionist Desk",
        role="receptionist",
        is_active=True,
    )
    sales_user = User(
        org_id=org.id,
        email=f"sales_{uuid.uuid4().hex[:4]}@s7.com",
        password_hash=PasswordHasher.hash("Pass12345!"),
        full_name="Sales Rep One",
        role="sales_employee",
        is_active=True,
    )
    db.add_all([admin_user, rec_user, sales_user])
    await db.flush()

    sales_emp = Employee(
        org_id=org.id,
        user_id=sales_user.id,
        title="Senior AE",
        is_available_for_booking=True,
    )
    db.add(sales_emp)

    # 3. Customer
    customer = Customer(
        org_id=org.id,
        phone_number="+15556667788",
        first_name="Frank",
        last_name="Underwood",
    )
    db.add(customer)
    await db.commit()

    admin_token = create_access_token(str(admin_user.id), str(org.id), admin_user.role, admin_user.email)
    rec_token = create_access_token(str(rec_user.id), str(org.id), rec_user.role, rec_user.email)
    sales_token = create_access_token(str(sales_user.id), str(org.id), sales_user.role, sales_user.email)

    return org, admin_token, rec_token, sales_token, sales_emp, customer


@pytest.mark.asyncio
async def test_appointment_availability_and_booking_lifecycle(client: AsyncClient, db_session: AsyncSession):
    org, admin_token, rec_token, sales_token, sales_emp, customer = await setup_stage7_env(db_session)
    rec_headers = {"Authorization": f"Bearer {rec_token}"}
    sales_headers = {"Authorization": f"Bearer {sales_token}"}

    # Pick a Tuesday in the future: 2026-12-08
    target_date = "2026-12-08"

    # 1. Query availability
    avail_res = await client.get(f"/api/v1/appointments/availability?date={target_date}", headers=rec_headers)
    assert avail_res.status_code == 200, avail_res.text
    avail_data = avail_res.json()
    assert avail_data["business_open"] is True
    assert len(avail_data["slots"]) > 0

    first_slot = avail_data["slots"][0]
    slot_start = first_slot["start_time"]
    slot_end = first_slot["end_time"]

    # 2. Book appointment
    book_payload = {
        "customer_id": str(customer.id),
        "employee_id": str(sales_emp.id),
        "start_time": slot_start,
        "end_time": slot_end,
        "meeting_type": "Discovery Demo",
        "notes": "Discuss enterprise tier",
    }
    book_res = await client.post("/api/v1/appointments", json=book_payload, headers=rec_headers)
    assert book_res.status_code == 201, book_res.text
    appt = book_res.json()
    assert appt["status"] == "confirmed"
    assert appt["customer_name"] == "Frank Underwood"
    appt_id = appt["id"]

    # 3. Collision prevention: booking the same slot must fail with 409
    dup_res = await client.post("/api/v1/appointments", json=book_payload, headers=rec_headers)
    assert dup_res.status_code == 409

    # 4. Availability now reflects that the booked slot is gone
    re_avail = await client.get(f"/api/v1/appointments/availability?date={target_date}", headers=rec_headers)
    assert re_avail.status_code == 200
    current_slots = re_avail.json()["slots"]
    assert not any(s["start_time"] == slot_start for s in current_slots)

    # 5. Sales employee views their calendar (read-only)
    cal_res = await client.get("/api/v1/appointments/my-calendar", headers=sales_headers)
    assert cal_res.status_code == 200
    my_cal = cal_res.json()
    assert my_cal["total"] == 1
    assert my_cal["items"][0]["id"] == appt_id

    # 6. Sales employee is forbidden from creating appointments
    sales_create = await client.post("/api/v1/appointments", json=book_payload, headers=sales_headers)
    assert sales_create.status_code == 403

    # 7. Reschedule appointment
    next_slot = current_slots[0]
    resched_res = await client.patch(
        f"/api/v1/appointments/{appt_id}/reschedule",
        json={
            "new_start_time": next_slot["start_time"],
            "new_end_time": next_slot["end_time"],
            "reason": "Customer conflict",
        },
        headers=rec_headers,
    )
    assert resched_res.status_code == 200
    assert resched_res.json()["status"] == "scheduled"

    # 8. Cancel appointment
    cancel_res = await client.post(
        f"/api/v1/appointments/{appt_id}/cancel",
        json={"reason": "Customer no longer interested"},
        headers=rec_headers,
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "cancelled"
    assert cancel_res.json()["cancellation_reason"] == "Customer no longer interested"


@pytest.mark.asyncio
async def test_holiday_and_special_schedule_availability(client: AsyncClient, db_session: AsyncSession):
    org, admin_token, rec_token, _, _, _ = await setup_stage7_env(db_session)
    headers = {"Authorization": f"Bearer {rec_token}"}

    # Add a Holiday on 2026-12-25
    holiday = Holiday(
        org_id=org.id,
        name="Christmas Day",
        start_date=date(2026, 12, 25),
        end_date=date(2026, 12, 25),
    )
    db_session.add(holiday)
    await db_session.commit()

    # Query holiday availability -> must be closed
    h_res = await client.get("/api/v1/appointments/availability?date=2026-12-25", headers=headers)
    assert h_res.status_code == 200
    h_data = h_res.json()
    assert h_data["business_open"] is False
    assert "Christmas Day" in h_data["reason"]
    assert len(h_data["slots"]) == 0
