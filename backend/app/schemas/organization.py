"""Organization Pydantic v2 schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class OrganizationResponse(BaseModel):
    """Organization tenant details."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    default_timezone: str
    is_active: bool
    created_at: datetime


class OrganizationUpdateRequest(BaseModel):
    """Payload for updating organization profile details."""

    name: Optional[str] = Field(None, min_length=2, max_length=255)
    default_timezone: Optional[str] = Field(None, min_length=2, max_length=50)
