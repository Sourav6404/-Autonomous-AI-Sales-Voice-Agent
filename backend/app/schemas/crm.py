"""Stage 6 Pydantic schemas for CRM: customers, leads, inquiries, employees, dashboard."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------------------------------------------------------------------------
# Customer schemas
# ---------------------------------------------------------------------------

class CustomerBase(BaseModel):
    phone_number: str = Field(..., max_length=50)
    email: Optional[str] = Field(None, max_length=255)
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    company_name: Optional[str] = Field(None, max_length=150)
    notes: Optional[str] = None
    source: Optional[str] = Field(None, max_length=100)
    tags: Optional[str] = None


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    email: Optional[str] = Field(None, max_length=255)
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    company_name: Optional[str] = Field(None, max_length=150)
    notes: Optional[str] = None
    source: Optional[str] = Field(None, max_length=100)
    tags: Optional[str] = None


class CustomerResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    phone_number: str
    email: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    company_name: Optional[str]
    total_calls_count: int
    last_called_at: Optional[datetime]
    notes: Optional[str]
    source: Optional[str]
    tags: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CustomerListResponse(BaseModel):
    items: List[CustomerResponse]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Lead schemas
# ---------------------------------------------------------------------------

class LeadBase(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    status: str = Field("new", max_length=50)
    score: int = Field(0, ge=0, le=100)
    qualification_tier: str = Field("cold", max_length=20)
    budget_range: Optional[str] = Field(None, max_length=100)
    decision_timeline: Optional[str] = Field(None, max_length=100)
    authority_confirmed: bool = False
    extracted_needs: Optional[str] = None
    notes: Optional[str] = None
    priority: Optional[str] = Field("medium", max_length=20)
    qualification_notes: Optional[str] = None


class LeadCreate(LeadBase):
    customer_id: uuid.UUID
    originating_call_id: Optional[uuid.UUID] = None


class LeadUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    status: Optional[str] = Field(None, max_length=50)
    score: Optional[int] = Field(None, ge=0, le=100)
    qualification_tier: Optional[str] = Field(None, max_length=20)
    budget_range: Optional[str] = Field(None, max_length=100)
    decision_timeline: Optional[str] = Field(None, max_length=100)
    authority_confirmed: Optional[bool] = None
    extracted_needs: Optional[str] = None
    notes: Optional[str] = None
    priority: Optional[str] = Field(None, max_length=20)
    qualification_notes: Optional[str] = None


class LeadAssignRequest(BaseModel):
    employee_id: uuid.UUID


class LeadResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    customer_id: uuid.UUID
    originating_call_id: Optional[uuid.UUID]
    assigned_employee_id: Optional[uuid.UUID]
    title: Optional[str]
    status: str
    score: int
    qualification_tier: str
    budget_range: Optional[str]
    decision_timeline: Optional[str]
    authority_confirmed: bool
    extracted_needs: Optional[str]
    notes: Optional[str]
    priority: Optional[str]
    qualification_notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    customer: Optional[CustomerResponse] = None

    model_config = ConfigDict(from_attributes=True)


class LeadListResponse(BaseModel):
    items: List[LeadResponse]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Inquiry schemas
# ---------------------------------------------------------------------------

class InquiryCreate(BaseModel):
    customer_id: uuid.UUID
    originating_call_id: Optional[uuid.UUID] = None
    subject: str = Field(..., max_length=255)
    description: Optional[str] = None
    priority: str = Field("medium", max_length=20)


class InquiryUpdate(BaseModel):
    subject: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    status: Optional[str] = Field(None, max_length=50)
    priority: Optional[str] = Field(None, max_length=20)
    resolution_notes: Optional[str] = None
    assigned_employee_id: Optional[uuid.UUID] = None


class InquiryResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    customer_id: uuid.UUID
    originating_call_id: Optional[uuid.UUID]
    assigned_employee_id: Optional[uuid.UUID]
    subject: str
    description: Optional[str]
    status: str
    priority: str
    resolution_notes: Optional[str]
    resolved_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    customer: Optional[CustomerResponse] = None

    model_config = ConfigDict(from_attributes=True)


class InquiryListResponse(BaseModel):
    items: List[InquiryResponse]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Employee management schemas
# ---------------------------------------------------------------------------

class EmployeeUserCreate(BaseModel):
    email: str = Field(..., max_length=255)
    full_name: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8)
    role: str = Field("sales_employee", max_length=50)
    phone_number: Optional[str] = Field(None, max_length=50)
    title: Optional[str] = Field(None, max_length=100)
    department_id: Optional[uuid.UUID] = None


class EmployeeUserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, max_length=255)
    phone_number: Optional[str] = Field(None, max_length=50)
    role: Optional[str] = Field(None, max_length=50)
    is_active: Optional[bool] = None
    title: Optional[str] = Field(None, max_length=100)
    department_id: Optional[uuid.UUID] = None
    is_available_for_takeover: Optional[bool] = None
    is_available_for_booking: Optional[bool] = None


class EmployeeResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    org_id: uuid.UUID
    title: Optional[str]
    department_id: Optional[uuid.UUID]
    is_available_for_takeover: bool
    is_available_for_booking: bool
    created_at: datetime

    # From user
    email: str
    full_name: str
    role: str
    phone_number: Optional[str]
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class EmployeeListResponse(BaseModel):
    items: List[EmployeeResponse]
    total: int


# ---------------------------------------------------------------------------
# Dashboard stats schemas
# ---------------------------------------------------------------------------

class AdminDashboardStats(BaseModel):
    total_customers: int
    total_calls_today: int
    total_calls_all_time: int
    total_leads: int
    open_leads: int
    total_inquiries: int
    open_inquiries: int
    total_employees: int
    total_sales_employees: int
    total_receptionists: int


class ReceptionistDashboardStats(BaseModel):
    calls_today: int
    calls_this_week: int
    new_customers_today: int
    open_inquiries: int
    new_leads_today: int
    recent_calls: List[Dict[str, Any]]


class SalesDashboardStats(BaseModel):
    my_leads_total: int
    my_leads_new: int
    my_leads_contacted: int
    my_leads_qualified: int
    my_leads_converted: int
    my_open_tasks: int
    recent_leads: List[Dict[str, Any]]
