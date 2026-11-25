"""Tests for Stage 6 CRM API: Customers, Leads, Inquiries, and Conversation integration."""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.security import PasswordHasher, create_access_token
from backend.app.models.customer import Customer
from backend.app.models.employee import Employee
from backend.app.models.organization import Organization
from backend.app.models.user import User


async def setup_tenant_and_users(db: AsyncSession):
    org = Organization(
        name="CRM Test Org",
        slug=f"crm-org-{uuid.uuid4().hex[:6]}",
        default_timezone="UTC",
    )
    db.add(org)
    await db.flush()

    admin_user = User(
        org_id=org.id,
        email=f"admin_{uuid.uuid4().hex[:4]}@crm.com",
        password_hash=PasswordHasher.hash("Pass12345!"),
        full_name="CRM Admin",
        role="admin",
        is_active=True,
    )
    db.add(admin_user)

    sales_user = User(
        org_id=org.id,
        email=f"sales_{uuid.uuid4().hex[:4]}@crm.com",
        password_hash=PasswordHasher.hash("Pass12345!"),
        full_name="Sales Rep",
        role="sales_employee",
        is_active=True,
    )
    db.add(sales_user)
    await db.flush()

    sales_emp = Employee(
        org_id=org.id,
        user_id=sales_user.id,
        title="Account Executive",
    )
    db.add(sales_emp)
    await db.commit()
    await db.refresh(admin_user)
    await db.refresh(sales_user)
    await db.refresh(sales_emp)

    admin_token = create_access_token(
        subject=str(admin_user.id),
        org_id=str(org.id),
        role=admin_user.role,
        email=admin_user.email,
    )
    sales_token = create_access_token(
        subject=str(sales_user.id),
        org_id=str(org.id),
        role=sales_user.role,
        email=sales_user.email,
    )

    return org, admin_user, admin_token, sales_user, sales_emp, sales_token


