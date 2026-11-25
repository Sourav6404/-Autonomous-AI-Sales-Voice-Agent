"""Tests for Role-Based Access Control (RBAC) across endpoints."""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.security import PasswordHasher, create_access_token
from backend.app.models.organization import Organization
from backend.app.models.user import User


async def create_user_with_role(db: AsyncSession, role: str) -> tuple[User, str]:
    """Helper to create organization and user with a specified role, returning (user, token)."""
    org = Organization(
        name=f"RBAC Org {role}",
        slug=f"rbac-{role}-{uuid.uuid4().hex[:6]}",
        default_timezone="UTC",
    )
    db.add(org)
    await db.flush()

    user = User(
        org_id=org.id,
        email=f"{role}_{uuid.uuid4().hex[:4]}@rbac.com",
        password_hash=PasswordHasher.hash("Pass12345!"),
        full_name=f"{role.capitalize()} User",
        role=role,
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
    return user, token


@pytest.mark.asyncio
async def test_owner_and_admin_can_update_business_settings(client: AsyncClient, db_session: AsyncSession):
    """Verifies that OWNER and ADMIN roles have permission to modify business settings."""
    for role in ["owner", "admin"]:
        user, token = await create_user_with_role(db_session, role)
        headers = {"Authorization": f"Bearer {token}"}

        patch_res = await client.patch(
            "/v1/business-settings",
            json={"contact_phone": "+19998887777", "recording_consent_required": True},
            headers=headers,
        )
        assert patch_res.status_code == 200, f"Role {role} failed: {patch_res.text}"
        data = patch_res.json()
        assert data["contact_phone"] == "+19998887777"


@pytest.mark.asyncio
async def test_receptionist_forbidden_from_admin_settings(client: AsyncClient, db_session: AsyncSession):
    """Verifies that RECEPTIONIST cannot modify organization settings or business hours."""
    user, token = await create_user_with_role(db_session, "receptionist")
    headers = {"Authorization": f"Bearer {token}"}

    # Cannot update organization
    org_res = await client.patch("/v1/organizations/me", json={"name": "Hacked"}, headers=headers)
    assert org_res.status_code == 403

    # Cannot update business settings
    settings_res = await client.patch(
        "/v1/business-settings", json={"contact_phone": "+1234567890"}, headers=headers
    )
    assert settings_res.status_code == 403

    # Cannot update business hours
    hours_res = await client.put(
        "/v1/business-hours",
        json={"schedules": [{"day_of_week": 1, "open_time": "09:00:00", "close_time": "17:00:00", "is_closed": False}]},
        headers=headers,
    )
    assert hours_res.status_code == 403


@pytest.mark.asyncio
async def test_receptionist_allowed_for_ai_availability(client: AsyncClient, db_session: AsyncSession):
    """Verifies that RECEPTIONIST can update AI status and set temporary offline mode."""
    user, token = await create_user_with_role(db_session, "receptionist")
    headers = {"Authorization": f"Bearer {token}"}

    # Can read AI status
    status_res = await client.get("/v1/ai-availability/status", headers=headers)
    assert status_res.status_code == 200

    # Can set temp offline
    offline_res = await client.post(
        "/v1/ai-availability/temp-offline",
        json={"duration_minutes": 30, "reason": "Staff meeting"},
        headers=headers,
    )
    assert offline_res.status_code == 200
    assert offline_res.json()["business_status"] == "closed"


@pytest.mark.asyncio
async def test_employee_forbidden_from_ai_controls(client: AsyncClient, db_session: AsyncSession):
    """Verifies that ordinary EMPLOYEE cannot modify AI availability status."""
    user, token = await create_user_with_role(db_session, "employee")
    headers = {"Authorization": f"Bearer {token}"}

    # Attempt to toggle AI availability
    res = await client.patch(
        "/v1/ai-availability",
        json={"status": "offline"},
        headers=headers,
    )
    assert res.status_code == 403
    err_body = res.json()
    msg = err_body.get("detail") or err_body.get("error", {}).get("message", "")
    assert "access denied" in msg.lower() or "permission" in msg.lower()
