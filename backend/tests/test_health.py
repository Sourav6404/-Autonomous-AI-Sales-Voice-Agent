"""Tests for health and readiness check endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_liveness_probe(client: AsyncClient):
    """Tests GET /v1/health/live returns 200 OK."""
    response = await client.get("/v1/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "FortiSales AI"
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_readiness_probe_success(client: AsyncClient, monkeypatch):
    """Tests GET /v1/health/ready when database is healthy."""
    # Mock check_database_connection to return True
    import backend.app.api.v1.health as health_module

    async def mock_db_check():
        return True

    monkeypatch.setattr(health_module, "check_database_connection", mock_db_check)

    response = await client.get("/v1/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["services"]["database"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_readiness_probe_database_unavailable(client: AsyncClient, monkeypatch):
    """Tests GET /v1/health/ready returns 503 when database is unavailable."""
    import backend.app.api.v1.health as health_module

    async def mock_db_check_fail():
        return False

    monkeypatch.setattr(health_module, "check_database_connection", mock_db_check_fail)

    response = await client.get("/v1/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["services"]["database"]["status"] == "unhealthy"
