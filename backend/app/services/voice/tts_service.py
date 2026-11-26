"""Streaming Text-to-Speech (TTS) services.

Provides ultra-low-latency streaming audio synthesis for Cartesia Sonic and ElevenLabs
with mock fallback. Output format: 16 kHz, mono, signed 16-bit linear PCM (LE).
Includes sentence-boundary token buffering for pipeline streaming.
"""

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, AsyncIterator, Awaitable, Callable, List, Optional
import httpx

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

SENTENCE_SPLIT_PATTERN = re.compile(r"([.?!:;\n]+(?:\s+|$))")


class SentenceAggregator:
    """Aggregates streamed LLM tokens into full sentences or complete clauses for TTS synthesis."""

    def __init__(self, min_sentence_words: int = 3):
        self.min_sentence_words = min_sentence_words
        self.buffer = ""

    def feed_token(self, token: str) -> List[str]:
        """Feeds a token from LLM stream and returns any completed sentences."""
        self.buffer += token
        parts = SENTENCE_SPLIT_PATTERN.split(self.buffer)

        # If we have delimiters
        if len(parts) > 1:
            ready_sentences = []
            # Combine sentences with delimiters
            i = 0
            while i < len(parts) - 1:
                sentence = (parts[i] + parts[i + 1]).strip()
                if sentence:
                    ready_sentences.append(sentence)
                i += 2
            # Remaining incomplete part
            self.buffer = parts[-1]
            return ready_sentences

        return []

    def flush(self) -> List[str]:
        """Flushes any remaining text in the buffer."""
        remaining = self.buffer.strip()
        self.buffer = ""
        if remaining:
            return [remaining]
        return []


class BaseTTSService(ABC):
    """Abstract interface for streaming Text-to-Speech synthesis."""

    @abstractmethod
    async def synthesize_stream(
        self,
        text: str,
        on_audio_chunk: Callable[[bytes], Awaitable[None]],
        cancellation_event: asyncio.Event,
    ) -> bool:
        """Synthesizes text into streaming 16kHz PCM16 audio chunks.

        Returns True if completed successfully, False if cancelled (barge-in).
        """
        pass


class CartesiaTTSService(BaseTTSService):
    """Low-latency streaming TTS using Cartesia Sonic HTTP raw PCM endpoint."""

    _UNSET = object()

    def __init__(
        self,
        api_key: Any = _UNSET,
        model: Optional[str] = None,
        voice_id: Optional[str] = None,
        sample_rate: int = 16000,
    ):
        self.api_key = settings.CARTESIA_API_KEY if api_key is self._UNSET else api_key
        self.model = model or settings.CARTESIA_MODEL
        self.voice_id = voice_id or settings.CARTESIA_VOICE_ID
        self.sample_rate = sample_rate

    async def synthesize_stream(
        self,
        text: str,
        on_audio_chunk: Callable[[bytes], Awaitable[None]],
        cancellation_event: asyncio.Event,
    ) -> bool:
        if not self.api_key:
            raise ValueError("CARTESIA_API_KEY is not configured.")

        if not text.strip() or cancellation_event.is_set():
            return False

        url = "https://api.cartesia.ai/tts/bytes"
        headers = {
            "X-API-Key": self.api_key,
            "Cartesia-Version": "2024-06-10",
            "Content-Type": "application/json",
        }
        payload = {
            "model_id": self.model,
            "transcript": text,
            "voice": {
                "mode": "id",
                "id": self.voice_id,
            },
            "output_format": {
                "container": "raw",
                "encoding": "pcm_s16le",
                "sample_rate": self.sample_rate,
            },
        }

        max_tts_attempts = 3
        for attempt in range(max_tts_attempts):
            if cancellation_event.is_set():
                return False
            try:
                async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
                    async with client.stream("POST", url, headers=headers, json=payload) as response:
                        if response.status_code in (502, 503, 504) and attempt < max_tts_attempts - 1:
                            logger.warning("Cartesia TTS %s on attempt %s. Retrying...", response.status_code, attempt + 1)
                            await asyncio.sleep(0.5 * (attempt + 1))
                            continue
                        if response.status_code != 200:
                            err_content = await response.aread()
                            logger.error(
                                "Cartesia TTS error (%s): %s", response.status_code, err_content[:200]
                            )
                            return False

                        async for chunk in response.aiter_bytes(chunk_size=640):
                            if cancellation_event.is_set():
                                logger.info("Cartesia TTS synthesis cancelled via barge-in.")
                                return False

                            if chunk:
                                await on_audio_chunk(chunk)
                return True
            except asyncio.CancelledError:
                return False
            except Exception as e:
                if attempt < max_tts_attempts - 1:
                    logger.warning("Cartesia TTS network retry (%s): %s", attempt + 1, e)
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                logger.error("Cartesia streaming TTS failed: %s", e)
                return False


