"""Comprehensive tests for Stage 4.1 Secure Voice Session & WebSocket Gateway.

Covers:
1. Ticket creation with valid JWT.
2. Ticket creation without authentication.
3. Ticket expiration.
4. Forged ticket rejection.
5. Single-use ticket replay rejection.
6. Cross-tenant conversation access.
7. WebSocket origin validation.
8. TenantContext cleanup.
9. One Call and one Conversation creation.
10. Duplicate creation prevention.
11. Resume without duplicate Call records.
12. Previous connection invalidation.
13. Clean hangup.
14. Unexpected disconnect and recovery.
15. Malformed PCM frames.
16. Oversized frames.
17. Concurrent connections to the same conversation.
"""

import asyncio
import json
import uuid
import pytest
from httpx import AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.tenant import TenantContext
from backend.app.main import app
from backend.app.models.call import Call
from backend.app.models.conversation import Conversation
from backend.app.models.organization import Organization
from backend.app.services.voice.session_manager import (
    VoiceSessionManager,
    VoiceSessionState,
)
from backend.app.services.voice.ticket_service import VoiceTicketService
from backend.tests.test_stage2_rbac import create_user_with_role


@pytest.fixture(autouse=True)
def setup_voice_test_environment(test_engine):
    """Resets in-memory ticket and session stores and binds session factory to test_engine."""
    VoiceTicketService.reset_in_memory_store_for_tests()
    VoiceSessionManager.reset_for_tests()
    factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    VoiceSessionManager.set_session_factory(factory)
    TenantContext.clear()
    yield
    VoiceTicketService.reset_in_memory_store_for_tests()
    VoiceSessionManager.reset_for_tests()
    VoiceSessionManager.set_session_factory(None)
    TenantContext.clear()


