"""Voice Session Ticket Issuance & Streaming WebSocket Gateway.

Endpoints:
- POST /voice/tickets: Issues ephemeral single-use 256-bit tickets to authenticated staff.
- WebSocket /voice/stream: Authenticated real-time audio and control multiplexer.

Guarantees:
1. Derives user_id and org_id exclusively from cryptographically verified JWT claims.
2. Accepts authentication via first WebSocket frame (preferred) or query parameter.
3. Validates WebSocket Origin against configured CORS_ORIGINS.
4. Binds and guarantees cleanup of TenantContext across all exit paths.
5. PCM16 protocol: 16,000 Hz, mono, signed 16-bit LE, 20ms (640 bytes/frame).
6. Enforces bounded frame buffers and backpressure limits.
7. Distinguishes clean user hangup from unexpected disconnect with recovery.
"""

import asyncio
import json
import logging
from typing import Optional
from uuid import UUID
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_current_active_user
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.tenant import TenantContext
from backend.app.models.conversation import Conversation
from backend.app.models.user import User
from backend.app.schemas.voice import (
    VoiceAuthMessage,
    VoiceEndSessionMessage,
    VoiceInterruptMessage,
    VoiceMicStateMessage,
    VoiceServerError,
    VoiceServerSessionCreated,
    VoiceServerSessionEnded,
    VoiceStartMessage,
    VoiceTicketRequest,
    VoiceTicketResponse,
)
from backend.app.services.voice.session_manager import (
    VoiceSession,
    VoiceSessionManager,
    VoiceSessionState,
)
from backend.app.services.voice.ticket_service import VoiceTicketService
from backend.app.services.voice.pipeline import VoicePipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["Voice Engine"])


@router.post(
    "/tickets",
    response_model=VoiceTicketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue ephemeral single-use voice session ticket",
)
async def create_voice_ticket(
    payload: VoiceTicketRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> VoiceTicketResponse:
    """Issues an ephemeral, single-use 256-bit ticket bound to authenticated staff and tenant."""
    org_id = current_user.org_id

    # If conversation_id was specified, verify ownership before issuing ticket
    if payload.conversation_id:
        conv_stmt = select(Conversation).where(
            Conversation.id == payload.conversation_id,
            Conversation.org_id == org_id,
        )
        conv_res = await db.execute(conv_stmt)
        conv = conv_res.scalar_one_or_none()
        if not conv:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Conversation '{payload.conversation_id}' was not found for this organization.",
            )

    raw_ticket = await VoiceTicketService.create_ticket(
        user_id=current_user.id,
        org_id=org_id,
        conversation_id=payload.conversation_id,
        caller_phone=payload.caller_phone,
        language=payload.language,
    )

    return VoiceTicketResponse(
        ticket=raw_ticket,
        expires_in=settings.VOICE_TICKET_EXPIRE_SECONDS,
        websocket_url=f"{settings.API_V1_PREFIX}/voice/stream",
    )


def _validate_origin(origin: Optional[str]) -> bool:
    """Validates WebSocket request origin against allowed CORS origins."""
    if settings.DEBUG and settings.APP_ENV != "production":
        return True
    if settings.APP_ENV == "production":
        if not origin:
            return False
        return origin in settings.CORS_ORIGINS
    if not origin:
        return True
    return origin in settings.CORS_ORIGINS or "*" in settings.CORS_ORIGINS


