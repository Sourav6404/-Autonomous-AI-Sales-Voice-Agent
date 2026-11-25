"""Pydantic schemas for FortiSales AI Knowledge Base and RAG."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Company Info
# ---------------------------------------------------------------------------
class CompanyInfoResponse(BaseModel):
    """Company profile and overview information."""

    business_name: str
    industry: Optional[str] = None
    website: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    business_address: Optional[str] = None
    company_overview: Optional[str] = None
    business_description: Optional[str] = None
    business_services: Optional[str] = None
    additional_info: Optional[str] = None
    updated_at: Optional[datetime] = None


class CompanyInfoUpdateRequest(BaseModel):
    """Update payload for company profile."""

    business_name: Optional[str] = Field(None, max_length=255)
    industry: Optional[str] = Field(None, max_length=100)
    website: Optional[str] = Field(None, max_length=255)
    contact_phone: Optional[str] = Field(None, max_length=50)
    contact_email: Optional[str] = None
    business_address: Optional[str] = None
    company_overview: Optional[str] = None
    business_description: Optional[str] = None
    business_services: Optional[str] = None
    additional_info: Optional[str] = None


# ---------------------------------------------------------------------------
# Products & Services Catalogue
# ---------------------------------------------------------------------------
class ProductServiceBase(BaseModel):
    name: str = Field(..., max_length=255)
    description: str
    category: str = Field("General", max_length=100)
    features: Optional[str] = None
    benefits: Optional[str] = None
    price: Optional[Decimal] = None
    currency: str = Field("USD", max_length=10)
    pricing_type: str = Field("fixed", pattern="^(fixed|starting_from|quotation_required)$")
    is_available: bool = True
    specifications: Optional[str] = None


class ProductServiceCreateRequest(ProductServiceBase):
    pass


class ProductServiceUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)
    features: Optional[str] = None
    benefits: Optional[str] = None
    price: Optional[Decimal] = None
    currency: Optional[str] = Field(None, max_length=10)
    pricing_type: Optional[str] = Field(None, pattern="^(fixed|starting_from|quotation_required)$")
    is_available: Optional[bool] = None
    specifications: Optional[str] = None


class ProductServiceResponse(ProductServiceBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# FAQs
# ---------------------------------------------------------------------------
class FAQBase(BaseModel):
    question: str
    answer: str
    category: str = Field("General", max_length=100)
    is_active: bool = True


class FAQCreateRequest(FAQBase):
    pass


class FAQUpdateRequest(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None


class FAQResponse(FAQBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Business Policies
# ---------------------------------------------------------------------------
class BusinessPolicyBase(BaseModel):
    policy_type: str = Field(..., max_length=100)
    title: str = Field(..., max_length=255)
    content: str
    is_active: bool = True


class BusinessPolicyCreateRequest(BusinessPolicyBase):
    pass


class BusinessPolicyUpdateRequest(BaseModel):
    policy_type: Optional[str] = Field(None, max_length=100)
    title: Optional[str] = Field(None, max_length=255)
    content: Optional[str] = None
    is_active: Optional[bool] = None


class BusinessPolicyResponse(BusinessPolicyBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Documents & RAG Retrieval
# ---------------------------------------------------------------------------
class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    department_id: Optional[UUID] = None
    title: str
    document_type: str
    file_path: Optional[str] = None
    chunk_count: int
    is_active: bool
    created_at: datetime


class KnowledgeQueryRequest(BaseModel):
    query: str
    limit: int = Field(4, ge=1, le=20)
    score_threshold: float = Field(0.2, ge=0.0, le=1.0)
    document_types: Optional[List[str]] = None


class KnowledgeSearchResultItem(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_title: str
    document_type: str
    content: str
    score: float
    token_count: int


class KnowledgeQueryResponse(BaseModel):
    query: str
    count: int
    results: List[KnowledgeSearchResultItem]
