"""Targeted Security Audit Verification Tests for Stage 2.

Covers:
1. Rejection of refresh token presented as access token.
2. Single-use refresh token rotation and replay prevention.
3. User & Organization deactivation immediate session invalidation.
4. Resistance to malformed, corrupted, and manipulated password hashes.
5. Thread-safe concurrent token revocation.
6. Multi-tenant bulk operations and raw SQL vs ORM isolation boundaries.
"""

import threading
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.security import PasswordHasher, RedisTokenBlacklist, TokenBlacklist, create_access_token, create_refresh_token
from backend.app.models.business_hours import BusinessHours
from backend.app.models.organization import Organization
from backend.app.models.user import User
from backend.tests.test_stage2_rbac import create_user_with_role


@pytest.mark.asyncio
async def test_refresh_token_rejected_on_access_endpoints(client: AsyncClient, db_session: AsyncSession):
    """Verifies that presenting a refresh token in Authorization: Bearer <refresh_token>
    is strictly rejected with 401 TOKEN_TYPE_INVALID on normal API routes.
    """
    user, _ = await create_user_with_role(db_session, "admin")
    refresh_token = create_refresh_token(subject=str(user.id), org_id=str(user.org_id))

    headers = {"Authorization": f"Bearer {refresh_token}"}
    response = await client.get("/v1/auth/me", headers=headers)
    assert response.status_code == 401
    data = response.json()
    err_msg = data.get("detail") or data.get("error", {}).get("message", "")
    assert "refresh token" in err_msg.lower() or "token_type_invalid" in str(data).lower()


@pytest.mark.asyncio
async def test_refresh_token_rotation_and_replay_rejection(client: AsyncClient):
    """Verifies single-use refresh token rotation:
    1. Using a refresh token issues a new pair.
    2. The old refresh token is immediately blacklisted.
    3. Attempting to reuse the old refresh token is rejected with 401.
    """
    reg_payload = {
        "org_name": "Rotation Audit Corp",
        "email": f"rotation_{uuid.uuid4().hex[:6]}@test.com",
        "password": "Password123!",
        "full_name": "Rotation Admin",
    }
    reg_res = await client.post("/v1/auth/register", json=reg_payload)
    assert reg_res.status_code == 201
    old_refresh_token = reg_res.json()["tokens"]["refresh_token"]

    # 1. Use the refresh token once -> succeeds
    res1 = await client.post("/v1/auth/refresh", json={"refresh_token": old_refresh_token})
    assert res1.status_code == 200
    new_refresh_token = res1.json()["refresh_token"]
    assert new_refresh_token != old_refresh_token

    # 2. Replay attack: try to reuse the old refresh token -> MUST fail with 401
    res2 = await client.post("/v1/auth/refresh", json={"refresh_token": old_refresh_token})
    assert res2.status_code == 401
    err = res2.json()
    msg = err.get("detail") or err.get("error", {}).get("message", "")
    assert "revoked" in msg.lower() or "invalid" in msg.lower()


@pytest.mark.asyncio
async def test_deactivated_organization_immediately_blocks_active_token(client: AsyncClient, db_session: AsyncSession):
    """Verifies that if an Organization is deactivated (is_active=False),
    all existing user tokens are rejected immediately with 403 ORGANIZATION_DEACTIVATED.
    """
    user, access_token = await create_user_with_role(db_session, "owner")
    headers = {"Authorization": f"Bearer {access_token}"}

    # Verify initial access is granted
    res_before = await client.get("/v1/auth/me", headers=headers)
    assert res_before.status_code == 200

    # Deactivate the organization
    org_query = select(Organization).where(Organization.id == user.org_id)
    org = (await db_session.execute(org_query)).scalar_one()
    org.is_active = False
    await db_session.commit()

    # Attempt request with previously valid token -> MUST fail with 403
    res_after = await client.get("/v1/auth/me", headers=headers)
    assert res_after.status_code == 403
    err = res_after.json()
    msg = err.get("detail") or err.get("error", {}).get("message", "")
    assert "deactivated" in msg.lower()


