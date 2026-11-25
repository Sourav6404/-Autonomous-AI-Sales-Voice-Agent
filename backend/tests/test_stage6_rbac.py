"""Tests for Stage 6 Role-Based Access Control (RBAC) and workspace security."""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.security import PasswordHasher, create_access_token
from backend.app.models.customer import Customer
from backend.app.models.employee import Employee
from backend.app.models.lead import Lead
from backend.app.models.organization import Organization
from backend.app.models.user import User


async def create_scoped_environment(db: AsyncSession):
    org = Organization(name="RBAC 6 Org", slug=f"rbac6-{uuid.uuid4().hex[:6]}", default_timezone="UTC")
    db.add(org)
    await db.flush()

    admin = User(
        org_id=org.id,
        email="admin@rbac6.com",
        password_hash=PasswordHasher.hash("Pass12345!"),
        full_name="Admin",
        role="admin",
        is_active=True,
    )
    sales1 = User(
        org_id=org.id,
        email="sales1@rbac6.com",
        password_hash=PasswordHasher.hash("Pass12345!"),
        full_name="Sales One",
        role="sales_employee",
        is_active=True,
    )
    sales2 = User(
        org_id=org.id,
        email="sales2@rbac6.com",
        password_hash=PasswordHasher.hash("Pass12345!"),
        full_name="Sales Two",
        role="sales_employee",
        is_active=True,
    )
    db.add_all([admin, sales1, sales2])
    await db.flush()

    emp1 = Employee(org_id=org.id, user_id=sales1.id, title="Rep 1")
    emp2 = Employee(org_id=org.id, user_id=sales2.id, title="Rep 2")
    db.add_all([emp1, emp2])
    await db.flush()

    cust = Customer(org_id=org.id, phone_number="+15557778899", first_name="Target")
    db.add(cust)
    await db.flush()

    lead_emp1 = Lead(
        org_id=org.id,
        customer_id=cust.id,
        assigned_employee_id=emp1.id,
        title="Lead for Sales 1",
        status="new",
        qualification_tier="hot",
        score=80,
    )
    db.add(lead_emp1)
    await db.commit()

    admin_token = create_access_token(str(admin.id), str(org.id), admin.role, admin.email)
    s1_token = create_access_token(str(sales1.id), str(org.id), sales1.role, sales1.email)
    s2_token = create_access_token(str(sales2.id), str(org.id), sales2.role, sales2.email)

    return admin_token, s1_token, s2_token, lead_emp1.id, emp2.id


@pytest.mark.asyncio
async def test_sales_employee_cannot_access_unassigned_lead(client: AsyncClient, db_session: AsyncSession):
    _, s1_token, s2_token, lead1_id, _ = await create_scoped_environment(db_session)

    # Sales 1 can access their assigned lead
    res_s1 = await client.get(f"/api/v1/leads/{lead1_id}", headers={"Authorization": f"Bearer {s1_token}"})
    assert res_s1.status_code == 200

    # Sales 2 is forbidden from accessing Sales 1's lead
    res_s2 = await client.get(f"/api/v1/leads/{lead1_id}", headers={"Authorization": f"Bearer {s2_token}"})
    assert res_s2.status_code == 403

    # Sales 2 cannot update Sales 1's lead
    patch_s2 = await client.patch(
        f"/api/v1/leads/{lead1_id}",
        json={"notes": "Hacked note"},
        headers={"Authorization": f"Bearer {s2_token}"},
    )
    assert patch_s2.status_code == 403


@pytest.mark.asyncio
async def test_employee_management_requires_admin(client: AsyncClient, db_session: AsyncSession):
    admin_token, s1_token, _, _, _ = await create_scoped_environment(db_session)

    # Sales employee cannot list all employees
    res_s1 = await client.get("/api/v1/employees", headers={"Authorization": f"Bearer {s1_token}"})
    assert res_s1.status_code == 403

    # Admin can list employees
    res_admin = await client.get("/api/v1/employees", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_admin.status_code == 200
    assert res_admin.json()["total"] >= 2


@pytest.mark.asyncio
async def test_lead_assignment_requires_admin(client: AsyncClient, db_session: AsyncSession):
    admin_token, s1_token, _, lead1_id, emp2_id = await create_scoped_environment(db_session)

    # Sales employee cannot reassign leads
    res_s1 = await client.post(
        f"/api/v1/leads/{lead1_id}/assign",
        json={"employee_id": str(emp2_id)},
        headers={"Authorization": f"Bearer {s1_token}"},
    )
    assert res_s1.status_code == 403

    # Admin can assign leads
    res_admin = await client.post(
        f"/api/v1/leads/{lead1_id}/assign",
        json={"employee_id": str(emp2_id)},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_admin.status_code == 200
    assert res_admin.json()["assigned_employee_id"] == str(emp2_id)


@pytest.mark.asyncio
async def test_workspace_html_endpoints_served(client: AsyncClient):
    for path in ["/", "/admin-dashboard", "/receptionist-dashboard", "/sales-dashboard"]:
        res = await client.get(path)
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")
