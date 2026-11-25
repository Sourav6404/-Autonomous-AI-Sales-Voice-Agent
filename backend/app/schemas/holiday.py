"""Holidays Pydantic v2 schemas."""

from datetime import date, datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class HolidayCreateRequest(BaseModel):
    """Payload to create a holiday or planned corporate closure."""

    name: str = Field(..., min_length=2, max_length=150)
    start_date: date
    end_date: date
    is_recurring_yearly: bool = Field(False)
    special_announcement: Optional[str] = Field(None, max_length=1000)

    @model_validator(mode="after")
    def validate_dates(self) -> "HolidayCreateRequest":
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class HolidayUpdateRequest(BaseModel):
    """Payload to modify an existing holiday."""

    name: Optional[str] = Field(None, min_length=2, max_length=150)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_recurring_yearly: Optional[bool] = None
    special_announcement: Optional[str] = Field(None, max_length=1000)

    @model_validator(mode="after")
    def validate_dates(self) -> "HolidayUpdateRequest":
        if self.start_date is not None and self.end_date is not None:
            if self.start_date > self.end_date:
                raise ValueError("start_date must be on or before end_date")
        return self


class HolidayResponse(BaseModel):
    """Holiday schedule record response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    name: str
    start_date: date
    end_date: date
    is_recurring_yearly: bool
    special_announcement: Optional[str] = None
    created_at: datetime
