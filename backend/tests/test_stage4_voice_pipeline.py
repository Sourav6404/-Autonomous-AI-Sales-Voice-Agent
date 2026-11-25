"""Comprehensive integration and unit test suite for Stage 4 Voice Pipeline.

Tests:
1. SileroVAD speech energy, onset detection, hangover silence detection.
2. SentenceAggregator clause and sentence boundary streaming.
3. STT services (Deepgram error on missing key, Mock streaming transcripts).
4. TTS services (Cartesia/ElevenLabs missing key, Mock PCM streaming, barge-in cancellation).
5. VoicePipeline full conversational turn integration with Stage 3 ConversationOrchestrator.
6. Barge-in interruption during AI speech generating clear_audio frame.
7. Explicit recording consent toggle in point-in-time session.
8. Receptionist console static route and asset serving.
"""

import asyncio
import json
import uuid
import pytest
from httpx import AsyncClient
from starlette.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.ai.providers.base import BaseLLMProvider, LLMResponse
from backend.app.core.config import settings
from backend.app.core.tenant import TenantContext
from backend.app.main import app
from backend.app.models.call import Call
from backend.app.models.conversation import Conversation
from backend.app.models.organization import Organization
from backend.app.services.voice.pipeline import VoicePipeline
from backend.app.services.voice.session_manager import VoiceSessionManager
from backend.app.services.voice.stt_service import DeepgramSTTService, MockSTTService
from backend.app.services.voice.ticket_service import VoiceTicketService
from backend.app.services.voice.tts_service import (
    CartesiaTTSService,
    ElevenLabsTTSService,
    MockTTSService,
    SentenceAggregator,
)
from backend.app.services.voice.vad import SileroVAD
from backend.tests.test_stage2_rbac import create_user_with_role


@pytest.fixture(autouse=True)
def setup_voice_pipeline_environment(test_engine):
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
# 1. Silero VAD Tests
# ---------------------------------------------------------------------------

def test_silero_vad_energy_calculation_and_speech_boundaries():
    vad = SileroVAD(speech_trigger_ms=40, silence_timeout_ms=60)  # 2 frames speech, 3 frames silence

    quiet_frame = bytes([0] * 640)
    rms_quiet = vad.compute_rms(quiet_frame)
    assert rms_quiet == 0.0

    # Loud speech frame (amplitude ~15000 in 16-bit integer)
    loud_sample = (15000).to_bytes(2, byteorder="little", signed=True)
    loud_frame = loud_sample * 320
    rms_loud = vad.compute_rms(loud_frame)
    assert rms_loud > 0.4

    # 1. Process quiet frames -> no speech
    res1 = vad.process_frame(quiet_frame)
    assert res1.is_speech is False
    assert res1.speech_started is False

    # 2. Process first loud frame -> consecutive count increases, not yet confirmed
    res2 = vad.process_frame(loud_frame)
    assert res2.is_speech is False

    # 3. Process second loud frame -> triggers speech onset!
    res3 = vad.process_frame(loud_frame)
    assert res3.is_speech is True
    assert res3.speech_started is True

    # 4. Process silence frames -> triggers speech conclusion after 3 frames
    vad.process_frame(quiet_frame)
    vad.process_frame(quiet_frame)
    res_end = vad.process_frame(quiet_frame)
    assert res_end.is_speech is False
    assert res_end.speech_ended is True


# ---------------------------------------------------------------------------
# 2. SentenceAggregator Tests
# ---------------------------------------------------------------------------

def test_sentence_aggregator_delimiters():
    agg = SentenceAggregator()

    # Incomplete sentence
    out1 = agg.feed_token("Hello, thank you ")
    assert out1 == []

    out2 = agg.feed_token("for calling FortiSales AI. ")
    assert out2 == ["Hello, thank you for calling FortiSales AI."]

    out3 = agg.feed_token("How can I help you today? ")
    assert out3 == ["How can I help you today?"]

    # Trailing without delimiter flushed
    agg.feed_token("We provide 24/7 AI receptionist services")
    flushed = agg.flush()
    assert flushed == ["We provide 24/7 AI receptionist services"]


# ---------------------------------------------------------------------------
# 3. Provider Configuration Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deepgram_stt_requires_api_key():
    stt = DeepgramSTTService(api_key=None)
    with pytest.raises(ValueError) as exc:
        await stt.start(on_transcript=lambda t, f: None)
    assert "DEEPGRAM_API_KEY is not configured" in str(exc.value)


@pytest.mark.asyncio
async def test_tts_providers_require_api_key():
    cartesia = CartesiaTTSService(api_key=None)
    with pytest.raises(ValueError) as exc1:
        await cartesia.synthesize_stream("Hello", lambda chunk: None, asyncio.Event())
    assert "CARTESIA_API_KEY is not configured" in str(exc1.value)

    eleven = ElevenLabsTTSService(api_key=None)
    with pytest.raises(ValueError) as exc2:
        await eleven.synthesize_stream("Hello", lambda chunk: None, asyncio.Event())
    assert "ELEVENLABS_API_KEY is not configured" in str(exc2.value)


# ---------------------------------------------------------------------------
# 4. Mock Streaming & Barge-In Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mock_tts_streaming_and_barge_in_cancellation():
    tts = MockTTSService(chunk_size=640, frames_per_word=2)
    chunks_received = []

    async def collect_chunk(chunk: bytes):
        chunks_received.append(chunk)

    cancel_evt = asyncio.Event()

    # 1. Normal uninterrupted speech
    completed = await tts.synthesize_stream("One two three", collect_chunk, cancel_evt)
    assert completed is True
    assert len(chunks_received) == 6  # 3 words * 2 frames

    # 2. Interrupted speech (barge-in)
    chunks_received.clear()
    cancel_evt.set()  # Signal cancellation immediately
    completed_interrupted = await tts.synthesize_stream("One two three four", collect_chunk, cancel_evt)
    assert completed_interrupted is False
    assert len(chunks_received) == 0


