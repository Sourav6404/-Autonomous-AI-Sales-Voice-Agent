"""Voice Activity Detection (VAD) and speech boundary detection.

Processes 16 kHz mono signed 16-bit LE PCM frames (20ms = 640 bytes).
Detects speech onset (barge-in trigger) and speech conclusion (turn completion trigger)
using adaptive energy and minimum-statistics noise tracking.
"""

import math
import struct
from dataclasses import dataclass
from typing import Optional

from backend.app.core.config import settings


@dataclass
class VADFrameResult:
    """Result of VAD frame analysis."""

    is_speech: bool
    speech_started: bool
    speech_ended: bool
    energy: float
    probability: float


class SileroVAD:
    """Voice Activity Detector optimized for 16kHz linear PCM audio streams."""

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_bytes: int = 640,
        energy_threshold: Optional[float] = None,
        silence_timeout_ms: Optional[int] = None,
        speech_trigger_ms: Optional[int] = None,
    ):
        self.sample_rate = sample_rate
        self.frame_bytes = frame_bytes
        self.num_samples = frame_bytes // 2
        self.frame_duration_ms = (self.num_samples / self.sample_rate) * 1000.0  # 20ms

        self.threshold = energy_threshold or settings.VAD_THRESHOLD
        self.silence_timeout_ms = silence_timeout_ms or settings.VAD_SILENCE_TIMEOUT_MS
        self.speech_trigger_ms = speech_trigger_ms or settings.VAD_SPEECH_TRIGGER_MS

        self.speech_trigger_frames = max(1, int(self.speech_trigger_ms / self.frame_duration_ms))
        self.silence_trigger_frames = max(1, int(self.silence_timeout_ms / self.frame_duration_ms))

        self.is_speaking = False
        self.consecutive_speech_frames = 0
        self.consecutive_silence_frames = 0
        self.noise_floor = 0.005

    def reset(self) -> None:
        """Resets detector state for a new conversation turn or post-barge-in."""
        self.is_speaking = False
        self.consecutive_speech_frames = 0
        self.consecutive_silence_frames = 0

    def compute_rms(self, pcm_bytes: bytes) -> float:
        """Calculates normalized Root Mean Square (RMS) energy in range [0.0, 1.0]."""
        if len(pcm_bytes) < 2:
            return 0.0

        num_samples = len(pcm_bytes) // 2
        fmt = f"<{num_samples}h"
        try:
            samples = struct.unpack(fmt, pcm_bytes[: num_samples * 2])
        except struct.error:
            return 0.0

        if not samples:
            return 0.0

        sum_squares = sum(s * s for s in samples)
        rms_raw = math.sqrt(sum_squares / num_samples)
        # Normalize 16-bit signed int max (32767.0) to [0.0, 1.0]
        return min(1.0, rms_raw / 32767.0)

    def process_frame(self, pcm_bytes: bytes) -> VADFrameResult:
        """Analyzes a 20ms audio frame and detects speech boundaries."""
        rms = self.compute_rms(pcm_bytes)

        # Dynamic threshold based on adaptive noise floor
        effective_threshold = max(self.threshold, self.noise_floor * 2.2)
        frame_has_voice = rms >= effective_threshold

        speech_started = False
        speech_ended = False

        if frame_has_voice:
            self.consecutive_speech_frames += 1
            self.consecutive_silence_frames = 0

            # Trigger speech onset if consecutive frames exceed threshold
            if not self.is_speaking and self.consecutive_speech_frames >= self.speech_trigger_frames:
                self.is_speaking = True
                speech_started = True
        else:
            self.consecutive_silence_frames += 1
            self.consecutive_speech_frames = 0

            # Update background noise floor slowly during silence
            self.noise_floor = 0.98 * self.noise_floor + 0.02 * rms

            # Trigger speech conclusion if consecutive silence frames exceed threshold
            if self.is_speaking and self.consecutive_silence_frames >= self.silence_trigger_frames:
                self.is_speaking = False
                speech_ended = True

        probability = min(1.0, max(0.0, rms / (effective_threshold * 2.0)))

        return VADFrameResult(
            is_speech=self.is_speaking,
            speech_started=speech_started,
            speech_ended=speech_ended,
            energy=rms,
            probability=probability,
        )
