"""Tests for Centralized AI Availability Precedence Resolution Engine."""

from datetime import datetime, timezone
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.tests.test_stage2_rbac import create_user_with_role


@pytest.mark.asyncio
async def test_precedence_regular_hours_vs_after_hours(client: AsyncClient, db_session: AsyncSession):
    """Tests that within business hours status is 'open', and outside hours status is 'closed' while AI remains 'online'."""
    user, token = await create_user_with_role(db_session, "admin")
    headers = {"Authorization": f"Bearer {token}"}

    # Set Monday (day_of_week=1) hours 09:00 - 17:00 UTC
    hours_payload = {
        "schedules": [
            {"day_of_week": 1, "open_time": "09:00:00", "close_time": "17:00:00", "is_closed": False}
        ]
    }
    await client.put("/v1/business-hours", json=hours_payload, headers=headers)

    # 1. Evaluate on Monday at 11:00 UTC (inside business hours)
    # 2026-11-23 was a Monday
    monday_open = "2026-11-23T11:00:00Z"
    res_open = await client.get(f"/v1/ai-availability/status?timestamp={monday_open}", headers=headers)
    assert res_open.status_code == 200
    data_open = res_open.json()
    assert data_open["business_status"] == "open"
    assert data_open["ai_status"] == "online"

    # 2. Evaluate on Monday at 20:00 UTC (after business hours)
    monday_closed = "2026-11-23T20:00:00Z"
    res_closed = await client.get(f"/v1/ai-availability/status?timestamp={monday_closed}", headers=headers)
    assert res_closed.status_code == 200
    data_closed = res_closed.json()
    assert data_closed["business_status"] == "closed"
    # By default, after_hours_behavior is ai_voicemail, so AI stays online!
    assert data_closed["ai_status"] == "online"
    assert "Closed after operating hours" in data_closed["reason"]


@pytest.mark.asyncio
async def test_precedence_holiday_overrides_business_hours(client: AsyncClient, db_session: AsyncSession):
    """Tests that a holiday closure overrides regular business hours."""
    user, token = await create_user_with_role(db_session, "admin")
    headers = {"Authorization": f"Bearer {token}"}

    # Set Monday hours
    hours_payload = {
        "schedules": [
            {"day_of_week": 1, "open_time": "09:00:00", "close_time": "17:00:00", "is_closed": False}
        ]
    }
    await client.put("/v1/business-hours", json=hours_payload, headers=headers)

    # Add holiday on Monday 2026-11-23
    await client.post(
        "/v1/holidays",
        json={
            "name": "Thanksgiving Monday",
            "start_date": "2026-11-23",
            "end_date": "2026-11-23",
            "is_recurring_yearly": False,
            "special_announcement": "Office closed for holiday",
        },
        headers=headers,
    )

    # Evaluate at 11:00 UTC on the holiday
    monday_time = "2026-11-23T11:00:00Z"
    res = await client.get(f"/v1/ai-availability/status?timestamp={monday_time}", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["business_status"] == "closed"
    assert "Office closed for holiday" in data["reason"]


@pytest.mark.asyncio
async def test_precedence_special_schedule_overrides_holiday(client: AsyncClient, db_session: AsyncSession):
    """Tests that a special schedule date override takes precedence over a holiday."""
    user, token = await create_user_with_role(db_session, "admin")
    headers = {"Authorization": f"Bearer {token}"}

    # Add holiday covering 2026-11-23
    await client.post(
        "/v1/holidays",
        json={
            "name": "Annual Meeting",
            "start_date": "2026-11-23",
            "end_date": "2026-11-23",
            "is_recurring_yearly": False,
        },
        headers=headers,
    )

    # Add special schedule opening half-day on 2026-11-23
    await client.post(
        "/v1/special-schedules",
        json={
            "schedule_date": "2026-11-23",
            "open_time": "10:00:00",
            "close_time": "14:00:00",
            "is_closed_all_day": False,
            "reason": "Special emergency customer support hours",
        },
        headers=headers,
    )

    # Evaluate at 11:00 UTC -> Special schedule makes business open!
    target_time = "2026-11-23T11:00:00Z"
    res = await client.get(f"/v1/ai-availability/status?timestamp={target_time}", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["business_status"] == "open"
    assert "Special emergency customer support hours" in data["reason"]


@pytest.mark.asyncio
async def test_precedence_emergency_closure_highest_priority(client: AsyncClient, db_session: AsyncSession):
    """Tests that emergency closure overrides everything and forces business closed and AI offline."""
    user, token = await create_user_with_role(db_session, "admin")
    headers = {"Authorization": f"Bearer {token}"}

    # Activate emergency closure
    patch_res = await client.patch(
        "/v1/ai-availability",
        json={"emergency_closure_active": True, "emergency_reason": "Severe Hurricane Warning"},
        headers=headers,
    )
    assert patch_res.status_code == 200

    # Evaluate status
    res = await client.get("/v1/ai-availability/status", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["business_status"] == "closed"
    assert data["ai_status"] == "offline"
    assert data["emergency_closure_active"] is True
    assert data["emergency_reason"] == "Severe Hurricane Warning"