class ElevenLabsTTSService(BaseTTSService):
    """Streaming TTS using ElevenLabs Turbo v2.5 streaming PCM endpoint."""

    _UNSET = object()

    def __init__(
        self,
        api_key: Any = _UNSET,
        voice_id: Optional[str] = None,
        sample_rate: int = 16000,
    ):
        self.api_key = settings.ELEVENLABS_API_KEY if api_key is self._UNSET else api_key
        self.voice_id = voice_id or settings.ELEVENLABS_VOICE_ID
        self.sample_rate = sample_rate

    async def synthesize_stream(
        self,
        text: str,
        on_audio_chunk: Callable[[bytes], Awaitable[None]],
        cancellation_event: asyncio.Event,
    ) -> bool:
        if not self.api_key:
            raise ValueError("ELEVENLABS_API_KEY is not configured.")

        if not text.strip() or cancellation_event.is_set():
            return False

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/stream?output_format=pcm_{self.sample_rate}"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        err_content = await response.aread()
                        logger.error(
                            "ElevenLabs TTS error (%s): %s", response.status_code, err_content
                        )
                        return False

                    async for chunk in response.aiter_bytes(chunk_size=640):
                        if cancellation_event.is_set():
                            logger.info("ElevenLabs TTS cancelled via barge-in.")
                            return False

                        if chunk:
                            await on_audio_chunk(chunk)
            return True
        except asyncio.CancelledError:
            return False
        except Exception as e:
            logger.error("ElevenLabs streaming TTS failed: %s", e)
            return False


class MockTTSService(BaseTTSService):
    """Deterministic mock TTS engine yielding 20ms PCM16 chunks for tests."""

    def __init__(self, chunk_size: int = 640, frames_per_word: int = 2):
        self.chunk_size = chunk_size
        self.frames_per_word = frames_per_word

    async def synthesize_stream(
        self,
        text: str,
        on_audio_chunk: Callable[[bytes], Awaitable[None]],
        cancellation_event: asyncio.Event,
    ) -> bool:
        if not text.strip():
            return True

        word_count = max(1, len(text.split()))
        total_frames = word_count * self.frames_per_word

        # Generate benign 440Hz audible test tone / linear PCM16 frame
        synthetic_frame = bytes([10, 0] * (self.chunk_size // 2))

        for _ in range(total_frames):
            if cancellation_event.is_set():
                logger.debug("Mock TTS synthesis aborted due to cancellation.")
                return False

            await on_audio_chunk(synthetic_frame)
            # Yield control to event loop to simulate speech pacing
            await asyncio.sleep(0.01)

        return True


def get_tts_service() -> BaseTTSService:
    """Factory resolving configured TTS service."""
    if settings.TTS_PROVIDER == "cartesia" and settings.CARTESIA_API_KEY:
        return CartesiaTTSService()
    if settings.TTS_PROVIDER == "elevenlabs" and settings.ELEVENLABS_API_KEY:
        return ElevenLabsTTSService()

    if settings.TTS_PROVIDER in ("cartesia", "elevenlabs"):
        logger.warning(
            "%s API key missing; falling back to mock TTS engine.",
            settings.TTS_PROVIDER.upper(),
        )
    return MockTTSService()
