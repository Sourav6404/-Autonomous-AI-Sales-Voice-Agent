"""Voice Session Lifecycle & State Coordinator.

Manages connection states:
- CONNECTING
- INITIALIZING
- ACTIVE
- RECOVERABLE_DISCONNECT
- TERMINATED

Guarantees:
1. Atomically links exactly one Call and one Conversation on session start.
2. recording_consent_given defaults strictly to False.
3. Does not invent customer phone numbers or fake CRM customer records.
4. Resumption checks ownership and call status; invalidates stale connection generation.
5. Prevents concurrent sockets from controlling the same conversation.
6. Executes short-lived database transactions; never holds DB locks across network waits.
7. Distinguishes clean hangup from unexpected disconnect with a 30s recovery window.
"""

import asyncio
from datetime import datetime, timezone
from enum import Enum
import logging
from typing import Dict, Optional, Tuple
from uuid import UUID
from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.database import AsyncSessionLocal
from backend.app.models.call import Call
from backend.app.models.conversation import Conversation
from backend.app.schemas.voice import TicketData

logger = logging.getLogger(__name__)


class VoiceSessionState(str, Enum):
    """Explicit voice connection lifecycle states."""

    CONNECTING = "CONNECTING"
    INITIALIZING = "INITIALIZING"
    ACTIVE = "ACTIVE"
    RECOVERABLE_DISCONNECT = "RECOVERABLE_DISCONNECT"
    TERMINATED = "TERMINATED"


class VoiceSession:
    """Represents an active in-memory voice session context."""

    def __init__(
        self,
        call_id: UUID,
        conversation_id: UUID,
        org_id: UUID,
        user_id: UUID,
        caller_phone: str,
        language: str,
    ):
        self.call_id = call_id
        self.conversation_id = conversation_id
        self.org_id = org_id
        self.user_id = user_id
        self.caller_phone = caller_phone
        self.language = language
        self.state: VoiceSessionState = VoiceSessionState.CONNECTING
        self.generation: int = 1
        self.active_socket: Optional[WebSocket] = None
        self.started_at: datetime = datetime.now(timezone.utc)
        self.disconnect_task: Optional[asyncio.Task] = None
        self.audio_buffer: bytearray = bytearray()


