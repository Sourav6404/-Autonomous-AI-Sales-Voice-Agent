"""FortiSales AI Configuration Specification.

Loads and validates system configuration via Pydantic Settings.
"""

from typing import List, Literal, Optional
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application and infrastructure settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "FortiSales AI"
    APP_ENV: Literal["development", "testing", "staging", "production"] = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/v1"
    SECRET_KEY: str = Field(
        default="fortisales_default_dev_secret_key_change_in_production_32b",
        min_length=16,
        description="Secret key for JWT and cryptographic operations",
    )

    # JWT & Authentication Settings
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS Settings
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    # PostgreSQL Database
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "fortisales_user"
    POSTGRES_PASSWORD: str = "fortisales_secure_dev_pw"
    POSTGRES_DB: str = "fortisales_db"

    # Explicit URLs (Optional overrides)
    DATABASE_URL: Optional[str] = None
    SYNC_DATABASE_URL: Optional[str] = None

    # Connection Pool Settings
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_ECHO: bool = False

    # Structured Logging
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    LOG_FORMAT: Literal["json", "text"] = "json"

    # Redis Settings
    REDIS_URL: Optional[str] = None

    # Voice Engine Settings (Stage 4)
    VOICE_TICKET_EXPIRE_SECONDS: int = 30
    VOICE_RECOVERY_TIMEOUT_SECONDS: int = 30
    MAX_VOICE_SESSIONS_PER_TENANT: int = 25
    VOICE_FRAME_BYTES: int = 640  # 20ms of 16kHz 16-bit mono PCM (320 samples * 2 bytes)
    VOICE_MAX_BUFFER_FRAMES: int = 250  # 5 seconds of audio buffer maximum

    # AI & LLM Provider Configuration
    DEFAULT_AI_PROVIDER: Literal["openai", "gemini"] = "openai"
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-1.5-flash"
    AI_REQUEST_TIMEOUT_SECONDS: float = 30.0
    AI_MAX_RETRIES: int = 2
    CONVERSATION_HISTORY_LIMIT: int = 15
    CONVERSATION_SUMMARY_THRESHOLD: int = 20

    @property
    def async_database_url(self) -> str:
        """Returns the asynchronous PostgreSQL connection URL."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@"
            f"{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def sync_database_url_str(self) -> str:
        """Returns the synchronous PostgreSQL connection URL for Alembic migrations."""
        if self.SYNC_DATABASE_URL:
            return self.SYNC_DATABASE_URL
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@"
            f"{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @field_validator("POSTGRES_PORT")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"Port must be between 1 and 65535, got {v}")
        return v

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        """Ensures default insecure credentials are never deployed in production."""
        if self.APP_ENV == "production":
            if self.SECRET_KEY == "fortisales_default_dev_secret_key_change_in_production_32b":
                raise ValueError("Insecure default SECRET_KEY must be changed in production.")
            if self.POSTGRES_PASSWORD == "fortisales_secure_dev_pw":
                raise ValueError("Insecure default POSTGRES_PASSWORD must be changed in production.")
        return self


# Cached global settings instance
settings = Settings()
