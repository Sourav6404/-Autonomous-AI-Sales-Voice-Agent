"""Business Settings Pydantic v2 schemas."""

import re
from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class BusinessSettingsResponse(BaseModel):
    """Organizational business and telephony settings response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    primary_language: str
    enable_multilingual: bool
    voice_id: str
    after_hours_behavior: str
    holiday_behavior: str
    max_call_duration_seconds: int
    recording_consent_required: bool
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    business_address: Optional[str] = None
    business_description: Optional[str] = None
    business_services: Optional[str] = None
    website: Optional[str] = Field(None, max_length=255)
    industry: Optional[str] = Field(None, max_length=100)
    company_overview: Optional[str] = None
    additional_info: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    company_overview: Optional[str] = None
    additional_info: Optional[str] = None
    updated_at: datetime


class BusinessSettingsUpdateRequest(BaseModel):
    """Payload to update business profile and receptionist settings."""

    primary_language: Optional[str] = Field(None, max_length=10)
    enable_multilingual: Optional[bool] = None
    voice_id: Optional[str] = Field(None, max_length=100)
    after_hours_behavior: Optional[str] = Field(
        None, pattern="^(ai_voicemail|forward_to_number|ai_general_info_only|reject)$"
    )
    holiday_behavior: Optional[str] = Field(None, max_length=50)
    max_call_duration_seconds: Optional[int] = Field(None, ge=60, le=7200)
    recording_consent_required: Optional[bool] = None
    contact_phone: Optional[str] = Field(None, max_length=50)
    contact_email: Optional[str] = None
    business_address: Optional[str] = None
    business_description: Optional[str] = None
    business_services: Optional[str] = None
    website: Optional[str] = Field(None, max_length=255)
    industry: Optional[str] = Field(None, max_length=100)
    company_overview: Optional[str] = None
    additional_info: Optional[str] = None

    @field_validator("contact_email")
    @classmethod
    def validate_contact_email(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip().lower()
            if not EMAIL_REGEX.match(clean):
                raise ValueError("Invalid contact email address format")
            return clean
        return v
