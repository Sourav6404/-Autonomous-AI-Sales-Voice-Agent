"""Pydantic v2 schemas for conversations, messages, and structured classification."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversationCreateRequest(BaseModel):
    """Payload to initiate a new isolated conversation session."""

    customer_phone: Optional[str] = Field("+10000000000", description="Caller/Customer telephone number")
    language: str = Field("en", min_length=2, max_length=10, description="Preferred conversation language")


class ConversationResponse(BaseModel):
    """Conversation session metadata."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    call_id: Optional[UUID] = None
    language: str
    status: str
    turn_count: int
    summary: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class MessageCreateRequest(BaseModel):
    """Customer dialogue turn input."""

    content: str = Field(..., min_length=1, max_length=4000, description="Customer spoken or typed transcript turn")

    @field_validator("content")
    @classmethod
    def validate_content_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Message content cannot be blank or whitespace only.")
        return stripped


class MessageResponse(BaseModel):
    """Individual dialogue turn output."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    turn_number: int
    speaker_role: str
    content: str
    sentiment: Optional[str] = None
    confidence_score: Optional[float] = None
    latency_ms: Optional[int] = None
    created_at: datetime


class CustomerIntentExtraction(BaseModel):
    """Structured intelligence extracted from conversation dialogue."""

    primary_intent: Optional[str] = Field(None, description="Inferred customer goal: 'inquiry', 'pricing', 'support', 'booking', 'complaint'")
    inquiry_category: Optional[str] = Field(None, description="Category of service or product discussed")
    service_interest: Optional[str] = Field(None, description="Specific service or offering customer expressed interest in")
    customer_name: Optional[str] = Field(None, description="Full or first name of customer if mentioned")
    contact_phone: Optional[str] = Field(None, description="Phone number supplied by caller")
    contact_email: Optional[str] = Field(None, description="Email address supplied by caller")
    budget_range: Optional[str] = Field(None, description="Budget or financial constraints mentioned")
    urgency: str = Field("medium", description="'low', 'medium', 'high', 'urgent'")
    sentiment: str = Field("neutral", description="'positive', 'neutral', 'negative', 'frustrated'")
    needs_human_intervention: bool = Field(False, description="Whether escalation to a human representative is warranted")
    confidence_score: float = Field(0.85, ge=0.0, le=1.0)


class OrchestrationTurnResponse(BaseModel):
    """Complete response returned after processing a customer message turn."""

    conversation_id: UUID
    turn_number: int
    customer_message: MessageResponse
    assistant_reply: MessageResponse
    tool_calls_executed: List[Dict[str, Any]] = Field(default_factory=list)
    extracted_intelligence: Optional[CustomerIntentExtraction] = None
    conversation_status: str


class HandoffItemResponse(BaseModel):
    """Details for a conversation session escalated to human staff."""

    conversation_id: UUID
    call_id: Optional[UUID] = None
    caller_phone_number: Optional[str] = None
    customer_id: Optional[UUID] = None
    customer_name: Optional[str] = None
    status: str
    turn_count: int
    summary: Optional[str] = None
    started_at: Optional[datetime] = None
    taken_over_by_employee_id: Optional[UUID] = None
    taken_over_by_name: Optional[str] = None
    notes: Optional[str] = None
    outcome: Optional[str] = None
    created_at: datetime


class HandoffTakeoverRequest(BaseModel):
    """Payload to take over a handed-off conversation session."""

    employee_id: Optional[UUID] = None
    notes: Optional[str] = None


class HandoffCreateRequest(BaseModel):
    """Explicit request to trigger a human handoff."""

    reason: str = Field(..., min_length=2, max_length=255, description="Reason for escalation")
    urgency: str = Field("medium", pattern="^(low|medium|high|critical|urgent)$", description="Urgency level")
    customer_callback_phone: Optional[str] = Field(None, description="Preferred callback phone number")
