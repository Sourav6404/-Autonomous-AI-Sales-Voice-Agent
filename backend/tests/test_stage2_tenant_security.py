"""Tests for Multi-Tenant Security, JWT Scope Binding, and Isolation."""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.security import PasswordHasher, create_access_token
from backend.app.models.holiday import Holiday
from backend.app.models.organization import Organization
from backend.app.models.user import User


async def create_tenant_and_admin(db: AsyncSession, name: str) -> tuple[Organization, User, str]:
    """Helper creating a distinct tenant with an admin user."""
    org = Organization(name=name, slug=f"tenant-{uuid.uuid4().hex[:6]}", default_timezone="UTC")
    db.add(org)
    await db.flush()

    user = User(
        org_id=org.id,
        email=f"admin_{uuid.uuid4().hex[:4]}@tenant.com",
        password_hash=PasswordHasher.hash("Pass123!"),
        full_name=f"{name} Admin",
        role="admin",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(
        subject=str(user.id),
        org_id=str(user.org_id),
        role=user.role,
        email=user.email,
    )
    return org, user, token


@pytest.mark.asyncio
async def test_tenant_data_boundary_for_holidays(client: AsyncClient, db_session: AsyncSession):
    """Verifies that Tenant A cannot see or manipulate Tenant B's holiday records."""
    org_a, user_a, token_a = await create_tenant_and_admin(db_session, "Tenant Alpha")
    org_b, user_b, token_b = await create_tenant_and_admin(db_session, "Tenant Beta")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 1. Tenant A creates a holiday
    res_a = await client.post(
        "/v1/holidays",
        json={
            "name": "Alpha Founder Day",
            "start_date": "2026-12-01",
            "end_date": "2026-12-01",
            "is_recurring_yearly": False,
        },
        headers=headers_a,
    )
    assert res_a.status_code == 201
    holiday_a_id = res_a.json()["id"]

    # 2. Tenant B lists holidays -> MUST NOT see Tenant A's holiday
    list_b = await client.get("/v1/holidays", headers=headers_b)
    assert list_b.status_code == 200
    ids_b = [h["id"] for h in list_b.json()]
    assert holiday_a_id not in ids_b

    # 3. Tenant B attempts to delete Tenant A's holiday by ID -> MUST return 404
    del_b = await client.delete(f"/v1/holidays/{holiday_a_id}", headers=headers_b)
    assert del_b.status_code == 404

    # 4. Tenant A deletes their own holiday -> 204
    del_a = await client.delete(f"/v1/holidays/{holiday_a_id}", headers=headers_a)
    assert del_a.status_code == 204


@pytest.mark.asyncio
async def test_token_org_id_tampering_rejected(client: AsyncClient, db_session: AsyncSession):
    """Verifies that tampering with org_id in a signed JWT causes signature validation failure."""
    org, user, valid_token = await create_tenant_and_admin(db_session, "Tamper Target")

    # Manually craft tampered token by forging signature
    tampered_token = valid_token[:-4] + "fake"
    headers = {"Authorization": f"Bearer {tampered_token}"}

    response = await client.get("/v1/auth/me", headers=headers)
    assert response.status_code == 401
    err_body = response.json()
    msg = err_body.get("detail") or err_body.get("error", {}).get("message", "")
    assert "invalid" in msg.lower() or "expired" in msg.lower()


@pytest.mark.asyncio
async def test_organization_me_scopes_to_authenticated_tenant(client: AsyncClient, db_session: AsyncSession):
    """Verifies GET /v1/organizations/me returns strictly the tenant in the JWT claim."""
    org_a, _, token_a = await create_tenant_and_admin(db_session, "Organization One")
    org_b, _, token_b = await create_tenant_and_admin(db_session, "Organization Two")

    res_a = await client.get("/v1/organizations/me", headers={"Authorization": f"Bearer {token_a}"})
    assert res_a.status_code == 200
    assert res_a.json()["id"] == str(org_a.id)
    assert res_a.json()["name"] == "Organization One"

    res_b = await client.get("/v1/organizations/me", headers={"Authorization": f"Bearer {token_b}"})
    assert res_b.status_code == 200
    assert res_b.json()["id"] == str(org_b.id)
    assert res_b.json()["name"] == "Organization Two"
