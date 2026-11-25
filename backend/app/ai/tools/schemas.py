"""Pydantic schemas for AI function calling arguments and results."""

from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class GetBusinessInformationInput(BaseModel):
    """Query parameter to retrieve organization details and services."""

    category: Optional[str] = Field(None, description="Optional service category filter (e.g. 'services', 'contact', 'general')")


class BusinessInformationOutput(BaseModel):
    """Structured business profile response."""

    name: str
    description: Optional[str] = None
    services: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    address: Optional[str] = None
    timezone: str


class GetBusinessHoursInput(BaseModel):
    """Optional parameters for operating hours lookup."""

    day_of_week: Optional[int] = Field(None, ge=0, le=6, description="0=Sunday, 1=Monday ... 6=Saturday")


class WeekdayHourDetail(BaseModel):
    day: str
    day_number: int
    open_time: str
    close_time: str
    is_closed: bool


class BusinessHoursOutput(BaseModel):
    timezone: str
    schedules: List[WeekdayHourDetail]


class GetAIAvailabilityInput(BaseModel):
    """Input for real-time operating status inquiry."""

    department_id: Optional[UUID] = None


class AIAvailabilityOutput(BaseModel):
    business_status: str
    ai_status: str
    reason: str
    current_time: str
    timezone: str
    next_status_change: Optional[str] = None


class RequestHumanHandoffInput(BaseModel):
    """Input to signal an escalation to a human representative."""

    reason: str = Field(..., min_length=2, max_length=255, description="Brief explanation why customer requests human assistance")
    urgency: str = Field("medium", pattern="^(low|medium|high|critical)$", description="Customer urgency level")
    customer_callback_phone: Optional[str] = Field(None, description="Best telephone number to reach customer")


class HumanHandoffOutput(BaseModel):
    handoff_status: str
    message: str
    ticket_reference: str


# ---------------------------------------------------------------------------
# Stage 5: Knowledge Base & RAG Tools
# ---------------------------------------------------------------------------
class QueryKnowledgeBaseInput(BaseModel):
    """Input for semantic knowledge base search."""

    query: str = Field(..., description="The search phrase or customer inquiry to search in business documents and knowledge base.")
    document_type: Optional[str] = Field(None, description="Optional document filter: 'faq', 'product_spec', 'policy', 'pricing', 'general'")


class QueryKnowledgeBaseOutput(BaseModel):
    """Retrieved knowledge chunks."""

    found: bool
    count: int
    chunks: List[Dict[str, Any]]
    summary: str


class GetProductOrServiceDetailsInput(BaseModel):
    """Input for product/service catalogue inquiry."""

    name: Optional[str] = Field(None, description="Exact or partial name of product or service.")
    category: Optional[str] = Field(None, description="Product or service category.")


class ProductOrServiceItem(BaseModel):
    name: str
    category: str
    description: str
    pricing_type: str  # 'fixed', 'starting_from', 'quotation_required'
    price: Optional[str] = None
    currency: str
    features: Optional[str] = None
    benefits: Optional[str] = None
    specifications: Optional[str] = None
    pricing_guidance: str


class ProductOrServiceDetailsOutput(BaseModel):
    found: bool
    count: int
    items: List[ProductOrServiceItem]


class GetBusinessPolicyInput(BaseModel):
    """Input to look up company rules and policies."""

    policy_type: str = Field(..., description="Type of policy: 'cancellation', 'refund', 'reschedule', 'payment', 'warranty', 'privacy', 'consultation_fee', 'booking_rules'")


class PolicyItem(BaseModel):
    policy_type: str
    title: str
    content: str


class BusinessPolicyOutput(BaseModel):
    found: bool
    policies: List[PolicyItem]


class GetFAQAnswerInput(BaseModel):
    """Input for frequently asked questions lookup."""

    query: str = Field(..., description="Specific question or topic customer is asking about.")
    category: Optional[str] = Field(None, description="FAQ category filter.")


class FAQItem(BaseModel):
    question: str
    answer: str
    category: str


class FAQAnswerOutput(BaseModel):
    found: bool
    count: int
    items: List[FAQItem]
