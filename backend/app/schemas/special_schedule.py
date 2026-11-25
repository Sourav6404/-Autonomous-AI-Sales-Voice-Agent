"""Special Schedules Pydantic v2 schemas."""

from datetime import date, time
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SpecialScheduleCreateRequest(BaseModel):
    """Payload to register an override date, split shift, or custom schedule."""

    schedule_date: date
    open_time: Optional[time] = None
    close_time: Optional[time] = None
    is_closed_all_day: bool = Field(False)
    reason: Optional[str] = Field(None, max_length=255)
    department_id: Optional[UUID] = None

    @model_validator(mode="after")
    def validate_times_and_status(self) -> "SpecialScheduleCreateRequest":
        if not self.is_closed_all_day:
            if self.open_time is None or self.close_time is None:
                raise ValueError("open_time and close_time are required when is_closed_all_day is False")
            if self.open_time >= self.close_time:
                raise ValueError("open_time must be strictly earlier than close_time")
        return self


class SpecialScheduleResponse(BaseModel):
    """Special schedule override response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    department_id: Optional[UUID] = None
    schedule_date: date
    open_time: Optional[time] = None
    close_time: Optional[time] = None
    is_closed_all_day: bool
    reason: Optional[str] = None
