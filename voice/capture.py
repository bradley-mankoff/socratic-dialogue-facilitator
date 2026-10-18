"""SDF-11 — voice-activity-gated live capture over fixture audio.

Frames flow through an injected VAD gate into an injected local
transcriber; each voiced utterance emits one confirmed transcript segment
into the :class:`TranscriptStore` the ambient tally (SDF-14) reads.
Confirmation happens synchronously at voice-activity end, inside the 3s
post-VAD-end target (spec story 28). Silence never reaches the transcriber,
so there is nothing to hallucinate from. By design the only emission is
confirmed segments — there is no streaming-hypothesis display path.

The ``clock`` must share the session timeline with frame timestamps (both
seconds since capture start) so confirmation latency is observable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Protocol


@dataclass(frozen=True)
class AudioFrame:
    """One chunk of fixture (or mic) audio headed for the VAD gate."""

    t: float
    samples: bytes


@dataclass(frozen=True)
class TranscriptSegment:
    """One confirmed utterance. Confirmed is the only kind the pipeline
    can emit — no hypothesis segment type exists."""

    text: str
    start_t: float
    end_t: float
    confirmed_at: float


class VoiceActivityDetector(Protocol):
    """Gate seam (Silero in production, fixture intervals in tests)."""

    def is_speech(self, frame: AudioFrame) -> bool: ...


class Transcriber(Protocol):
    """Local transcription seam (faster-whisper int8 in production)."""

    def transcribe(self, frames: list[AudioFrame]) -> str: ...


class TranscriptStore:
    """Confirmed segments in emission order — the store the tally reads."""

    def __init__(self) -> None:
        self._segments: list[TranscriptSegment] = []

    def append(self, segment: TranscriptSegment) -> None:
        self._segments.append(segment)

    def segments(self) -> list[TranscriptSegment]:
        return list(self._segments)


class CapturePipeline:
    """VAD-gated capture: buffer speech, confirm at voice-activity end."""

    def __init__(self, vad: VoiceActivityDetector,
                 transcriber: Transcriber,
                 store: TranscriptStore,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._vad = vad
        self._transcriber = transcriber
        self._store = store
        self._clock = clock
        self._buffer: list[AudioFrame] = []
        self._open = False

    def feed(self, frame: AudioFrame) -> None:
        if self._vad.is_speech(frame):
            self._open = True
            self._buffer.append(frame)
        elif self._open:
            self._confirm()

    def close(self) -> None:
        if self._open:
            self._confirm()

    def _confirm(self) -> None:
        frames, self._buffer = self._buffer, []
        self._open = False
        text = self._transcriber.transcribe(frames)
        self._store.append(TranscriptSegment(
            text=text,
            start_t=frames[0].t,
            end_t=frames[-1].t,
            confirmed_at=self._clock(),
        ))
