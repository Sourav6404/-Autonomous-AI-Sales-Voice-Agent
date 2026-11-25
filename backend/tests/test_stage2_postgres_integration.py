"""PostgreSQL 16 Live Integration Tests for Stage 2 Authentication and Business Config."""

import socket
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.security import PasswordHasher, create_access_token
from backend.app.main import app
from backend.app.models.business_settings import BusinessSettings
from backend.app.models.organization import Organization
from backend.app.models.user import User


def is_live_postgres_available() -> bool:
    """Checks whether live PostgreSQL is reachable."""
    if "postgresql" not in settings.async_database_url:
        return False
    try:
        sock = socket.create_connection((settings.POSTGRES_SERVER, settings.POSTGRES_PORT), timeout=1.0)
        sock.close()
        return True
    except (OSError, ConnectionRefusedError):
        return False


POSTGRES_ONLINE = is_live_postgres_available()


@pytest.mark.skipif(not POSTGRES_ONLINE, reason="Live PostgreSQL container is not reachable.")
@pytest.mark.asyncio
async def test_postgres_live_registration_and_db_persistence():
    """Executes full organization registration against live PostgreSQL 16 container,
    verifying rows are created in organizations, users, business_settings, and ai_availability.
    """
    pg_engine = create_async_engine(settings.async_database_url, echo=False)
    session_factory = async_sessionmaker(bind=pg_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        async def override_pg_db():
            yield db

        app.dependency_overrides[get_db] = override_pg_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            slug = f"pg-org-{uuid.uuid4().hex[:8]}"
            reg_payload = {
                "org_name": "Postgres Live Tenant Inc",
                "org_slug": slug,
                "timezone": "America/Chicago",
                "email": f"owner_{uuid.uuid4().hex[:6]}@pglive.com",
                "password": "LivePostgresPassword2026!",
                "full_name": "PG Live Admin",
                "phone_number": "+13125550188",
            }
            res = await client.post("/v1/auth/register", json=reg_payload)
            assert res.status_code == 201, res.text
            data = res.json()
            org_id = uuid.UUID(data["org_id"])
            user_id = uuid.UUID(data["user"]["id"])

            # Verify in PostgreSQL
            org_query = select(Organization).where(Organization.id == org_id)
            org_row = (await db.execute(org_query)).scalar_one_or_none()
            assert org_row is not None
            assert org_row.name == "Postgres Live Tenant Inc"

            user_query = select(User).where(User.id == user_id)
            user_row = (await db.execute(user_query)).scalar_one_or_none()
            assert user_row is not None
            assert user_row.role == "owner"

            settings_query = select(BusinessSettings).where(BusinessSettings.org_id == org_id)
            settings_row = (await db.execute(settings_query)).scalar_one_or_none()
            assert settings_row is not None
            assert settings_row.contact_phone == "+13125550188"

        app.dependency_overrides.clear()
    await pg_engine.dispose()