# ---------------------------------------------------------------------------
# 5. Full VoicePipeline Integration Test
# ---------------------------------------------------------------------------

class StubLLMProvider(BaseLLMProvider):
    def __init__(self):
        super().__init__(provider_name="mock", model="mock-model")

    async def generate_response(self, messages, tools=None, response_schema=None, temperature=0.7, max_tokens=1024):
        return LLMResponse(
            content="Our office hours are Monday through Friday, 9 AM to 5 PM. Would you like to schedule an appointment?",
            tool_calls=[],
            finish_reason="stop",
            provider="mock",
        )

    async def generate_stream(self, messages, tools=None, temperature=0.7, max_tokens=1024):
        yield "Our office hours are Monday through Friday, 9 AM to 5 PM."


@pytest.mark.asyncio
async def test_voice_pipeline_full_turn_and_barge_in(db_session: AsyncSession):
    user, token = await create_user_with_role(db_session, "receptionist")
    conv = Conversation(org_id=user.org_id, language="en", status="active", turn_count=0)
    db_session.add(conv)
    await db_session.commit()

    audio_chunks = []
    json_messages = []

    async def handle_audio(chunk: bytes):
        audio_chunks.append(chunk)

    async def handle_json(msg: dict):
        json_messages.append(msg)

    mock_stt = MockSTTService(predefined_script=["What are your business hours?"])
    mock_tts = MockTTSService()
    mock_vad = SileroVAD(speech_trigger_ms=20, silence_timeout_ms=40)

    pipeline = VoicePipeline(
        conversation_id=conv.id,
        org_id=user.org_id,
        user_id=user.id,
        send_audio_chunk=handle_audio,
        send_json_message=handle_json,
        vad=mock_vad,
        stt_service=mock_stt,
        tts_service=mock_tts,
        llm_provider=StubLLMProvider(),
    )

    await pipeline.start()

    # 1. Simulate user speech: send loud PCM frames then silence
    loud_sample = (16000).to_bytes(2, byteorder="little", signed=True)
    loud_frame = loud_sample * 320
    quiet_frame = bytes([0] * 640)

    # 2 speech frames -> speech_started
    await pipeline.process_incoming_pcm(loud_frame)
    await pipeline.process_incoming_pcm(loud_frame)

    # 3 silence frames -> speech_ended -> triggers _execute_ai_turn
    await pipeline.process_incoming_pcm(quiet_frame)
    await pipeline.process_incoming_pcm(quiet_frame)
    await pipeline.process_incoming_pcm(quiet_frame)

    # Wait for turn execution task to complete
    if pipeline.active_turn_task:
        await pipeline.active_turn_task

    # Verify transcripts and audio chunks were emitted
    assert len(audio_chunks) > 0
    types = [m.get("type") for m in json_messages]
    assert "transcript" in types
    assert "speech_state" in types

    # Check caller transcript
    caller_transcripts = [m["text"] for m in json_messages if m.get("type") == "transcript" and m.get("role") == "caller"]
    assert "What are your business hours?" in caller_transcripts

    # 2. Test Barge-In Trigger
    pipeline.is_ai_speaking = True
    await pipeline.trigger_barge_in()
    assert pipeline.is_ai_speaking is False
    assert any(m.get("type") == "clear_audio" for m in json_messages)

    await pipeline.close()


# ---------------------------------------------------------------------------
# 6. Receptionist Static Console & Route Serving Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_receptionist_console_routes(client: AsyncClient):
    # Test console HTML route
    res_console = await client.get("/voice-console")
    assert res_console.status_code == 200
    assert "FortiSales AI" in res_console.text
    assert "receptionist.js" in res_console.text

    # Test static assets
    res_worklet = await client.get("/static/pcm-processor.js")
    assert res_worklet.status_code == 200
    assert "pcm16-capture-processor" in res_worklet.text

    res_client_js = await client.get("/static/receptionist.js")
    assert res_client_js.status_code == 200
    assert "ReceptionistVoiceClient" in res_client_js.text


# ---------------------------------------------------------------------------
# 7. WebSocket Start Frame Recording Consent Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_websocket_start_recording_consent_toggle(db_session: AsyncSession):
    user, token = await create_user_with_role(db_session, "receptionist")
    await db_session.commit()
    raw_ticket = await VoiceTicketService.create_ticket(user_id=user.id, org_id=user.org_id)

    test_client = TestClient(app)
    with test_client.websocket_connect("/v1/voice/stream") as ws:
        ws.send_text(json.dumps({"type": "auth", "ticket": raw_ticket}))
        init_resp = json.loads(ws.receive_text())
        call_id = uuid.UUID(init_resp["call_id"])

        # Send start frame with explicit recording_consent=True
        ws.send_text(json.dumps({
            "type": "start",
            "codec": "pcm16",
            "sample_rate": 16000,
            "channels": 1,
            "recording_consent": True,
        }))

        # End clean
        ws.send_text(json.dumps({"type": "end_session"}))
        ws.receive_text()

    # Verify Call record updated consent to True
    db_session.expire_all()
    call_stmt = select(Call).where(Call.id == call_id)
    call_res = await db_session.execute(call_stmt)
    call = call_res.scalar_one()
    assert call.recording_consent_given is True
