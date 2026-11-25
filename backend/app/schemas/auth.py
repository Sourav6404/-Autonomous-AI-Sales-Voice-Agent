"""Authentication and User Pydantic v2 schemas."""

import re
from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class RegisterRequest(BaseModel):
    """Payload for organization registration with initial owner account."""

    org_name: str = Field(..., min_length=2, max_length=255, description="Organization name")
    org_slug: Optional[str] = Field(None, min_length=2, max_length=100, description="Organization URL slug")
    timezone: str = Field("UTC", description="Default business timezone (e.g., 'America/New_York', 'UTC')")
    email: str = Field(..., min_length=5, max_length=255, description="Owner email address")
    password: str = Field(..., min_length=8, max_length=128, description="Strong account password (min 8 chars)")
    full_name: str = Field(..., min_length=2, max_length=255, description="Owner full name")
    phone_number: Optional[str] = Field(None, max_length=50, description="Owner contact telephone")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if not EMAIL_REGEX.match(clean):
            raise ValueError("Invalid email address format")
        return clean

    @field_validator("org_slug")
    @classmethod
    def validate_org_slug(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip().lower()
            if not re.match(r"^[a-z0-9-]+$", v):
                raise ValueError("Organization slug must contain only lowercase alphanumeric characters and hyphens")
        return v


class LoginRequest(BaseModel):
    """Payload for user authentication."""

    email: str = Field(..., min_length=5, description="Registered user email")
    password: str = Field(..., min_length=1, description="Account password")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if not EMAIL_REGEX.match(clean):
            raise ValueError("Invalid email address format")
        return clean


class TokenResponse(BaseModel):
    """Bearer access & refresh token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access token expiration window in seconds")


class UserResponse(BaseModel):
    """Sanitized user profile response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    email: str
    full_name: str
    role: str
    phone_number: Optional[str] = None
    is_active: bool
    created_at: datetime


class AuthResponse(BaseModel):
    """Combined registration or login response."""

    user: UserResponse
    org_id: UUID
    org_name: str
    tokens: TokenResponse
