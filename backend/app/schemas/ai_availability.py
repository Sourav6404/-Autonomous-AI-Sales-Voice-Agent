"""AI Availability Pydantic v2 schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class AIAvailabilityStatusResponse(BaseModel):
    """Complete computed operational availability response for receptionist."""

    model_config = ConfigDict(from_attributes=True)

    org_id: UUID
    department_id: Optional[UUID] = None
    business_status: str = Field(..., description="'open' or 'closed'")
    ai_status: str = Field(..., description="'online', 'offline', 'maintenance', 'takeover_only'")
    reason: str = Field(..., description="Precedence resolution explanation")
    current_time: datetime = Field(..., description="Evaluated timestamp in tenant timezone")
    timezone: str = Field(..., description="Organization timezone")
    emergency_closure_active: bool
    emergency_reason: Optional[str] = None
    temp_offline_until: Optional[datetime] = None
    next_status_change_at: Optional[datetime] = None


class AIAvailabilityUpdateRequest(BaseModel):
    """Payload to update operational status or emergency closures."""

    status: Optional[str] = Field(None, pattern="^(online|offline|maintenance|takeover_only)$")
    emergency_closure_active: Optional[bool] = None
    emergency_reason: Optional[str] = None
    auto_schedule_enabled: Optional[bool] = None


class TempOfflineRequest(BaseModel):
    """Payload to set temporary offline mode for a duration."""

    duration_minutes: int = Field(..., ge=1, le=1440, description="Duration in minutes (1 to 1440)")
    reason: Optional[str] = Field("Temporary break", max_length=255)


class ScheduledStatusChangeRequest(BaseModel):
    """Payload to defer an availability status transition."""

    scheduled_status: str = Field(..., pattern="^(online|offline|maintenance|takeover_only)$")
    scheduled_status_change_at: datetime
