"""Tests for Business Profile, Hours, Holidays, and Special Schedules Configuration."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.tests.test_stage2_rbac import create_user_with_role


@pytest.mark.asyncio
async def test_business_profile_and_telephony_settings(client: AsyncClient, db_session: AsyncSession):
    """Tests updating and retrieving organization business profile & receptionist telephony configuration."""
    user, token = await create_user_with_role(db_session, "admin")
    headers = {"Authorization": f"Bearer {token}"}

    # Update profile & telephony settings
    update_payload = {
        "primary_language": "es",
        "enable_multilingual": True,
        "voice_id": "sonic-spanish-2",
        "after_hours_behavior": "forward_to_number",
        "holiday_behavior": "custom_greeting",
        "max_call_duration_seconds": 600,
        "recording_consent_required": False,
        "contact_phone": "+1-800-555-0199",
        "contact_email": "support@enterprise.com",
        "business_address": "100 Tech Blvd, Suite 400, Austin TX 78701",
        "business_description": "Enterprise cloud security and AI receptionist solutions.",
        "business_services": "Voice receptionist, Appointment scheduling, Lead qualification",
    }
    patch_res = await client.patch("/v1/business-settings", json=update_payload, headers=headers)
    assert patch_res.status_code == 200, patch_res.text
    data = patch_res.json()
    assert data["primary_language"] == "es"
    assert data["voice_id"] == "sonic-spanish-2"
    assert data["after_hours_behavior"] == "forward_to_number"
    assert data["contact_phone"] == "+1-800-555-0199"
    assert data["contact_email"] == "support@enterprise.com"

    # Get settings
    get_res = await client.get("/v1/business-settings", headers=headers)
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["business_description"] == "Enterprise cloud security and AI receptionist solutions."


@pytest.mark.asyncio
async def test_business_hours_validation_open_before_close(client: AsyncClient, db_session: AsyncSession):
    """Tests that setting open_time >= close_time is rejected with 422 Unprocessable Entity."""
    user, token = await create_user_with_role(db_session, "admin")
    headers = {"Authorization": f"Bearer {token}"}

    # Invalid: open at 17:00, close at 09:00
    invalid_payload = {
        "schedules": [
            {
                "day_of_week": 1,
                "open_time": "17:00:00",
                "close_time": "09:00:00",
                "is_closed": False,
            }
        ]
    }
    response = await client.put("/v1/business-hours", json=invalid_payload, headers=headers)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_business_hours_bulk_replace_and_get(client: AsyncClient, db_session: AsyncSession):
    """Tests bulk replacement of weekly operating hours."""
    user, token = await create_user_with_role(db_session, "admin")
    headers = {"Authorization": f"Bearer {token}"}

    valid_payload = {
        "schedules": [
            {"day_of_week": 1, "open_time": "09:00:00", "close_time": "17:00:00", "is_closed": False},
            {"day_of_week": 2, "open_time": "09:00:00", "close_time": "17:00:00", "is_closed": False},
            {"day_of_week": 0, "open_time": "00:00:00", "close_time": "23:59:59", "is_closed": True},
        ]
    }
    put_res = await client.put("/v1/business-hours", json=valid_payload, headers=headers)
    assert put_res.status_code == 200
    hours = put_res.json()
    assert len(hours) == 3

    # Fetch
    get_res = await client.get("/v1/business-hours", headers=headers)
    assert get_res.status_code == 200
    assert len(get_res.json()) == 3


@pytest.mark.asyncio
async def test_special_schedules_date_override(client: AsyncClient, db_session: AsyncSession):
    """Tests creating, fetching, and deleting special schedules (date overrides)."""
    user, token = await create_user_with_role(db_session, "admin")
    headers = {"Authorization": f"Bearer {token}"}

    create_payload = {
        "schedule_date": "2026-12-24",
        "open_time": "09:00:00",
        "close_time": "13:00:00",
        "is_closed_all_day": False,
        "reason": "Christmas Eve Half Day",
    }
    post_res = await client.post("/v1/special-schedules", json=create_payload, headers=headers)
    assert post_res.status_code == 201
    data = post_res.json()
    assert data["reason"] == "Christmas Eve Half Day"
    schedule_id = data["id"]

    # List
    list_res = await client.get("/v1/special-schedules", headers=headers)
    assert list_res.status_code == 200
    assert any(s["id"] == schedule_id for s in list_res.json())

    # Delete
    del_res = await client.delete(f"/v1/special-schedules/{schedule_id}", headers=headers)
    assert del_res.status_code == 204
