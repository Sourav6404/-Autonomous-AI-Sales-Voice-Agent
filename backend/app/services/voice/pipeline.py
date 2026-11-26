"""Real-time Voice Pipeline Orchestrator.

Integrates Silero VAD, streaming Speech-to-Text (Deepgram), Stage 3 ConversationOrchestrator,
SentenceAggregator, and streaming Text-to-Speech (Cartesia/ElevenLabs).
Coordinates barge-in, turn transitions, and backpressure.
"""

import asyncio
import logging
import time
from typing import Awaitable, Callable, Optional
from uuid import UUID

from backend.app.ai.conversation.orchestrator import ConversationOrchestrator
from backend.app.ai.conversation.prompt_manager import PromptManager
from backend.app.ai.providers.base import BaseLLMProvider, ChatMessage
from backend.app.ai.providers.factory import get_ai_provider
from backend.app.models.conversation import Conversation
from backend.app.models.message import Message
from sqlalchemy import select
from backend.app.services.voice.session_manager import VoiceSessionManager
from backend.app.services.voice.stt_service import BaseSTTService, get_stt_service
from backend.app.services.voice.tts_service import BaseTTSService, SentenceAggregator, get_tts_service
from backend.app.services.voice.vad import SileroVAD

logger = logging.getLogger(__name__)