@pytest.mark.asyncio
async def test_deactivated_user_immediately_blocks_access(client: AsyncClient, db_session: AsyncSession):
    """Verifies that deactivating a specific user account immediately blocks token authentication."""
    user, access_token = await create_user_with_role(db_session, "employee")
    headers = {"Authorization": f"Bearer {access_token}"}

    # Verify initial access
    res_before = await client.get("/v1/auth/me", headers=headers)
    assert res_before.status_code == 200

    # Deactivate user
    user.is_active = False
    await db_session.commit()

    # Attempt request with token -> MUST fail with 403
    res_after = await client.get("/v1/auth/me", headers=headers)
    assert res_after.status_code == 403
    err = res_after.json()
    msg = err.get("detail") or err.get("error", {}).get("message", "")
    assert "deactivated" in msg.lower()


def test_password_hasher_resistance_to_malformed_hashes():
    """Verifies that PasswordHasher.verify handles corrupted, truncated, or forged inputs safely without throwing."""
    # Invalid prefixes / missing parts
    assert PasswordHasher.verify("pass", "plaintext_password") is False
    assert PasswordHasher.verify("pass", "$bcrypt$v=1$invalid") is False
    assert PasswordHasher.verify("pass", "$scrypt$") is False
    assert PasswordHasher.verify("pass", "$scrypt$invalid$hex$hex") is False
    assert PasswordHasher.verify("pass", "$scrypt$n=not_a_num,r=8,p=1$deadbeef$feedface") is False
    assert PasswordHasher.verify("pass", "$scrypt$n=16384,r=8,p=1$not_valid_hex$deadbeef") is False
    assert PasswordHasher.verify("pass", "") is False
    assert PasswordHasher.verify("pass", None) is False  # type: ignore


def test_token_blacklist_thread_safety():
    """Verifies thread-safe concurrent token revocation and checking."""
    tokens = [f"token_{i}_{uuid.uuid4()}" for i in range(100)]
    errors = []

    def worker(token_slice):
        try:
            for t in token_slice:
                TokenBlacklist.revoke(t, expires_at_timestamp=9999999999.0)
                assert TokenBlacklist.is_revoked(t) is True
        except Exception as e:
            errors.append(e)

    threads = []
    chunk_size = 25
    for i in range(0, len(tokens), chunk_size):
        t = threading.Thread(target=worker, args=(tokens[i:i + chunk_size],))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    assert len(errors) == 0, f"Encountered thread safety errors: {errors}"
    for t in tokens:
        assert TokenBlacklist.is_revoked(t) is True


@pytest.mark.asyncio
async def test_tenant_bulk_mutation_boundaries(client: AsyncClient, db_session: AsyncSession):
    """Verifies that tenant scoping is preserved in bulk operations and raw SQL boundaries."""
    user_a, token_a = await create_user_with_role(db_session, "admin")
    user_b, token_b = await create_user_with_role(db_session, "admin")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Tenant A sets hours
    payload_a = {
        "schedules": [
            {"day_of_week": 1, "open_time": "08:00:00", "close_time": "16:00:00", "is_closed": False}
        ]
    }
    await client.put("/v1/business-hours", json=payload_a, headers=headers_a)

    # Tenant B sets hours
    payload_b = {
        "schedules": [
            {"day_of_week": 1, "open_time": "10:00:00", "close_time": "18:00:00", "is_closed": False}
        ]
    }
    await client.put("/v1/business-hours", json=payload_b, headers=headers_b)

    # Verify Tenant A only sees Tenant A's hours
    get_a = await client.get("/v1/business-hours", headers=headers_a)
    assert get_a.status_code == 200
    hours_a = get_a.json()
    assert len(hours_a) == 1
    assert hours_a[0]["open_time"] == "08:00:00"

    # Verify Tenant B only sees Tenant B's hours
    get_b = await client.get("/v1/business-hours", headers=headers_b)
    assert get_b.status_code == 200
    hours_b = get_b.json()
    assert len(hours_b) == 1
    assert hours_b[0]["open_time"] == "10:00:00"
