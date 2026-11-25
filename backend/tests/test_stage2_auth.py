"""Tests for Stage 2 Authentication, Tokens, and Account Management."""

import pytest
from httpx import AsyncClient
from backend.app.core.security import PasswordHasher, TokenBlacklist, decode_token


@pytest.mark.asyncio
async def test_register_organization_and_owner_success(client: AsyncClient):
    """Tests successful registration of organization and owner user."""
    payload = {
        "org_name": "Apex AI Solutions",
        "org_slug": "apex-ai-solutions",
        "timezone": "America/New_York",
        "email": "owner@apexai.com",
        "password": "SecurePassword123!",
        "full_name": "Alice Apex",
        "phone_number": "+15551234567",
    }
    response = await client.post("/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()

    assert data["org_name"] == "Apex AI Solutions"
    assert "org_id" in data
    assert data["user"]["email"] == "owner@apexai.com"
    assert data["user"]["role"] == "owner"
    assert data["user"]["full_name"] == "Alice Apex"
    assert "tokens" in data
    assert "access_token" in data["tokens"]
    assert "refresh_token" in data["tokens"]
    assert data["tokens"]["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_duplicate_email_rejected(client: AsyncClient):
    """Tests that registering with an already existing email is rejected with 400."""
    payload = {
        "org_name": "Unique Corp",
        "org_slug": "unique-corp-1",
        "timezone": "UTC",
        "email": "dup@example.com",
        "password": "Password123!",
        "full_name": "First User",
    }
    res1 = await client.post("/v1/auth/register", json=payload)
    assert res1.status_code == 201

    payload2 = {
        "org_name": "Another Corp",
        "org_slug": "unique-corp-2",
        "timezone": "UTC",
        "email": "dup@example.com",
        "password": "Password456!",
        "full_name": "Second User",
    }
    res2 = await client.post("/v1/auth/register", json=payload2)
    assert res2.status_code == 400
    assert "already exists" in res2.json()["detail"]


@pytest.mark.asyncio
async def test_login_success_and_token_generation(client: AsyncClient):
    """Tests login with valid credentials returns access and refresh tokens."""
    # Register first
    reg_payload = {
        "org_name": "Login Test Corp",
        "org_slug": "login-test-corp",
        "timezone": "UTC",
        "email": "loginuser@testcorp.com",
        "password": "StrongPassword999!",
        "full_name": "Login User",
    }
    await client.post("/v1/auth/register", json=reg_payload)

    # Login
    login_payload = {
        "email": "loginuser@testcorp.com",
        "password": "StrongPassword999!",
    }
    response = await client.post("/v1/auth/login", json=login_payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data

    # Verify decoded claims
    decoded = decode_token(data["access_token"])
    assert decoded is not None
    assert decoded["email"] == "loginuser@testcorp.com"
    assert decoded["role"] == "owner"


@pytest.mark.asyncio
async def test_login_invalid_password_rejected(client: AsyncClient):
    """Tests login with wrong password returns 401 Unauthorized."""
    reg_payload = {
        "org_name": "Wrong Pass Corp",
        "email": "wrongpass@test.com",
        "password": "CorrectPassword123!",
        "full_name": "Pass User",
    }
    await client.post("/v1/auth/register", json=reg_payload)

    login_payload = {
        "email": "wrongpass@test.com",
        "password": "WrongPassword999!",
    }
    response = await client.post("/v1/auth/login", json=login_payload)
    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_current_user_profile_me(client: AsyncClient):
    """Tests GET /v1/auth/me with valid Bearer token."""
    reg_payload = {
        "org_name": "Profile Corp",
        "email": "me@profilecorp.com",
        "password": "PasswordProfile123!",
        "full_name": "Me User",
    }
    reg_res = await client.post("/v1/auth/register", json=reg_payload)
    token = reg_res.json()["tokens"]["access_token"]

    headers = {"Authorization": f"Bearer {token}"}
    response = await client.get("/v1/auth/me", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "me@profilecorp.com"
    assert data["full_name"] == "Me User"
    assert data["role"] == "owner"


@pytest.mark.asyncio
async def test_logout_revokes_token(client: AsyncClient):
    """Tests that logging out blacklists the token and prevents subsequent usage."""
    reg_payload = {
        "org_name": "Logout Corp",
        "email": "logout@test.com",
        "password": "PasswordLogout123!",
        "full_name": "Logout User",
    }
    reg_res = await client.post("/v1/auth/register", json=reg_payload)
    token = reg_res.json()["tokens"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Verify access works before logout
    res_before = await client.get("/v1/auth/me", headers=headers)
    assert res_before.status_code == 200

    # Call logout
    logout_res = await client.post("/v1/auth/logout", headers=headers)
    assert logout_res.status_code == 200

    # Call /me with the same token -> should fail 401
    res_after = await client.get("/v1/auth/me", headers=headers)
    assert res_after.status_code == 401
    err_body = res_after.json()
    msg = err_body.get("detail") or err_body.get("error", {}).get("message", "")
    assert "revoked" in msg.lower()


@pytest.mark.asyncio
async def test_refresh_token_flow(client: AsyncClient):
    """Tests exchanging a refresh token for new access and refresh tokens."""
    reg_payload = {
        "org_name": "Refresh Corp",
        "email": "refresh@test.com",
        "password": "PasswordRefresh123!",
        "full_name": "Refresh User",
    }
    reg_res = await client.post("/v1/auth/register", json=reg_payload)
    refresh_token = reg_res.json()["tokens"]["refresh_token"]

    response = await client.post("/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data

    # Verify newly issued access token works
    new_token = data["access_token"]
    headers = {"Authorization": f"Bearer {new_token}"}
    me_res = await client.get("/v1/auth/me", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "refresh@test.com"


def test_password_hasher_scrypt():
    """Validates Scrypt hashing and verification."""
    password = "SuperSecretPassword#2026"
    hashed = PasswordHasher.hash(password)
    assert hashed.startswith("$scrypt$")
    assert PasswordHasher.verify(password, hashed) is True
    assert PasswordHasher.verify("wrong_password", hashed) is False