@pytest.mark.asyncio
async def test_customer_crud_and_search(client: AsyncClient, db_session: AsyncSession):
    _, _, admin_token, _, _, _ = await setup_tenant_and_users(db_session)
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Create customer
    create_payload = {
        "phone_number": "+15551234567",
        "first_name": "Alice",
        "last_name": "Wonderland",
        "email": "alice@example.com",
        "company_name": "Acme Inc",
        "notes": "VIP client",
    }
    res = await client.post("/api/v1/customers", json=create_payload, headers=headers)
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["phone_number"] == "+15551234567"
    assert data["first_name"] == "Alice"
    cust_id = data["id"]

    # 2. Get customer
    res = await client.get(f"/api/v1/customers/{cust_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["email"] == "alice@example.com"

    # 3. Update customer
    res = await client.patch(
        f"/api/v1/customers/{cust_id}",
        json={"notes": "Updated VIP client note", "company_name": "Acme Global"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["notes"] == "Updated VIP client note"
    assert res.json()["company_name"] == "Acme Global"

    # 4. Search customer
    res = await client.get("/api/v1/customers?search=Alice", headers=headers)
    assert res.status_code == 200
    search_data = res.json()
    assert search_data["total"] >= 1
    assert any(c["id"] == cust_id for c in search_data["items"])


@pytest.mark.asyncio
async def test_lead_crud_and_assignment(client: AsyncClient, db_session: AsyncSession):
    _, _, admin_token, sales_user, sales_emp, sales_token = await setup_tenant_and_users(db_session)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    sales_headers = {"Authorization": f"Bearer {sales_token}"}

    # Create customer first
    cust_res = await client.post(
        "/api/v1/customers",
        json={"phone_number": "+15559876543", "first_name": "Bob"},
        headers=admin_headers,
    )
    assert cust_res.status_code == 201
    cust_id = cust_res.json()["id"]

    # 1. Create lead
    lead_payload = {
        "customer_id": cust_id,
        "title": "Enterprise Cloud Deal",
        "status": "new",
        "score": 75,
        "qualification_tier": "warm",
        "budget_range": "$50k-$100k",
        "decision_timeline": "Q2",
        "notes": "Needs multi-tenant security",
    }
    res = await client.post("/api/v1/leads", json=lead_payload, headers=admin_headers)
    assert res.status_code == 201, res.text
    lead_data = res.json()
    assert lead_data["score"] == 75
    assert lead_data["qualification_tier"] == "warm"
    lead_id = lead_data["id"]

    # 2. Assign lead to sales employee
    assign_res = await client.post(
        f"/api/v1/leads/{lead_id}/assign",
        json={"employee_id": str(sales_emp.id)},
        headers=admin_headers,
    )
    assert assign_res.status_code == 200
    assigned_data = assign_res.json()
    assert assigned_data["assigned_employee_id"] == str(sales_emp.id)

    # 3. Sales employee can view their assigned lead
    my_leads_res = await client.get("/api/v1/leads/my", headers=sales_headers)
    assert my_leads_res.status_code == 200
    my_leads = my_leads_res.json()
    assert my_leads["total"] == 1
    assert my_leads["items"][0]["id"] == lead_id

    # 4. Sales employee can update their assigned lead
    patch_res = await client.patch(
        f"/api/v1/leads/{lead_id}",
        json={"status": "qualified", "score": 90, "qualification_tier": "hot"},
        headers=sales_headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "qualified"
    assert patch_res.json()["score"] == 90
    assert patch_res.json()["qualification_tier"] == "hot"


@pytest.mark.asyncio
async def test_inquiry_lifecycle(client: AsyncClient, db_session: AsyncSession):
    _, _, admin_token, _, _, _ = await setup_tenant_and_users(db_session)
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Create customer
    cust_res = await client.post(
        "/api/v1/customers",
        json={"phone_number": "+15554443322", "first_name": "Charlie"},
        headers=headers,
    )
    cust_id = cust_res.json()["id"]

    # 1. Create inquiry
    inq_payload = {
        "customer_id": cust_id,
        "subject": "Billing issue on invoice #1042",
        "description": "Double charged for subscription",
        "priority": "high",
    }
    res = await client.post("/api/v1/inquiries", json=inq_payload, headers=headers)
    assert res.status_code == 201, res.text
    inq = res.json()
    assert inq["status"] == "open"
    assert inq["priority"] == "high"
    inq_id = inq["id"]

    # 2. List inquiries
    list_res = await client.get("/api/v1/inquiries?priority=high", headers=headers)
    assert list_res.status_code == 200
    assert list_res.json()["total"] >= 1

    # 3. Resolve inquiry
    res = await client.patch(
        f"/api/v1/inquiries/{inq_id}",
        json={"status": "resolved", "resolution_notes": "Issued credit note"},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "resolved"
    assert res.json()["resolved_at"] is not None


@pytest.mark.asyncio
async def test_conversation_auto_creates_customer_and_lead(client: AsyncClient, db_session: AsyncSession):
    _, _, admin_token, _, _, _ = await setup_tenant_and_users(db_session)
    headers = {"Authorization": f"Bearer {admin_token}"}

    caller_phone = "+15558889900"

    # 1. Start conversation with a phone number
    conv_res = await client.post(
        "/api/v1/conversations",
        json={"customer_phone": caller_phone, "language": "en"},
        headers=headers,
    )
    assert conv_res.status_code == 201, conv_res.text
    conv_id = conv_res.json()["id"]

    # Verify customer was auto-created
    cust_res = await client.get(f"/api/v1/customers?search={caller_phone}", headers=headers)
    assert cust_res.status_code == 200
    assert cust_res.json()["total"] == 1
    customer = cust_res.json()["items"][0]
    assert customer["phone_number"] == caller_phone
    assert customer["total_calls_count"] == 1

    # 2. End conversation
    end_res = await client.post(f"/api/v1/conversations/{conv_id}/end", headers=headers)
    assert end_res.status_code == 200

    # Verify lead was auto-created upon call completion
    leads_res = await client.get("/api/v1/leads", headers=headers)
    assert leads_res.status_code == 200
    leads = leads_res.json()["items"]
    matching_lead = next((l for l in leads if l["customer_id"] == customer["id"]), None)
    assert matching_lead is not None
    assert matching_lead["status"] == "new"
    assert caller_phone in matching_lead["title"]