class VoicePipeline:
    """Manages the full-duplex real-time audio pipeline for an active voice call."""

    def __init__(
        self,
        conversation_id: UUID,
        org_id: UUID,
        user_id: UUID,
        send_audio_chunk: Callable[[bytes], Awaitable[None]],
        send_json_message: Callable[[dict], Awaitable[None]],
        vad: Optional[SileroVAD] = None,
        stt_service: Optional[BaseSTTService] = None,
        tts_service: Optional[BaseTTSService] = None,
        llm_provider: Optional[BaseLLMProvider] = None,
    ):
        self.conversation_id = conversation_id
        self.org_id = org_id
        self.user_id = user_id
        self.send_audio_chunk = send_audio_chunk
        self.send_json_message = send_json_message

        self.vad = vad or SileroVAD()
        self.stt_service = stt_service or get_stt_service()
        self.tts_service = tts_service or get_tts_service()
        self.llm_provider = llm_provider

        self.is_customer_speaking = False
        self.is_ai_speaking = False
        self.is_processing_turn = False
        self.last_speech_ended_at: Optional[float] = None
        self.cached_system_prompt: Optional[str] = None

        self.cancellation_event = asyncio.Event()
        self.active_turn_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Starts upstream STT streaming session and prepares audio pipeline."""
        self.cancellation_event.clear()
        if hasattr(self.stt_service, "on_status"):
            self.stt_service.on_status = self._on_stt_status
        try:
            await self.stt_service.start(on_transcript=self._on_stt_transcript)
        except Exception as e:
            logger.warning("Upstream STT connection failed during start (%s); voice session will continue and retry on audio.", e)
            await self.send_json_message({
                "type": "warning",
                "code": "STT_CONNECT_DELAYED",
                "message": "Speech recognition is reconnecting in background.",
            })
        logger.info("VoicePipeline initialized for conversation %s", self.conversation_id)

    async def _on_stt_status(self, status: str) -> None:
        await self.send_json_message({
            "type": "stt_state",
            "state": status,
        })

    async def trigger_initial_greeting(self) -> None:
        """Plays instant pre-warmed opening greeting via Cartesia TTS without waiting for an LLM round-trip."""
        async with self._lock:
            if self.is_processing_turn:
                return
            self.is_processing_turn = True

        try:
            factory = VoiceSessionManager.get_session_factory()
            greeting_text = "Hello! Thank you for calling FortiSales. Welcome! I'm your AI receptionist. May I know your name?"
            async with factory() as db:
                conv_res = await db.execute(select(Conversation).where(Conversation.id == self.conversation_id))
                conv = conv_res.scalar_one_or_none()
                if conv and conv.turn_count > 0:
                    return

                asst_msg = Message(
                    conversation_id=self.conversation_id,
                    turn_number=1,
                    speaker_role="ai_agent",
                    content=greeting_text,
                    latency_ms=0,
                )
                db.add(asst_msg)
                if conv:
                    conv.turn_count = 1
                await db.commit()

            logger.info("Spoken instant AI greeting: '%s'", greeting_text)

            # 1. Send AI transcript turn to client UI immediately
            await self.send_json_message({
                "type": "transcript",
                "role": "ai_agent",
                "text": greeting_text,
                "is_final": True,
            })

            # 2. Indicate AI is speaking
            self.is_ai_speaking = True
            await self.send_json_message({
                "type": "speech_state",
                "speaker": "ai_agent",
                "state": "speaking",
            })

            # 3. Stream Cartesia TTS audio chunks directly to client
            await self.tts_service.synthesize_stream(
                text=greeting_text,
                on_audio_chunk=self.send_audio_chunk,
                cancellation_event=self.cancellation_event,
            )

        except Exception as e:
            logger.exception("Error triggering initial greeting: %s", e)
        finally:
            self.is_ai_speaking = False
            self.is_processing_turn = False
            await self.send_json_message({
                "type": "speech_state",
                "speaker": "ai_agent",
                "state": "silent",
            })

    async def _on_stt_transcript(self, transcript: str, is_final: bool) -> None:
        """Callback invoked when STT yields interim transcription during speech."""
        if not transcript.strip():
            return

        await self.send_json_message({
            "type": "transcript",
            "role": "caller",
            "text": transcript.strip(),
            "is_final": False,  # Always treat live streaming updates as interim
        })

    async def process_incoming_pcm(self, pcm_bytes: bytes) -> None:
        """Processes an incoming 20ms PCM16 frame from the client microphone."""
        vad_result = self.vad.process_frame(pcm_bytes)

        # 1. Barge-In Detection & Customer Speech Continuation
        if vad_result.speech_started:
            self.is_customer_speaking = True
            await self.send_json_message({
                "type": "speech_state",
                "speaker": "caller",
                "state": "speaking",
            })

            # Real barge-in: customer interrupted AI speaking out loud
            if self.is_ai_speaking:
                logger.info("Barge-in triggered: customer interrupted AI speaking on conv %s", self.conversation_id)
                await self.trigger_barge_in()
            # Customer continued speaking while AI was preparing a response:
            elif self.is_processing_turn:
                logger.info("Customer continued speaking during turn preparation on conv %s; rolling back transcript", self.conversation_id)
                if self.active_turn_task and not self.active_turn_task.done():
                    self.active_turn_task.cancel()
                    self.active_turn_task = None
                if getattr(self, "current_turn_transcript", None):
                    self.stt_service.rollback_transcript(self.current_turn_transcript)
                    self.current_turn_transcript = ""
                self.is_processing_turn = False

        # 2. Feed audio to STT engine
        await self.stt_service.send_audio(pcm_bytes)

        # 3. End-of-Speech Detection: Customer finished speaking
        if vad_result.speech_ended:
            self.last_speech_ended_at = time.time()
            self.is_customer_speaking = False
            await self.send_json_message({
                "type": "speech_state",
                "speaker": "caller",
                "state": "silent",
            })

            if not self.is_processing_turn and not self.is_ai_speaking:
                # Spawn AI turn generation task
                self.active_turn_task = asyncio.create_task(self._execute_ai_turn())

    async def trigger_barge_in(self) -> None:
        """Cancels active speech synthesis and instructs browser to flush audio buffers."""
        self.cancellation_event.set()

        if self.active_turn_task and not self.active_turn_task.done():
            self.active_turn_task.cancel()
            self.active_turn_task = None

        self.is_ai_speaking = False
        self.is_processing_turn = False

        # Send clear_audio frame to browser to instantly mute client-side playback buffer
        await self.send_json_message({"type": "clear_audio", "reason": "barge_in"})

    async def _execute_ai_turn(self) -> None:
        """Executes LLM reasoning, tools, and sentence-level streaming TTS with latency telemetry."""
        async with self._lock:
            self.is_processing_turn = True
            self.cancellation_event.clear()

        t_speech_end = self.last_speech_ended_at or time.time()

        try:
            # 1. Get finalized user transcript from STT
            user_transcript = await self.stt_service.finish_turn()
            self.current_turn_transcript = user_transcript
            t_stt_final = time.time()

            if not user_transcript.strip():
                self.is_processing_turn = False
                return

            t_orch_start = time.time()
            logger.info(
                "Executing AI turn for transcript: '%s' [STT final: %.3f, Orchestrator start: %.3f]",
                user_transcript, t_stt_final, t_orch_start
            )
            await self.send_json_message({
                "type": "transcript",
                "role": "caller",
                "text": user_transcript,
                "is_final": True,
            })

            # Notify UI that AI is thinking
            await self.send_json_message({
                "type": "speech_state",
                "speaker": "ai_agent",
                "state": "thinking",
            })

            # 2. Invoke Stage 3 ConversationOrchestrator in a point-in-time database session
            t_llm_start = time.time()
            factory = VoiceSessionManager.get_session_factory()
            turn_response = None
            async with factory() as db:
                turn_response = await ConversationOrchestrator.handle_message(
                    db=db,
                    conversation_id=self.conversation_id,
                    org_id=self.org_id,
                    user_message_text=user_transcript,
                    provider=self.llm_provider,
                    user_id=self.user_id,
                    enable_ai_fallback=True,
                )
            t_rag_complete = time.time()

            if not turn_response or not turn_response.assistant_reply or not turn_response.assistant_reply.content:
                self.is_processing_turn = False
                return

            if self.cancellation_event.is_set():
                logger.info("AI response discarded due to barge-in during generation.")
                return

            full_ai_text = turn_response.assistant_reply.content
            logger.info("AI generated response: '%s'", full_ai_text)

            # Signal handoff status event to client if conversation was handed off
            if turn_response.conversation_status == "handed_off":
                await self.send_json_message({
                    "type": "handoff_status",
                    "status": "handed_off",
                    "message": full_ai_text,
                })

            # 3. Sentence-level streaming TTS
            aggregator = SentenceAggregator()
            sentences = aggregator.feed_token(full_ai_text)
            sentences.extend(aggregator.flush())

            if not sentences:
                sentences = [full_ai_text]

            t_first_sentence = time.time()
            first_chunk_sent = False
            t_tts_first_chunk = None

            async def latency_tracked_audio_chunk(chunk: bytes):
                nonlocal first_chunk_sent, t_tts_first_chunk
                if not first_chunk_sent:
                    first_chunk_sent = True
                    t_tts_first_chunk = time.time()
                    telemetry = {
                        "speech_end_ts": round(t_speech_end, 3),
                        "stt_final_ms": int((t_stt_final - t_speech_end) * 1000),
                        "rag_retrieval_ms": int((t_rag_complete - t_rag_start) * 1000),
                        "llm_first_token_ms": int((t_rag_complete - t_stt_final) * 1000),
                        "first_sentence_ms": int((t_first_sentence - t_speech_end) * 1000),
                        "cartesia_first_chunk_ms": int((t_tts_first_chunk - t_first_sentence) * 1000),
                        "total_turn_to_first_audio_ms": int((t_tts_first_chunk - t_speech_end) * 1000),
                    }
                    logger.info("Turn Latency Telemetry: %s", telemetry)
                    await self.send_json_message({
                        "type": "latency_telemetry",
                        "metrics": telemetry,
                    })
                await self.send_audio_chunk(chunk)

            for sentence in sentences:
                if self.cancellation_event.is_set():
                    logger.info("Remaining sentences aborted due to barge-in.")
                    break

                # Send AI transcript turn to client UI
                await self.send_json_message({
                    "type": "transcript",
                    "role": "ai_agent",
                    "text": sentence,
                    "is_final": True,
                })

                self.is_ai_speaking = True
                await self.send_json_message({
                    "type": "speech_state",
                    "speaker": "ai_agent",
                    "state": "speaking",
                })

                # Stream audio chunks directly to client
                success = await self.tts_service.synthesize_stream(
                    text=sentence,
                    on_audio_chunk=latency_tracked_audio_chunk,
                    cancellation_event=self.cancellation_event,
                )

                if not success:
                    if not self.cancellation_event.is_set():
                        logger.error("TTS synthesis failed for sentence: %s", sentence)
                        await self.send_json_message({
                            "type": "error",
                            "code": "TTS_FAILED",
                            "message": "Cartesia TTS voice synthesis failed. Check Cartesia API status or key.",
                        })
                    break

        except asyncio.CancelledError:
            logger.info("AI turn task cancelled.")
        except Exception as e:
            logger.exception("Error executing AI voice turn: %s", e)
            await self.send_json_message({
                "type": "error",
                "code": "PIPELINE_ERROR",
                "message": "Encountered an internal error processing the voice response.",
            })
        finally:
            self.is_ai_speaking = False
            self.is_processing_turn = False
            self.vad.reset()
            await self.send_json_message({
                "type": "speech_state",
                "speaker": "ai_agent",
                "state": "silent",
            })

    async def close(self) -> None:
        """Terminates pipeline components."""
        self.cancellation_event.set()
        if self.active_turn_task and not self.active_turn_task.done():
            self.active_turn_task.cancel()
        await self.stt_service.close()