class VoiceSessionManager:
    """Thread-safe coordinator for active voice sessions and database synchronization."""

    _sessions: Dict[UUID, VoiceSession] = {}  # conversation_id -> VoiceSession
    _lock = asyncio.Lock()
    _session_factory = None

    @classmethod
    def get_session_factory(cls):
        """Returns active database session factory (AsyncSessionLocal or test override)."""
        return cls._session_factory or AsyncSessionLocal

    @classmethod
    def set_session_factory(cls, factory):
        """Allows test fixtures to bind sessions to test database engines."""
        cls._session_factory = factory

    @classmethod
    async def create_or_resume_session(
        cls,
        ticket: TicketData,
        socket: WebSocket,
    ) -> Tuple[VoiceSession, bool]:
        """Creates a new Call+Conversation or resumes an existing eligible session.

        Returns (session, is_resumed).
        """
        async with cls._lock:
            # 1. Resumption flow if conversation_id was bound to the ticket
            if ticket.conversation_id:
                session, resumed = await cls._resume_session(ticket, socket)
                return session, resumed

            # 2. Check active session limit per organization
            active_org_count = sum(
                1 for s in cls._sessions.values()
                if s.org_id == ticket.org_id and s.state in (VoiceSessionState.ACTIVE, VoiceSessionState.INITIALIZING)
            )
            if active_org_count >= settings.MAX_VOICE_SESSIONS_PER_TENANT:
                raise ValueError(
                    f"Active voice session limit ({settings.MAX_VOICE_SESSIONS_PER_TENANT}) reached for this organization."
                )

            # 3. New Session Flow: Short-lived DB transaction creating Call and Conversation
            factory = cls.get_session_factory()
            async with factory() as db:
                call = Call(
                    org_id=ticket.org_id,
                    caller_phone_number=ticket.caller_phone or "browser-voice",
                    callee_phone_number="AI-Receptionist",
                    status="in_progress",
                    started_at=datetime.now(timezone.utc),
                    recording_consent_given=False,  # Explicit default False
                )
                db.add(call)
                await db.flush()

                conv = Conversation(
                    org_id=ticket.org_id,
                    call_id=call.id,
                    language=ticket.language,
                    status="active",
                    turn_count=0,
                )
                db.add(conv)
                await db.commit()
                await db.refresh(call)
                await db.refresh(conv)

                session = VoiceSession(
                    call_id=call.id,
                    conversation_id=conv.id,
                    org_id=ticket.org_id,
                    user_id=ticket.user_id,
                    caller_phone=call.caller_phone_number,
                    language=conv.language,
                )
                session.state = VoiceSessionState.ACTIVE
                session.active_socket = socket
                cls._sessions[conv.id] = session

                logger.info(
                    "Initialized new voice session call_id=%s conv_id=%s for org=%s",
                    call.id,
                    conv.id,
                    ticket.org_id,
                )
                return session, False

    @classmethod
    async def _resume_session(
        cls,
        ticket: TicketData,
        socket: WebSocket,
    ) -> Tuple[VoiceSession, bool]:
        """Resumes an existing conversation and linked call, invalidating previous generation."""
        conv_id = ticket.conversation_id
        assert conv_id is not None

        # Verify database eligibility
        factory = cls.get_session_factory()
        async with factory() as db:
            conv_stmt = select(Conversation).where(
                Conversation.id == conv_id,
                Conversation.org_id == ticket.org_id,
            )
            conv_res = await db.execute(conv_stmt)
            conv = conv_res.scalar_one_or_none()

            if not conv:
                raise ValueError(f"Conversation '{conv_id}' not found for authenticated organization.")

            if conv.status not in ("active", "handed_off"):
                raise ValueError(f"Conversation '{conv_id}' is {conv.status} and cannot be resumed.")

            call = None
            if conv.call_id:
                call_stmt = select(Call).where(Call.id == conv.call_id, Call.org_id == ticket.org_id)
                call_res = await db.execute(call_stmt)
                call = call_res.scalar_one_or_none()

            if not call or call.status not in ("initiated", "in_progress", "handed_off"):
                raise ValueError(f"Underlying call for conversation '{conv_id}' is not eligible for resumption.")

        # Check existing in-memory session or instantiate new resumed tracker
        existing_session = cls._sessions.get(conv_id)
        if existing_session:
            # Cancel any pending disconnect drop timer
            if existing_session.disconnect_task and not existing_session.disconnect_task.done():
                existing_session.disconnect_task.cancel()
                existing_session.disconnect_task = None

            # Invalidate previous socket generation if still open
            if existing_session.active_socket and existing_session.active_socket != socket:
                try:
                    logger.warning(
                        "Closing stale socket generation %s for conv_id %s",
                        existing_session.generation,
                        conv_id,
                    )
                    await existing_session.active_socket.close(code=4409, reason="Superseded by new connection")
                except Exception as e:
                    logger.debug("Stale socket close handled: %s", e)

            existing_session.generation += 1
            existing_session.active_socket = socket
            existing_session.state = VoiceSessionState.ACTIVE
            logger.info("Resumed active voice session conv_id=%s generation=%s", conv_id, existing_session.generation)
            return existing_session, True

        # Session was not in memory (e.g. backend restart or fresh resume ticket)
        session = VoiceSession(
            call_id=call.id,
            conversation_id=conv.id,
            org_id=ticket.org_id,
            user_id=ticket.user_id,
            caller_phone=call.caller_phone_number,
            language=conv.language,
        )
        session.state = VoiceSessionState.ACTIVE
        session.active_socket = socket
        cls._sessions[conv.id] = session
        return session, True

    @classmethod
    async def handle_clean_hangup(
        cls,
        conversation_id: UUID,
        reason: str = "user_hangup",
    ) -> Optional[Tuple[int, str]]:
        """Handles explicit clean termination from client."""
        async with cls._lock:
            session = cls._sessions.pop(conversation_id, None)
            if not session:
                return None

            session.state = VoiceSessionState.TERMINATED
            if session.disconnect_task and not session.disconnect_task.done():
                session.disconnect_task.cancel()

        # Update database in short-lived transaction
        return await cls._finalize_session_in_db(
            call_id=session.call_id,
            conv_id=session.conversation_id,
            org_id=session.org_id,
            started_at=session.started_at,
            final_status="completed",
        )

    @classmethod
    async def handle_disconnect(
        cls,
        conversation_id: UUID,
        socket: WebSocket,
    ) -> None:
        """Handles unexpected socket disconnect, scheduling recovery window."""
        async with cls._lock:
            session = cls._sessions.get(conversation_id)
            if not session:
                return

            # Verify disconnect came from currently active socket generation
            if session.active_socket != socket:
                logger.debug("Ignoring disconnect from superseded socket generation for conv %s", conversation_id)
                return

            session.state = VoiceSessionState.RECOVERABLE_DISCONNECT
            session.active_socket = None

            # Spawn recovery window timer
            recovery_seconds = settings.VOICE_RECOVERY_TIMEOUT_SECONDS
            session.disconnect_task = asyncio.create_task(
                cls._recovery_timer(conversation_id, session.generation, recovery_seconds)
            )
            logger.info(
                "Voice session %s disconnected; awaiting recovery for %ss",
                conversation_id,
                recovery_seconds,
            )

    @classmethod
    async def _recovery_timer(
        cls,
        conversation_id: UUID,
        generation: int,
        wait_seconds: int,
    ) -> None:
        """Waits for recovery window; drops call if unrecovered."""
        try:
            await asyncio.sleep(wait_seconds)
        except asyncio.CancelledError:
            return  # Reconnected successfully

        async with cls._lock:
            session = cls._sessions.get(conversation_id)
            if not session or session.generation != generation:
                return
            if session.state != VoiceSessionState.RECOVERABLE_DISCONNECT:
                return

            # Unrecovered session: finalize as dropped
            cls._sessions.pop(conversation_id, None)
            session.state = VoiceSessionState.TERMINATED

        logger.warning("Recovery timeout expired for conv %s; marking dropped", conversation_id)
        await cls._finalize_session_in_db(
            call_id=session.call_id,
            conv_id=session.conversation_id,
            org_id=session.org_id,
            started_at=session.started_at,
            final_status="dropped",
        )

    @classmethod
    async def _finalize_session_in_db(
        cls,
        call_id: UUID,
        conv_id: UUID,
        org_id: UUID,
        started_at: datetime,
        final_status: str,
    ) -> Tuple[int, str]:
        """Finalizes call and conversation in PostgreSQL."""
        now = datetime.now(timezone.utc)
        duration_sec = max(0, int((now - started_at).total_seconds()))

        factory = cls.get_session_factory()
        async with factory() as db:
            # Update Call
            call_stmt = select(Call).where(Call.id == call_id, Call.org_id == org_id)
            call_res = await db.execute(call_stmt)
            call = call_res.scalar_one_or_none()
            if call:
                call.status = final_status
                call.ended_at = now
                call.duration_seconds = duration_sec

            # Update Conversation
            conv_stmt = select(Conversation).where(Conversation.id == conv_id, Conversation.org_id == org_id)
            conv_res = await db.execute(conv_stmt)
            conv = conv_res.scalar_one_or_none()
            if conv:
                conv.status = "completed" if final_status == "completed" else "abandoned"

            await db.commit()

        return duration_sec, final_status

    @classmethod
    def get_session(cls, conversation_id: UUID) -> Optional[VoiceSession]:
        """Retrieves session context from memory."""
        return cls._sessions.get(conversation_id)

    @classmethod
    def reset_for_tests(cls):
        """Cleans in-memory tracking state between tests."""
        for s in cls._sessions.values():
            if s.disconnect_task and not s.disconnect_task.done():
                s.disconnect_task.cancel()
        cls._sessions.clear()
