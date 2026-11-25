"""Stage 7 Pydantic schemas for Appointment and Calendar Management."""

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class AppointmentSlot(BaseModel):
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    employee_id: uuid.UUID
    employee_name: str
    available: bool


class AppointmentAvailabilityResponse(BaseModel):
    date: date
    timezone: str
    business_open: bool
    reason: Optional[str] = None
    slots: List[AppointmentSlot]


class AppointmentCreate(BaseModel):
    customer_id: uuid.UUID
    employee_id: Optional[uuid.UUID] = None
    lead_id: Optional[uuid.UUID] = None
    start_time: datetime
    end_time: datetime
    meeting_type: str = Field("Sales Discovery Call", max_length=100)
    title: Optional[str] = Field(None, max_length=255)
    purpose: Optional[str] = None
    meeting_link_or_phone: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None
    booking_source: str = Field("manual", max_length=50)


class AppointmentReschedule(BaseModel):
    new_start_time: datetime
    new_end_time: datetime
    reason: Optional[str] = None


class AppointmentCancel(BaseModel):
    reason: str = Field(..., min_length=2, max_length=500)


class AppointmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    customer_id: uuid.UUID
    employee_id: uuid.UUID
    lead_id: Optional[uuid.UUID] = None
    originating_call_id: Optional[uuid.UUID] = None
    created_by_user_id: Optional[uuid.UUID] = None
    title: Optional[str]
    purpose: Optional[str]
    start_time: datetime
    end_time: datetime
    timezone: str
    status: str
    booking_source: str
    meeting_type: str
    meeting_link_or_phone: Optional[str]
    calendar_event_id: Optional[str]
    cancellation_reason: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    # Nested info
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    employee_name: Optional[str] = None


class AppointmentListResponse(BaseModel):
    items: List[AppointmentResponse]
    total: int
    page: int
    page_size: int


class AppointmentStatsResponse(BaseModel):
    total_appointments: int
    upcoming_appointments: int
    completed_appointments: int
    cancelled_appointments: int
    today_appointments: int
