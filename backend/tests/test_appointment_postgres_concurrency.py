"""PostgreSQL-specific integration tests for appointment concurrency and GiST exclusion constraint."""

import os
import uuid
from datetime import datetime, timedelta, timezone
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from backend.app.core.config import settings
from backend.app.models.appointment import Appointment
from backend.app.models.customer import Customer
from backend.app.models.employee import Employee
from backend.app.models.organization import Organization
from backend.app.models.user import User


def is_live_postgres_available() -> bool:
    """Checks whether a live PostgreSQL instance is reachable."""
    # Only run against real postgresql URL, not sqlite
    if "postgresql" not in settings.async_database_url:
        return False
    import socket
    try:
        sock = socket.create_connection((settings.POSTGRES_SERVER, settings.POSTGRES_PORT), timeout=1.0)
        sock.close()
        return True
    except (OSError, ConnectionRefusedError):
        return False


POSTGRES_ONLINE = is_live_postgres_available()


@pytest.mark.skipif(
    not POSTGRES_ONLINE,
    reason="Docker / live PostgreSQL with btree_gist extension is offline. Start PostgreSQL container to execute."
)
@pytest.mark.asyncio
async def test_postgres_gist_exclusion_constraint_rejects_overlap():
    """Validates that PostgreSQL's native GiST exclusion constraint (no_overlapping_appointments)
    strictly rejects overlapping time ranges for the same employee at the database engine level.
    """
    engine = create_async_engine(settings.async_database_url, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        # 1. Seed tenant and staff records
        org = Organization(name="Live PG Org", slug=f"live-pg-{uuid.uuid4().hex[:8]}")
        session.add(org)
        await session.flush()
        org_id = org.id

        user = User(org_id=org_id, email=f"rep-{uuid.uuid4().hex[:6]}@pg.com", password_hash="hash", full_name="Sales Rep")
        cust1 = Customer(org_id=org_id, phone_number=f"+1{uuid.uuid4().int % 10000000000}")
        cust2 = Customer(org_id=org_id, phone_number=f"+1{uuid.uuid4().int % 10000000000}")
        session.add_all([user, cust1, cust2])
        await session.flush()
        cust1_id = cust1.id
        cust2_id = cust2.id

        emp = Employee(org_id=org_id, user_id=user.id)
        session.add(emp)
        await session.flush()
        emp_id = emp.id

        # 2. Insert initial booking: 14:00 - 14:30 UTC
        base_time = datetime(2026, 12, 10, 14, 0, tzinfo=timezone.utc)
        appt1 = Appointment(
            org_id=org_id,
            customer_id=cust1_id,
            employee_id=emp_id,
            start_time=base_time,
            end_time=base_time + timedelta(minutes=30),
            status="scheduled",
        )
        session.add(appt1)
        await session.commit()

        # 3. Attempt to insert overlapping booking: 14:15 - 14:45 UTC for the same employee
        appt_conflict = Appointment(
            org_id=org_id,
            customer_id=cust2_id,
            employee_id=emp_id,
            start_time=base_time + timedelta(minutes=15),
            end_time=base_time + timedelta(minutes=45),
            status="scheduled",
        )
        session.add(appt_conflict)

        # Database GiST exclusion constraint must reject with IntegrityError
        with pytest.raises(IntegrityError) as exc_info:
            await session.commit()
        await session.rollback()

        assert "no_overlapping_appointments" in str(exc_info.value).lower() or "exclusion" in str(exc_info.value).lower()

    # 4. Insert non-overlapping booking: 14:30 - 15:00 UTC using clean session
    async with session_factory() as session2:
        appt_adjacent = Appointment(
            org_id=org_id,
            customer_id=cust2_id,
            employee_id=emp_id,
            start_time=base_time + timedelta(minutes=30),
            end_time=base_time + timedelta(minutes=60),
            status="scheduled",
        )
        session2.add(appt_adjacent)
        await session2.commit()

        assert appt_adjacent.id is not None

    await engine.dispose()


@pytest.mark.skipif(
    not POSTGRES_ONLINE,
    reason="Docker / live PostgreSQL with btree_gist extension is offline. Start PostgreSQL container to execute."
)
@pytest.mark.asyncio
async def test_postgres_concurrent_simultaneous_booking_race_condition():
    """Tests two simultaneous transactions running concurrently in parallel coroutines
    attempting to book overlapping appointments for the same employee.

    Verifies that PostgreSQL's GiST exclusion constraint serializes conflict detection,
    allowing exactly ONE transaction to succeed and forcing the other to fail with IntegrityError.
    """
    import asyncio
    engine = create_async_engine(settings.async_database_url, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    # 1. Seed test employee and customers
    async with session_factory() as setup_session:
        org = Organization(name="Race Org", slug=f"race-org-{uuid.uuid4().hex[:8]}")
        setup_session.add(org)
        await setup_session.flush()
        org_id = org.id

        user = User(org_id=org_id, email=f"race-rep-{uuid.uuid4().hex[:6]}@pg.com", password_hash="hash", full_name="Sales Rep")
        cust_a = Customer(org_id=org_id, phone_number=f"+1{uuid.uuid4().int % 10000000000}")
        cust_b = Customer(org_id=org_id, phone_number=f"+1{uuid.uuid4().int % 10000000000}")
        setup_session.add_all([user, cust_a, cust_b])
        await setup_session.flush()

        emp = Employee(org_id=org_id, user_id=user.id)
        setup_session.add(emp)
        await setup_session.commit()
        emp_id = emp.id
        cust_a_id = cust_a.id
        cust_b_id = cust_b.id

    race_slot_start = datetime(2026, 12, 15, 10, 0, tzinfo=timezone.utc)
    slot_a_end = race_slot_start + timedelta(minutes=30)  # 10:00 - 10:30
    slot_b_end = race_slot_start + timedelta(minutes=45)  # 10:15 - 10:45 (conflicts)

    # 2. Worker coroutines representing two independent simultaneous client requests
    async def book_worker_a():
        async with session_factory() as session_a:
            appt = Appointment(
                org_id=org_id,
                customer_id=cust_a_id,
                employee_id=emp_id,
                start_time=race_slot_start,
                end_time=slot_a_end,
                status="scheduled",
            )
            session_a.add(appt)
            await session_a.commit()
            return "SUCCESS"

    async def book_worker_b():
        async with session_factory() as session_b:
            appt = Appointment(
                org_id=org_id,
                customer_id=cust_b_id,
                employee_id=emp_id,
                start_time=race_slot_start + timedelta(minutes=15),
                end_time=slot_b_end,
                status="scheduled",
            )
            session_b.add(appt)
            await session_b.commit()
            return "SUCCESS"

    # 3. Execute concurrently
    results = await asyncio.gather(
        book_worker_a(),
        book_worker_b(),
        return_exceptions=True,
    )

    successes = [r for r in results if r == "SUCCESS"]
    failures = [r for r in results if isinstance(r, IntegrityError)]

    # Exactly ONE booking succeeds and exactly ONE fails with IntegrityError
    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
    assert len(failures) == 1, f"Expected exactly 1 exclusion violation, got {len(failures)}"

    await engine.dispose()
