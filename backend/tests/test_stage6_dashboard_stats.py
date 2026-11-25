"""Tests for Stage 6 Dashboard Statistics (Admin, Receptionist, Sales)."""

import uuid
from datetime import datetime, timezone
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.security import PasswordHasher, create_access_token
from backend.app.models.call import Call
from backend.app.models.customer import Customer
from backend.app.models.employee import Employee
from backend.app.models.inquiry import Inquiry
from backend.app.models.lead import Lead
from backend.app.models.organization import Organization
from backend.app.models.user import User


@pytest.mark.asyncio
async def test_dashboard_stats_endpoints(client: AsyncClient, db_session: AsyncSession):
    # Setup Org
    org = Organization(name="Stats Org", slug=f"stats-{uuid.uuid4().hex[:6]}", default_timezone="UTC")
    db_session.add(org)
    await db_session.flush()

    # Admin user
    admin_user = User(
        org_id=org.id,
        email="admin@stats.com",
        password_hash=PasswordHasher.hash("Pass12345!"),
        full_name="Stats Admin",
        role="admin",
        is_active=True,
    )
    # Receptionist user
    receptionist_user = User(
        org_id=org.id,
        email="receptionist@stats.com",
        password_hash=PasswordHasher.hash("Pass12345!"),
        full_name="Stats Receptionist",
        role="receptionist",
        is_active=True,
    )
    # Sales user
    sales_user = User(
        org_id=org.id,
        email="sales@stats.com",
        password_hash=PasswordHasher.hash("Pass12345!"),
        full_name="Stats Sales",
        role="sales_employee",
        is_active=True,
    )
    db_session.add_all([admin_user, receptionist_user, sales_user])
    await db_session.flush()

    sales_emp = Employee(org_id=org.id, user_id=sales_user.id, title="Account Exec")
    db_session.add(sales_emp)

    # Customer
    customer = Customer(org_id=org.id, phone_number="+15551112233", first_name="Dan")
    db_session.add(customer)
    await db_session.flush()

    # Call today
    call = Call(
        org_id=org.id,
        customer_id=customer.id,
        caller_phone_number="+15551112233",
        callee_phone_number="AI-Receptionist",
        status="completed",
        started_at=datetime.now(timezone.utc),
        duration_seconds=120,
    )
    db_session.add(call)

    # Lead assigned to sales
    lead = Lead(
        org_id=org.id,
        customer_id=customer.id,
        assigned_employee_id=sales_emp.id,
        title="Dan's Inquiry",
        status="new",
        qualification_tier="warm",
        score=65,
    )
    db_session.add(lead)

    # Inquiry
    inquiry = Inquiry(
        org_id=org.id,
        customer_id=customer.id,
        subject="Product query",
        status="open",
        priority="medium",
    )
    db_session.add(inquiry)

    await db_session.commit()

    admin_token = create_access_token(str(admin_user.id), str(org.id), admin_user.role, admin_user.email)
    rec_token = create_access_token(str(receptionist_user.id), str(org.id), receptionist_user.role, receptionist_user.email)
    sales_token = create_access_token(str(sales_user.id), str(org.id), sales_user.role, sales_user.email)

    # 1. Admin dashboard stats
    admin_res = await client.get("/api/v1/dashboard/admin", headers={"Authorization": f"Bearer {admin_token}"})
    assert admin_res.status_code == 200, admin_res.text
    admin_stats = admin_res.json()
    assert admin_stats["total_customers"] == 1
    assert admin_stats["total_calls_today"] == 1
    assert admin_stats["total_leads"] == 1
    assert admin_stats["open_leads"] == 1
    assert admin_stats["total_inquiries"] == 1
    assert admin_stats["total_employees"] == 3
    assert admin_stats["total_sales_employees"] == 1
    assert admin_stats["total_receptionists"] == 1

    # 2. Receptionist dashboard stats
    rec_res = await client.get("/api/v1/dashboard/receptionist", headers={"Authorization": f"Bearer {rec_token}"})
    assert rec_res.status_code == 200, rec_res.text
    rec_stats = rec_res.json()
    assert rec_stats["calls_today"] == 1
    assert rec_stats["open_inquiries"] == 1
    assert len(rec_stats["recent_calls"]) == 1

    # 3. Sales employee dashboard stats
    sales_res = await client.get("/api/v1/dashboard/sales", headers={"Authorization": f"Bearer {sales_token}"})
    assert sales_res.status_code == 200, sales_res.text
    sales_stats = sales_res.json()
    assert sales_stats["my_leads_total"] == 1
    assert sales_stats["my_leads_new"] == 1
    assert len(sales_stats["recent_leads"]) == 1
