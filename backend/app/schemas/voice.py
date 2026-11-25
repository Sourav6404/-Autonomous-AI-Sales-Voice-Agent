"""Pydantic v2 schemas for voice session tickets, framing protocols, and control messages."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class VoiceTicketRequest(BaseModel):
    """Payload to request an ephemeral, single-use voice-session ticket."""

    conversation_id: Optional[UUID] = Field(
        None,
        description="Optional existing conversation session UUID to resume. If omitted, a new conversation and call are created.",
    )
    caller_phone: Optional[str] = Field(
        None,
        max_length=50,
        description="Optional verified caller phone number. If omitted, defaults to browser-voice identifier.",
    )
    language: str = Field(
        "en",
        min_length=2,
        max_length=10,
        description="Preferred spoken conversation language (e.g., 'en', 'es', 'fr').",
    )


class VoiceTicketResponse(BaseModel):
    """Response containing ephemeral single-use ticket for WebSocket authentication."""

    ticket: str = Field(..., description="Single-use, high-entropy ticket for WebSocket handshake")
    expires_in: int = Field(30, description="Ticket validity window in seconds")
    websocket_url: str = Field("/api/v1/voice/stream", description="Relative WebSocket stream path")


class TicketData(BaseModel):
    """Internal model for serialized ticket metadata stored in Redis or memory."""

    user_id: UUID
    org_id: UUID
    conversation_id: Optional[UUID] = None
    caller_phone: str = "browser-voice"
    language: str = "en"
    created_at: float
    used: bool = False


# ---------------------------------------------------------------------------
# WebSocket Control Message Schemas
# ---------------------------------------------------------------------------

class VoiceAuthMessage(BaseModel):
    """First-frame authentication payload."""

    type: Literal["auth"] = "auth"
    ticket: str = Field(..., min_length=16, max_length=256)


class VoiceStartMessage(BaseModel):
    """Client start-session control frame defining codec metadata and consent."""

    type: Literal["start"] = "start"
    codec: Literal["pcm16"] = "pcm16"
    sample_rate: int = Field(16000, description="Audio sampling rate in Hz")
    channels: int = Field(1, description="Audio channels (mono)")
    recording_consent: Optional[bool] = Field(
        None, description="Explicit caller consent to record and persist call audio."
    )


class VoiceInterruptMessage(BaseModel):
    """Client-signaled barge-in interruption."""

    type: Literal["interrupt"] = "interrupt"
    timestamp: Optional[datetime] = None


class VoiceMicStateMessage(BaseModel):
    """Client microphone mute state update."""

    type: Literal["set_mic_state"] = "set_mic_state"
    is_muted: bool


class VoiceEndSessionMessage(BaseModel):
    """Client clean hangup notification."""

    type: Literal["end_session"] = "end_session"
    reason: Optional[str] = "user_hangup"


class VoiceServerSessionCreated(BaseModel):
    """Server acknowledgment upon successful session instantiation."""

    type: Literal["session_created"] = "session_created"
    call_id: UUID
    conversation_id: UUID
    codec: str = "pcm16"
    sample_rate: int = 16000
    frame_bytes: int = 640
    resumed: bool = False


class VoiceServerSessionEnded(BaseModel):
    """Server notification when voice call terminates."""

    type: Literal["session_ended"] = "session_ended"
    call_id: UUID
    conversation_id: UUID
    duration_seconds: int
    status: str
    reason: str


class VoiceServerError(BaseModel):
    """Server error frame dispatched before abnormal connection termination."""

    type: Literal["error"] = "error"
    code: str
    message: str