@router.websocket("/stream")
async def voice_stream_websocket(
    websocket: WebSocket,
    ticket: Optional[str] = Query(None, description="Optional query parameter ticket fallback"),
):
    """Bidirectional WebSocket streaming audio and control multiplexer."""
    # Accept connection first to establish socket
    await websocket.accept()

    # 1. Validate Origin header
    origin = websocket.headers.get("origin")
    if not _validate_origin(origin):
        logger.warning("Rejected voice WebSocket with unauthorized origin: %s", origin)
        await websocket.close(code=4403, reason="Forbidden origin")
        return

    session: Optional[VoiceSession] = None
    conversation_id: Optional[UUID] = None
    pipeline: Optional[VoicePipeline] = None

    try:
        # 2. Authenticate connection via ticket
        raw_ticket = ticket
        if not raw_ticket:
            # Prefer first message authentication frame
            try:
                auth_raw = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
                auth_data = json.loads(auth_raw)
                auth_msg = VoiceAuthMessage.model_validate(auth_data)
                raw_ticket = auth_msg.ticket
            except (asyncio.TimeoutError, json.JSONDecodeError, ValidationError) as e:
                logger.warning("Voice WebSocket authentication handshake failed: %s", e)
                await websocket.send_text(
                    VoiceServerError(
                        code="AUTH_TIMEOUT",
                        message="Missing or malformed authentication frame.",
                    ).model_dump_json()
                )
                await websocket.close(code=4401, reason="Authentication failed")
                return

        # Atomically redeem single-use ticket
        ticket_data = await VoiceTicketService.redeem_ticket(raw_ticket)
        if not ticket_data:
            logger.warning("Voice WebSocket ticket redemption failed (invalid, expired, or replayed)")
            await websocket.send_text(
                VoiceServerError(
                    code="INVALID_TICKET",
                    message="Voice session ticket is invalid, expired, or already used.",
                ).model_dump_json()
            )
            await websocket.close(code=4401, reason="Ticket invalid or expired")
            return

        # 3. Establish request-scoped TenantContext
        TenantContext.set_current_tenant_id(ticket_data.org_id)

        # 4. Initialize or Resume Voice Session
        try:
            session, resumed = await VoiceSessionManager.create_or_resume_session(
                ticket=ticket_data,
                socket=websocket,
            )
            conversation_id = session.conversation_id
        except Exception as e:
            logger.exception("Failed to initialize voice session: %s", e)
            await websocket.send_text(
                VoiceServerError(
                    code="SESSION_INIT_FAILED",
                    message="Failed to initialize session.",
                ).model_dump_json()
            )
            await websocket.close(code=4500, reason="Initialization failed")
            return

        # Notify client session is active
        await websocket.send_text(
            VoiceServerSessionCreated(
                call_id=session.call_id,
                conversation_id=session.conversation_id,
                codec="pcm16",
                sample_rate=16000,
                frame_bytes=settings.VOICE_FRAME_BYTES,
                resumed=resumed,
            ).model_dump_json()
        )

        # 5. Initialize Real-Time Voice Pipeline (VAD, STT, LLM Orchestrator, TTS)
        pipeline = VoicePipeline(
            conversation_id=session.conversation_id,
            org_id=session.org_id,
            user_id=session.user_id,
            send_audio_chunk=websocket.send_bytes,
            send_json_message=lambda msg: websocket.send_text(json.dumps(msg)),
        )
        session.pipeline = pipeline
        await pipeline.start()

        # 6. Active Message & Audio Frame Multiplexing Loop
        max_frame_bytes = settings.VOICE_FRAME_BYTES * 10  # Max 200ms per packet (6400 bytes)
        max_buffer_bytes = settings.VOICE_FRAME_BYTES * settings.VOICE_MAX_BUFFER_FRAMES

        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                logger.info("Received websocket.disconnect frame for conv %s", conversation_id)
                if conversation_id:
                    await VoiceSessionManager.handle_disconnect(conversation_id, websocket)
                break

            if "bytes" in message and message["bytes"]:
                audio_bytes = message["bytes"]

                # Enforce frame size bounds to protect against memory exhaustion
                if len(audio_bytes) > max_frame_bytes:
                    logger.warning(
                        "Oversized audio frame rejected (%s bytes > %s max)",
                        len(audio_bytes),
                        max_frame_bytes,
                    )
                    await websocket.send_text(
                        VoiceServerError(
                            code="OVERSIZED_FRAME",
                            message="Audio frame exceeds maximum allowable packet size.",
                        ).model_dump_json()
                    )
                    continue

                # Validate PCM16 2-byte sample alignment
                if len(audio_bytes) % 2 != 0:
                    logger.warning("Rejecting audio frame with odd byte length (%s bytes)", len(audio_bytes))
                    await websocket.send_text(
                        VoiceServerError(
                            code="MALFORMED_FRAME",
                            message="Audio frame length must be an even number of bytes for 16-bit PCM.",
                        ).model_dump_json()
                    )
                    continue

                # Enforce bounded buffer and backpressure protection (preserving 2-byte sample alignment)
                if len(session.audio_buffer) + len(audio_bytes) > max_buffer_bytes:
                    excess = (len(session.audio_buffer) + len(audio_bytes)) - max_buffer_bytes
                    if excess % 2 != 0:
                        excess += 1
                    session.audio_buffer = session.audio_buffer[excess:]

                session.audio_buffer.extend(audio_bytes)

                # Diagnostic counters
                session.frames_received = getattr(session, "frames_received", 0) + 1
                session.bytes_received = getattr(session, "bytes_received", 0) + len(audio_bytes)
                if session.frames_received % 50 == 0:
                    try:
                        await websocket.send_text(json.dumps({
                            "type": "audio_diagnostics",
                            "backend_frames": session.frames_received,
                            "backend_bytes": session.bytes_received,
                        }))
                    except Exception:
                        pass

                # Stream audio into real-time voice pipeline
                await pipeline.process_incoming_pcm(audio_bytes)

            elif "text" in message and message["text"]:
                try:
                    payload_dict = json.loads(message["text"])
                    msg_type = payload_dict.get("type")

                    if msg_type == "end_session":
                        end_msg = VoiceEndSessionMessage.model_validate(payload_dict)
                        await pipeline.close()
                        duration, status_str = await VoiceSessionManager.handle_clean_hangup(
                            conversation_id=session.conversation_id,
                            reason=end_msg.reason or "user_hangup",
                        )
                        await websocket.send_text(
                            VoiceServerSessionEnded(
                                call_id=session.call_id,
                                conversation_id=session.conversation_id,
                                duration_seconds=duration,
                                status=status_str,
                                reason=end_msg.reason or "user_hangup",
                            ).model_dump_json()
                        )
                        await websocket.close(code=1000, reason="Clean termination")
                        return

                    elif msg_type == "interrupt":
                        _ = VoiceInterruptMessage.model_validate(payload_dict)
                        # Clear in-memory buffer on barge-in and cancel active synthesis
                        session.audio_buffer.clear()
                        await pipeline.trigger_barge_in()
                        logger.debug("Barge-in signaled for session %s", session.conversation_id)

                    elif msg_type == "set_mic_state":
                        _ = VoiceMicStateMessage.model_validate(payload_dict)

                    elif msg_type == "start":
                        start_msg = VoiceStartMessage.model_validate(payload_dict)
                        if start_msg.recording_consent is not None:
                            await VoiceSessionManager.update_recording_consent(
                                call_id=session.call_id,
                                org_id=session.org_id,
                                consent=start_msg.recording_consent,
                            )
                        # Automatically generate and speak friendly greeting via real LLM + Cartesia TTS
                        asyncio.create_task(pipeline.trigger_initial_greeting())

                except ValidationError as ve:
                    logger.warning("Malformed voice control frame: %s", ve)
                    await websocket.send_text(
                        VoiceServerError(
                            code="MALFORMED_CONTROL_FRAME",
                            message="Control frame failed schema validation.",
                        ).model_dump_json()
                    )

    except (WebSocketDisconnect, RuntimeError) as e:
        logger.info("Voice WebSocket disconnected for conversation %s: %s", conversation_id, e)
        if pipeline:
            await pipeline.close()
        if conversation_id:
            await VoiceSessionManager.handle_disconnect(conversation_id, websocket)

    except Exception as e:
        logger.exception("Unhandled error in voice WebSocket loop: %s", e)
        if pipeline:
            await pipeline.close()
        try:
            await websocket.close(code=4500, reason="Internal error")
        except Exception:
            pass

    finally:
        # Guarantee tenant context reset on any exit path
        TenantContext.clear()
