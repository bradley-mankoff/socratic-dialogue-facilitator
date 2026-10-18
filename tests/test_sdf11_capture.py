"""SDF-11 — live capture pipeline over fixture audio (story 28).

Voice-activity-gated capture through local transcription emits confirmed
transcript segments from fixture audio into the transcript store the tally
reads. No word-streaming display by design.

Seam: ``voice.capture``. The VAD and the transcriber are injected callables,
so the gate runs headless: fixture frames stand in for mic audio, a stub VAD
stands in for Silero, and a stub transcriber stands in for faster-whisper
int8. The Mac acceptance script (SDF-20) qualifies the real models against
this same seam.
"""

from __future__ import annotations

import pathlib

import pytest

from voice.capture import AudioFrame, CapturePipeline, TranscriptStore

FRAME_DT = 0.02  # 20 ms frames, the cadence Silero VAD consumes


def make_fixture(total_s: float, speech_intervals=()) -> list[AudioFrame]:
    """Synthetic fixture audio: bare timestamped frames over ``total_s``.

    Voicing lives in the VAD stub's intervals, not in the frames — the
    frames carry no speech flag, so only the gate can decide.
    """
    n = int(total_s / FRAME_DT)
    return [AudioFrame(t=round(i * FRAME_DT, 6), samples=b"\x00\x01")
            for i in range(n)]


class FixtureVad:
    """Stub gate: speech inside the fixture's voiced intervals."""

    def __init__(self, speech_intervals=()):
        self.intervals = tuple(speech_intervals)

    def is_speech(self, frame: AudioFrame) -> bool:
        return any(start <= frame.t < end
                   for start, end in self.intervals)


class FakeClock:
    def __init__(self):
        # Session timeline: the clock shares its origin with the fixture
        # frame timestamps (both seconds since capture start), which is
        # the pipeline's documented clock contract.
        self.now_s = 0.0

    def __call__(self) -> float:
        return self.now_s

    def advance(self, dt: float) -> None:
        self.now_s += dt


class StubTranscriber:
    """Stub local transcription: canned text, one entry per utterance.

    ``transcribe_s`` simulates model time on the fake clock so the
    confirmation-latency bound is observable headless. Each ``feed``
    also advances the session clock by one frame so the clock tracks
    the fixture timeline the way a live capture clock tracks the mic.
    """

    def __init__(self, texts, clock: FakeClock, transcribe_s: float = 0.4):
        self.texts = list(texts)
        self.clock = clock
        self.transcribe_s = transcribe_s
        self.calls: list[list[AudioFrame]] = []

    def transcribe(self, frames: list[AudioFrame]) -> str:
        self.calls.append(list(frames))
        self.clock.advance(self.transcribe_s)
        return self.texts[len(self.calls) - 1]


def run_pipeline(frames, vad, transcriber, clock) -> TranscriptStore:
    store = TranscriptStore()
    pipe = CapturePipeline(vad=vad, transcriber=transcriber,
                           store=store, clock=clock)
    for frame in frames:
        pipe.feed(frame)
        clock.advance(FRAME_DT)
    pipe.close()
    return store


# -- AC1: fixture audio yields confirmed segments within 3s of VAD end -----


def test_voiced_fixture_yields_confirmed_segment_within_3s_of_voice_end():
    clock = FakeClock()
    vad = FixtureVad(speech_intervals=[(0.2, 0.8)])
    transcriber = StubTranscriber(["justice is the advantage of the stronger"],
                                  clock)
    store = run_pipeline(make_fixture(2.0), vad, transcriber, clock)

    segments = store.segments()
    assert len(segments) == 1
    seg = segments[0]
    assert seg.text == "justice is the advantage of the stronger"
    assert seg.start_t == pytest.approx(0.2, abs=FRAME_DT)
    assert seg.end_t == pytest.approx(0.8, abs=FRAME_DT * 2)
    assert seg.confirmed_at - seg.end_t <= 3.0


def test_two_utterances_yield_two_confirmed_segments_in_order():
    clock = FakeClock()
    vad = FixtureVad(speech_intervals=[(0.2, 0.6), (1.0, 1.4)])
    transcriber = StubTranscriber(["first", "second"], clock)
    store = run_pipeline(make_fixture(2.0), vad, transcriber, clock)

    assert [s.text for s in store.segments()] == ["first", "second"]


# -- AC2: silence gates capture instead of hallucinating --------------------


def test_silence_fixture_stores_nothing_and_never_calls_transcriber():
    clock = FakeClock()
    vad = FixtureVad(speech_intervals=[])
    transcriber = StubTranscriber(["hallucinated words"], clock)
    store = run_pipeline(make_fixture(2.0), vad, transcriber, clock)

    assert store.segments() == []
    assert transcriber.calls == []


# -- AC3: no word-streaming partials path exists in the build ---------------


def test_no_word_streaming_partials_path_exists():
    import voice.capture as capture

    assert not any("partial" in name.lower() for name in dir(capture))
    for path in pathlib.Path("voice").glob("*.py"):
        assert "partial" not in path.read_text().lower(), path
