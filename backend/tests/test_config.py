"""Tests for configuration validation and environment settings."""

import pytest
from pydantic import ValidationError
from backend.app.core.config import Settings


def test_default_settings():
    """Tests default configuration parameters."""
    settings = Settings()
    assert settings.APP_NAME == "FortiSales AI"
    assert settings.POSTGRES_PORT == 5432
    assert "postgresql+asyncpg://" in settings.async_database_url
    assert "postgresql+psycopg2://" in settings.sync_database_url_str


def test_invalid_postgres_port():
    """Tests validation error when POSTGRES_PORT is out of range."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(POSTGRES_PORT=99999)
    assert "Port must be between 1 and 65535" in str(exc_info.value)


def test_invalid_short_secret_key():
    """Tests validation error when SECRET_KEY is too short."""
    with pytest.raises(ValidationError):
        Settings(SECRET_KEY="short")


def test_custom_database_url_override():
    """Tests explicitly provided DATABASE_URL override."""
    custom_url = "postgresql+asyncpg://user:pass@custom_host:5433/custom_db"
    settings = Settings(DATABASE_URL=custom_url)
    assert settings.async_database_url == custom_url


def test_production_environment_rejects_default_credentials():
    """Tests that deploying with default credentials in production raises validation error."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_ENV="production",
            SECRET_KEY="fortisales_default_dev_secret_key_change_in_production_32b",
            POSTGRES_PASSWORD="fortisales_secure_dev_pw",
        )
    assert "Insecure default SECRET_KEY must be changed in production" in str(exc_info.value)


def test_production_environment_valid_credentials():
    """Tests that production environment accepts strong custom credentials."""
    prod_settings = Settings(
        APP_ENV="production",
        SECRET_KEY="a_very_strong_custom_production_key_32bytes",
        POSTGRES_PASSWORD="strong_custom_prod_password_123",
    )
    assert prod_settings.APP_ENV == "production"
    assert prod_settings.SECRET_KEY == "a_very_strong_custom_production_key_32bytes"
