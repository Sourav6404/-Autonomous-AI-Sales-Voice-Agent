"""Streaming Speech-to-Text (STT) services.

Provides streaming transcription over WebSocket using Deepgram Nova-2 with mock fallback.
Audio format: 16,000 Hz, 1 channel (mono), signed 16-bit linear PCM (little-endian).
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Optional
import websockets

from backend.app.core.config import settings

logger = logging.getLogger(__name__)


class BaseSTTService(ABC):
    """Abstract interface for bidirectional streaming Speech-to-Text services."""

    @abstractmethod
    async def start(self, on_transcript: Callable[[str, bool], Awaitable[None]]) -> None:
        """Establishes upstream STT connection and starts listener task."""
        pass

    @abstractmethod
    async def send_audio(self, pcm_bytes: bytes) -> None:
        """Sends a chunk of raw 16kHz linear PCM audio to the STT engine."""
        pass

    @abstractmethod
    async def finish_turn(self) -> str:
        """Signals turn completion, flushes pending transcripts, and returns final text."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Cleanly closes upstream connections."""
        pass


class DeepgramSTTService(BaseSTTService):
    """Streaming STT implementation using Deepgram's real-time Nova-2 WebSocket API."""

    _UNSET = object()

    def __init__(
        self,
        api_key: Any = _UNSET,
        model: Optional[str] = None,
        sample_rate: int = 16000,
    ):
        self.api_key = settings.DEEPGRAM_API_KEY if api_key is self._UNSET else api_key
        self.model = model or settings.DEEPGRAM_MODEL
        self.sample_rate = sample_rate

        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.receive_task: Optional[asyncio.Task] = None
        self.on_transcript: Optional[Callable[[str, bool], Awaitable[None]]] = None

        self.accumulated_transcript = ""
        self.is_connected = False
        self._lock = asyncio.Lock()

    async def start(self, on_transcript: Callable[[str, bool], Awaitable[None]]) -> None:
        """Connects to Deepgram live streaming endpoint."""
        if not self.api_key:
            raise ValueError(
                "DEEPGRAM_API_KEY is not configured. Provide an API key or use mock provider."
            )

        self.on_transcript = on_transcript
        self.accumulated_transcript = ""

        url = (
            f"wss://api.deepgram.com/v1/listen"
            f"?model={self.model}"
            f"&encoding=linear16"
            f"&sample_rate={self.sample_rate}"
            f"&channels=1"
            f"&endpointing=300"
            f"&interim_results=true"
            f"&smart_format=true"
        )
        headers = {
            "Authorization": f"Token {self.api_key}",
        }

        connect_kwargs = {
            "ping_interval": 10,
            "ping_timeout": 10,
        }
        import inspect
        sig = inspect.signature(websockets.connect)
        if "additional_headers" in sig.parameters:
            connect_kwargs["additional_headers"] = headers
        else:
            connect_kwargs["extra_headers"] = headers

        try:
            self.ws = await websockets.connect(
                url,
                **connect_kwargs,
            )
            self.is_connected = True
            self.receive_task = asyncio.create_task(self._receive_loop())
            logger.info("Connected to Deepgram streaming STT (%s)", self.model)
        except Exception as e:
            logger.error("Failed to connect to Deepgram streaming WebSocket: %s", e)
            self.is_connected = False
            raise

    async def _receive_loop(self) -> None:
        """Listens for transcript events from Deepgram."""
        assert self.ws is not None
        try:
            async for message in self.ws:
                if isinstance(message, str):
                    data = json.loads(message)
                    channel = data.get("channel", {})
                    alternatives = channel.get("alternatives", [])
                    if alternatives:
                        transcript = alternatives[0].get("transcript", "")
                        is_final = data.get("is_final", False)
                        speech_final = data.get("speech_final", False)

                        if transcript:
                            if is_final:
                                if self.accumulated_transcript:
                                    self.accumulated_transcript += " " + transcript
                                else:
                                    self.accumulated_transcript = transcript

                            if self.on_transcript:
                                await self.on_transcript(transcript, is_final or speech_final)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Error in Deepgram receive loop: %s", e)
        finally:
            self.is_connected = False

    async def send_audio(self, pcm_bytes: bytes) -> None:
        """Sends binary audio to Deepgram."""
        if self.ws and self.is_connected:
            try:
                await self.ws.send(pcm_bytes)
            except Exception as e:
                logger.warning("Error streaming audio to Deepgram: %s", e)
                self.is_connected = False

    async def finish_turn(self) -> str:
        """Flushes turn and returns transcript."""
        if self.ws and self.is_connected:
            try:
                # Deepgram KeepAlive/Flush frame
                await self.ws.send(json.dumps({"type": "KeepAlive"}))
            except Exception:
                pass
        result = self.accumulated_transcript.strip()
        self.accumulated_transcript = ""
        return result

    async def close(self) -> None:
        """Terminates WebSocket session."""
        self.is_connected = False
        if self.receive_task and not self.receive_task.done():
            self.receive_task.cancel()
        if self.ws:
            try:
                # Send Deepgram CloseStream message
                await self.ws.send(json.dumps({"type": "CloseStream"}))
                await self.ws.close()
            except Exception:
                pass
            self.ws = None


class MockSTTService(BaseSTTService):
    """Deterministic mock STT service for testing and offline development."""

    def __init__(self, predefined_script: Optional[list] = None):
        self.on_transcript: Optional[Callable[[str, bool], Awaitable[None]]] = None
        self.script = predefined_script or [
            "Hi, what are your business hours?",
            "Can I book a demo appointment for tomorrow at 2 PM?",
            "What services do you provide?",
        ]
        self.script_index = 0
        self.accumulated_transcript = ""
        self.bytes_received = 0

    async def start(self, on_transcript: Callable[[str, bool], Awaitable[None]]) -> None:
        self.on_transcript = on_transcript
        self.accumulated_transcript = ""
        self.bytes_received = 0

    async def send_audio(self, pcm_bytes: bytes) -> None:
        self.bytes_received += len(pcm_bytes)
        # Periodically simulate interim transcript
        if self.bytes_received >= 3200 and self.on_transcript:  # 100ms
            current_phrase = self.script[self.script_index % len(self.script)]
            words = current_phrase.split()
            interim = " ".join(words[: min(len(words), max(1, self.bytes_received // 3200))])
            await self.on_transcript(interim, False)

    async def finish_turn(self) -> str:
        phrase = self.script[self.script_index % len(self.script)]
        self.script_index += 1
        if self.on_transcript:
            await self.on_transcript(phrase, True)
        self.bytes_received = 0
        return phrase

    async def close(self) -> None:
        pass


def get_stt_service() -> BaseSTTService:
    """Factory resolving configured STT service."""
    if settings.STT_PROVIDER == "deepgram" and settings.DEEPGRAM_API_KEY:
        return DeepgramSTTService()
    if settings.STT_PROVIDER == "deepgram" and not settings.DEEPGRAM_API_KEY:
        logger.warning("DEEPGRAM_API_KEY missing; using mock STT service for offline execution.")
    return MockSTTService()