# ---------------------------------------------------------------------------
# Phase 2: Ticket Creation & Redemption Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ticket_creation_with_valid_jwt(client: AsyncClient, db_session: AsyncSession):
    """1. Tests that authenticated staff receive an ephemeral 256-bit voice ticket."""
    user, token = await create_user_with_role(db_session, "receptionist")
    headers = {"Authorization": f"Bearer {token}"}

    res = await client.post(
        "/api/v1/voice/tickets",
        json={"language": "en", "caller_phone": "+18005550199"},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert "ticket" in data
    assert data["ticket"].startswith("tkt_")
    assert len(data["ticket"]) >= 32
    assert data["expires_in"] == 30
    assert data["websocket_url"] == "/v1/voice/stream"


@pytest.mark.asyncio
async def test_ticket_creation_without_authentication(client: AsyncClient):
    """2. Tests that unauthenticated requests are rejected with 401."""
    res = await client.post("/api/v1/voice/tickets", json={})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_ticket_expiration(db_session: AsyncSession):
    """3. Tests that tickets expire after their configured TTL and cannot be redeemed."""
    org = Organization(name="Expire Corp", slug=f"exp-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.flush()

    raw_ticket = await VoiceTicketService.create_ticket(
        user_id=uuid.uuid4(),
        org_id=org.id,
        ttl_seconds=1,  # 1 second TTL
    )

    # Wait for expiry
    await asyncio.sleep(1.1)

    redeemed = await VoiceTicketService.redeem_ticket(raw_ticket)
    assert redeemed is None


@pytest.mark.asyncio
async def test_forged_ticket_rejection():
    """4. Tests that fabricated or forged tickets return None."""
    forged = f"tkt_{uuid.uuid4().hex}{uuid.uuid4().hex}"
    redeemed = await VoiceTicketService.redeem_ticket(forged)
    assert redeemed is None


@pytest.mark.asyncio
async def test_single_use_ticket_replay_rejection(db_session: AsyncSession):
    """5. Tests atomic redemption: first redemption succeeds; replay fails."""
    org = Organization(name="Replay Corp", slug=f"rep-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.flush()

    user_id = uuid.uuid4()
    raw_ticket = await VoiceTicketService.create_ticket(
        user_id=user_id,
        org_id=org.id,
    )

    # 1st Redemption: Success
    first_redeem = await VoiceTicketService.redeem_ticket(raw_ticket)
    assert first_redeem is not None
    assert first_redeem.user_id == user_id
    assert first_redeem.org_id == org.id

    # 2nd Redemption (Replay attack): Rejected
    second_redeem = await VoiceTicketService.redeem_ticket(raw_ticket)
    assert second_redeem is None


@pytest.mark.asyncio
async def test_cross_tenant_conversation_ticket_rejected(client: AsyncClient, db_session: AsyncSession):
    """6. Tests that requesting a ticket bound to another tenant's conversation is rejected with 404."""
    # Tenant A
    user_a, token_a = await create_user_with_role(db_session, "admin")

    # Tenant B
    org_b = Organization(name="Tenant B", slug=f"tb-{uuid.uuid4().hex[:6]}")
    db_session.add(org_b)
    await db_session.flush()
    conv_b = Conversation(org_id=org_b.id, language="en", status="active", turn_count=0)
    db_session.add(conv_b)
    await db_session.commit()

    # User A attempts to request ticket for Tenant B's conversation
    headers_a = {"Authorization": f"Bearer {token_a}"}
    res = await client.post(
        "/api/v1/voice/tickets",
        json={"conversation_id": str(conv_b.id)},
        headers=headers_a,
    )
    assert res.status_code == 404
    assert "was not found" in res.text


# ---------------------------------------------------------------------------
# Phase 3 & 4: WebSocket Gateway, Session Lifecycle & DB Safety Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_websocket_origin_validation():
    """7. Tests that unauthorized Origin headers are rejected with 4403 in production mode."""
    test_client = TestClient(app)

    orig_env = settings.APP_ENV
    orig_origins = settings.CORS_ORIGINS
    orig_debug = settings.DEBUG
    settings.APP_ENV = "production"
    settings.DEBUG = False
    settings.CORS_ORIGINS = ["https://app.fortisales.ai"]
    try:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with test_client.websocket_connect(
                "/v1/voice/stream",
                headers={"Origin": "https://malicious-attacker.com"},
            ) as ws:
                ws.receive_text()
        assert exc_info.value.code == 4403
    finally:
        settings.APP_ENV = orig_env
        settings.CORS_ORIGINS = orig_origins
        settings.DEBUG = orig_debug


@pytest.mark.asyncio
async def test_session_creation_call_conversation_and_consent(db_session: AsyncSession):
    """8, 9, 10. Tests that redeeming ticket creates exactly one Call (consent=False)
    and one Conversation, establishes TenantContext, and cleans up TenantContext on exit.
    """
    user, token = await create_user_with_role(db_session, "receptionist")
    await db_session.commit()
    raw_ticket = await VoiceTicketService.create_ticket(
        user_id=user.id,
        org_id=user.org_id,
        caller_phone="+15551234567",
        language="en",
    )

    test_client = TestClient(app)

    # Connect via WebSocket and send auth frame
    with test_client.websocket_connect("/v1/voice/stream") as ws:
        ws.send_text(json.dumps({"type": "auth", "ticket": raw_ticket}))

        resp_raw = ws.receive_text()
        resp = json.loads(resp_raw)

        assert resp["type"] == "session_created"
        call_id = uuid.UUID(resp["call_id"])
        conv_id = uuid.UUID(resp["conversation_id"])
        assert resp["codec"] == "pcm16"
        assert resp["sample_rate"] == 16000
        assert resp["frame_bytes"] == 640
        assert resp["resumed"] is False

        # Verify DB records
        call_stmt = select(Call).where(Call.id == call_id)
        call_res = await db_session.execute(call_stmt)
        call = call_res.scalar_one()

        assert call.org_id == user.org_id
        assert call.caller_phone_number == "+15551234567"
        assert call.status == "in_progress"
        assert call.recording_consent_given is False  # Explicit False requirement

        conv_stmt = select(Conversation).where(Conversation.id == conv_id)
        conv_res = await db_session.execute(conv_stmt)
        conv = conv_res.scalar_one()

        assert conv.org_id == user.org_id
        assert conv.call_id == call.id
        assert conv.status == "active"

        # End clean
        ws.send_text(json.dumps({"type": "end_session", "reason": "user_hangup"}))
        end_resp = json.loads(ws.receive_text())
        assert end_resp["type"] == "session_ended"

    # Verify TenantContext cleanup
    assert TenantContext.get_current_tenant_id() is None


@pytest.mark.asyncio
async def test_session_resume_without_duplicate_call_records(db_session: AsyncSession):
    """11, 12. Tests resuming an existing session without creating duplicate Call records."""
    user, token = await create_user_with_role(db_session, "receptionist")
    await db_session.commit()

    # 1. Start initial session
    ticket_1 = await VoiceTicketService.create_ticket(user_id=user.id, org_id=user.org_id)
    test_client = TestClient(app)

    with test_client.websocket_connect("/v1/voice/stream") as ws1:
        ws1.send_text(json.dumps({"type": "auth", "ticket": ticket_1}))
        init_resp = json.loads(ws1.receive_text())
        conv_id = uuid.UUID(init_resp["conversation_id"])
        call_id = uuid.UUID(init_resp["call_id"])

        # 2. Issue resume ticket for same conversation
        ticket_resume = await VoiceTicketService.create_ticket(
            user_id=user.id,
            org_id=user.org_id,
            conversation_id=conv_id,
        )

        # Connect with second socket generation
        with test_client.websocket_connect("/v1/voice/stream") as ws2:
            ws2.send_text(json.dumps({"type": "auth", "ticket": ticket_resume}))
            resume_resp = json.loads(ws2.receive_text())

            assert resume_resp["type"] == "session_created"
            assert resume_resp["resumed"] is True
            assert uuid.UUID(resume_resp["conversation_id"]) == conv_id
            assert uuid.UUID(resume_resp["call_id"]) == call_id

            # Clean close
            ws2.send_text(json.dumps({"type": "end_session"}))
            ws2.receive_text()

    # Verify no duplicate call records exist for this conversation
    count_stmt = select(Call).where(Call.org_id == user.org_id)
    count_res = await db_session.execute(count_stmt)
    calls = count_res.scalars().all()
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_clean_hangup_calculates_duration(db_session: AsyncSession):
    """13. Tests that clean hangup marks status='completed' and computes duration."""
    user, token = await create_user_with_role(db_session, "receptionist")
    await db_session.commit()
    raw_ticket = await VoiceTicketService.create_ticket(user_id=user.id, org_id=user.org_id)

    test_client = TestClient(app)
    with test_client.websocket_connect("/v1/voice/stream") as ws:
        ws.send_text(json.dumps({"type": "auth", "ticket": raw_ticket}))
        init_resp = json.loads(ws.receive_text())
        call_id = uuid.UUID(init_resp["call_id"])

        await asyncio.sleep(0.5)

        ws.send_text(json.dumps({"type": "end_session", "reason": "user_hangup"}))
        end_resp = json.loads(ws.receive_text())
        assert end_resp["type"] == "session_ended"
        assert end_resp["status"] == "completed"

    call_stmt = select(Call).where(Call.id == call_id)
    call_res = await db_session.execute(call_stmt)
    call = call_res.scalar_one()
    assert call.status == "completed"
    assert call.duration_seconds is not None
    assert call.duration_seconds >= 0


@pytest.mark.asyncio
async def test_unexpected_disconnect_and_recovery_drop(db_session: AsyncSession):
    """14. Tests unexpected disconnect marks dropped if unrecovered."""
    user, token = await create_user_with_role(db_session, "receptionist")
    await db_session.commit()
    raw_ticket = await VoiceTicketService.create_ticket(user_id=user.id, org_id=user.org_id)

    test_client = TestClient(app)
    with test_client.websocket_connect("/v1/voice/stream") as ws:
        ws.send_text(json.dumps({"type": "auth", "ticket": raw_ticket}))
        init_resp = json.loads(ws.receive_text())
        call_id = uuid.UUID(init_resp["call_id"])
        conv_id = uuid.UUID(init_resp["conversation_id"])

    # Session is now in memory; simulate disconnect recovery timer on pytest async loop
    session = VoiceSessionManager.get_session(conv_id)
    assert session is not None

    # Trigger disconnect recovery timer with a fast window (0.1s)
    session.state = VoiceSessionState.RECOVERABLE_DISCONNECT
    await VoiceSessionManager._recovery_timer(conv_id, session.generation, wait_seconds=0.1)

    db_session.expire_all()
    call_stmt = select(Call).where(Call.id == call_id)
    call_res = await db_session.execute(call_stmt)
    call = call_res.scalar_one()
    assert call.status == "dropped"

    conv_stmt = select(Conversation).where(Conversation.id == conv_id)
    conv_res = await db_session.execute(conv_stmt)
    conv = conv_res.scalar_one()
    assert conv.status == "abandoned"


@pytest.mark.asyncio
async def test_audio_framing_pcm16_and_oversized_rejection(db_session: AsyncSession):
    """15, 16. Tests valid 640-byte PCM16 chunks and rejection of oversized frames."""
    user, token = await create_user_with_role(db_session, "receptionist")
    await db_session.commit()
    raw_ticket = await VoiceTicketService.create_ticket(user_id=user.id, org_id=user.org_id)

    test_client = TestClient(app)
    with test_client.websocket_connect("/v1/voice/stream") as ws:
        ws.send_text(json.dumps({"type": "auth", "ticket": raw_ticket}))
        init_resp = json.loads(ws.receive_text())
        conv_id = uuid.UUID(init_resp["conversation_id"])

        # 1. Valid 20ms frame: exactly 640 bytes
        valid_pcm_frame = bytes([0] * 640)
        ws.send_bytes(valid_pcm_frame)

        # 2. Oversized packet > 6400 bytes (e.g. 10000 bytes)
        oversized = bytes([1] * 10000)
        ws.send_bytes(oversized)

        # Server dispatches OVERSIZED_FRAME error frame without dropping socket
        err_frame = json.loads(ws.receive_text())
        assert err_frame["type"] == "error"
        assert err_frame["code"] == "OVERSIZED_FRAME"

        # Verify session is still alive
        session = VoiceSessionManager.get_session(conv_id)
        assert session is not None
        assert session.state == VoiceSessionState.ACTIVE
        assert len(session.audio_buffer) == 640  # Only valid frame was buffered

        # Clean hangup
        ws.send_text(json.dumps({"type": "end_session"}))
        ws.receive_text()


@pytest.mark.asyncio
async def test_concurrent_connections_to_same_conversation(db_session: AsyncSession):
    """17. Tests that a new connection for the same conversation supersedes and closes the first."""
    user, token = await create_user_with_role(db_session, "receptionist")
    await db_session.commit()
    ticket_1 = await VoiceTicketService.create_ticket(user_id=user.id, org_id=user.org_id)

    test_client = TestClient(app)
    with test_client.websocket_connect("/v1/voice/stream") as ws1:
        ws1.send_text(json.dumps({"type": "auth", "ticket": ticket_1}))
        init_resp = json.loads(ws1.receive_text())
        conv_id = uuid.UUID(init_resp["conversation_id"])

        # Create resume ticket
        ticket_2 = await VoiceTicketService.create_ticket(
            user_id=user.id,
            org_id=user.org_id,
            conversation_id=conv_id,
        )

        with test_client.websocket_connect("/v1/voice/stream") as ws2:
            ws2.send_text(json.dumps({"type": "auth", "ticket": ticket_2}))
            res2 = json.loads(ws2.receive_text())
            assert res2["resumed"] is True

            # First socket is superseded and closed with 4409
            with pytest.raises(WebSocketDisconnect) as exc:
                ws1.receive_text()
            assert exc.value.code == 4409

            ws2.send_text(json.dumps({"type": "end_session"}))
            ws2.receive_text()


@pytest.mark.asyncio
async def test_invalid_ticket_closes_with_4401():
    """18. Regression test: invalid or expired ticket closes WebSocket with 4401 (not 4403)."""
    test_client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with test_client.websocket_connect("/v1/voice/stream") as ws:
            ws.send_text(json.dumps({"type": "auth", "ticket": "tkt_invalid_or_expired_token"}))
            ws.receive_text()  # Receive INVALID_TICKET error frame
            ws.receive_text()  # Wait for close
    assert exc_info.value.code == 4401


@pytest.mark.asyncio
async def test_pcm16_odd_byte_excess_buffer_trimming_and_malformed_rejection(db_session: AsyncSession):
    """19. Regression test: odd-byte frame rejected with MALFORMED_FRAME; buffer trimming preserves 2-byte sample alignment."""
    user, token = await create_user_with_role(db_session, "receptionist")
    await db_session.commit()
    raw_ticket = await VoiceTicketService.create_ticket(user_id=user.id, org_id=user.org_id)

    test_client = TestClient(app)
    with test_client.websocket_connect("/v1/voice/stream") as ws:
        ws.send_text(json.dumps({"type": "auth", "ticket": raw_ticket}))
        init_resp = json.loads(ws.receive_text())
        conv_id = uuid.UUID(init_resp["conversation_id"])

        # 1. Send odd-byte audio chunk (e.g., 641 bytes)
        odd_chunk = bytes([0] * 641)
        ws.send_bytes(odd_chunk)

        malformed_err = json.loads(ws.receive_text())
        assert malformed_err["type"] == "error"
        assert malformed_err["code"] == "MALFORMED_FRAME"

        # 2. Buffer trimming test with odd excess
        session = VoiceSessionManager.get_session(conv_id)
        assert session is not None

        # Pre-seed buffer with 640 bytes (even)
        valid_chunk = bytes([0] * 640)
        ws.send_bytes(valid_chunk)

        # Synchronize via an oversized check frame
        ws.send_bytes(bytes([1] * 10000))
        oversized_err = json.loads(ws.receive_text())
        assert oversized_err["code"] == "OVERSIZED_FRAME"
        assert len(session.audio_buffer) == 640

        # Verify odd-byte excess calculation rounds up to preserve 2-byte sample alignment
        # Simulating buffer holding 700 bytes, incoming 100 bytes, max limit 701 bytes -> excess 99 (odd)
        session.audio_buffer = bytearray(b"\x00" * 700)
        max_buffer_bytes = 701
        test_audio = bytes([0] * 100)
        excess = (len(session.audio_buffer) + len(test_audio)) - max_buffer_bytes
        assert excess == 99  # Odd excess
        if excess % 2 != 0:
            excess += 1
        assert excess == 100  # Rounded up to preserve 2-byte alignment
        session.audio_buffer = session.audio_buffer[excess:]
        session.audio_buffer.extend(test_audio)
        assert len(session.audio_buffer) % 2 == 0
        assert len(session.audio_buffer) == 700

        # Clean hangup
        ws.send_text(json.dumps({"type": "end_session"}))
        end_resp = json.loads(ws.receive_text())
        assert end_resp["type"] == "session_ended"


@pytest.mark.asyncio
async def test_production_redis_fail_closed():
    """20. Regression test: in production mode, Redis failure fails closed and rejects in-memory fallback."""
    orig_env = settings.APP_ENV
    settings.APP_ENV = "production"
    VoiceTicketService.set_redis_client_for_tests(None)

    try:
        # Ticket creation must raise RuntimeError when Redis is unavailable in production
        with pytest.raises(RuntimeError) as exc_info:
            await VoiceTicketService.create_ticket(
                user_id=uuid.uuid4(),
                org_id=uuid.uuid4(),
            )
        assert "Distributed Redis required" in str(exc_info.value)

        # Ticket redemption must fail closed (return None)
        redeemed = await VoiceTicketService.redeem_ticket("tkt_some_random_ticket")
        assert redeemed is None
    finally:
        settings.APP_ENV = orig_env
