"""Business Hours Pydantic v2 schemas."""

from datetime import time
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class WeekdayHoursItem(BaseModel):
    """Schedule item for a specific day of the week."""

    day_of_week: int = Field(..., ge=0, le=6, description="0=Sunday, 1=Monday, ..., 6=Saturday")
    open_time: time = Field(..., description="Opening time (HH:MM:SS)")
    close_time: time = Field(..., description="Closing time (HH:MM:SS)")
    is_closed: bool = Field(False, description="Whether the business/dept is closed this day")
    department_id: Optional[UUID] = Field(None, description="Optional department UUID")

    @model_validator(mode="after")
    def validate_times(self) -> "WeekdayHoursItem":
        if not self.is_closed and self.open_time >= self.close_time:
            raise ValueError("open_time must be strictly earlier than close_time unless closed")
        return self


class BusinessHoursResponse(BaseModel):
    """Operating hours record response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    department_id: Optional[UUID] = None
    day_of_week: int
    open_time: time
    close_time: time
    is_closed: bool


class BusinessHoursBulkUpdateRequest(BaseModel):
    """Payload to batch replace weekly schedule."""

    schedules: List[WeekdayHoursItem] = Field(..., min_length=1, max_length=14)
