import json
import threading

import pipeline as pipeline_module
from nlp.llm import ConversationContext
from pipeline import ProcessingPipeline
from utils.diagnostics import (
    configure_local_diagnostics,
    disable_local_diagnostics,
    log_diagnostic,
)


class AdvancingClock:
    """A patched monotonic clock advanced explicitly by deterministic fakes."""

    def __init__(self):
        self._seconds = 0.0
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            return self._seconds

    def advance(self, seconds):
        with self._lock:
            self._seconds += seconds


def test_pipeline_records_stage_milestones_without_conversation_content(tmp_path, monkeypatch):
    clock = AdvancingClock()
    monkeypatch.setattr(pipeline_module, "monotonic", clock)
    diagnostic_path = tmp_path / "diagnostics.log"
    assert configure_local_diagnostics(diagnostic_path)
    first_audio_played = threading.Event()

    class Transcriber:
        def transcribe(self, _audio):
            clock.advance(0.25)
            return "PRIVATE TRANSCRIPT 9271"

    class StreamingLLM:
        def generate(self, _messages, on_chunk, _cancelled):
            clock.advance(0.125)
            on_chunk("PRIVATE RESPONSE 6382")
            clock.advance(0.25)
            on_chunk(" is complete. ")
            assert first_audio_played.wait(timeout=1)
            clock.advance(0.25)

    class Synthesizer:
        def synthesize_stream(self, _text):
            clock.advance(0.125)
            yield [0.1], 22050
            clock.advance(0.125)

    class Player:
        def play(self, _samples, _sample_rate, _cancelled, on_volume=None):
            clock.advance(0.5)
            first_audio_played.set()

    pipeline = ProcessingPipeline(
        Transcriber(), StreamingLLM(), Synthesizer(), Player()
    )
    try:
        pipeline.run(
            [0.1], ConversationContext(), lambda *_: None, lambda: False
        )
        lines = diagnostic_path.read_text(encoding="utf-8").splitlines()
    finally:
        disable_local_diagnostics()

    events = [json.loads(line) for line in lines]
    stage_events = [event for event in events if event["event"] == "stage_completed"]
    milestones = {
        (event["stage"], event.get("milestone")): event["duration_ms"]
        for event in stage_events
    }

    assert milestones[("transcribe", None)] == 250
    assert milestones[("model", "first_token")] == 125
    assert milestones[("model", "first_sentence_ready")] == 375
    assert milestones[("model", None)] == 1375
    assert milestones[("tts", "first_audio_ready")] == 125
    assert milestones[("tts", "synthesis_total")] == 250
    diagnostic_text = diagnostic_path.read_text(encoding="utf-8")
    assert "PRIVATE TRANSCRIPT 9271" not in diagnostic_text
    assert "PRIVATE RESPONSE 6382" not in diagnostic_text
    assert all(
        set(event) <= {"event", "stage", "milestone", "duration_ms", "trace_id"}
        for event in stage_events
    )


def test_diagnostics_discard_unknown_milestones_and_private_text(tmp_path):
    diagnostic_path = tmp_path / "diagnostics.log"
    assert configure_local_diagnostics(diagnostic_path)
    try:
        log_diagnostic(
            "stage_completed",
            stage="model",
            milestone="PRIVATE RESPONSE 6382",
            duration_ms=25,
            transcript="PRIVATE TRANSCRIPT 9271",
        )
        log_diagnostic(
            "stage_completed",
            stage="model",
            milestone="first_token",
            duration_ms=25,
        )
        log_diagnostic(
            "stage_completed",
            stage="tts",
            milestone="first_token",
            duration_ms=25,
        )
        log_diagnostic(
            "turn_failed",
            stage="model",
            milestone="first_token",
            duration_ms=25,
        )
        lines = diagnostic_path.read_text(encoding="utf-8").splitlines()
    finally:
        disable_local_diagnostics()

    assert [json.loads(line) for line in lines] == [
        {"duration_ms": 25, "event": "stage_completed", "stage": "model"},
        {
            "duration_ms": 25,
            "event": "stage_completed",
            "milestone": "first_token",
            "stage": "model",
        },
        {"duration_ms": 25, "event": "stage_completed", "stage": "tts"},
        {"duration_ms": 25, "event": "turn_failed", "stage": "model"},
    ]
    assert "PRIVATE" not in "\n".join(lines)


def test_pipeline_aggregates_tts_milestones_once_for_multiple_sentences(tmp_path, monkeypatch):
    clock = AdvancingClock()
    monkeypatch.setattr(pipeline_module, "monotonic", clock)
    diagnostic_path = tmp_path / "diagnostics.log"
    assert configure_local_diagnostics(diagnostic_path)

    class Transcriber:
        def transcribe(self, _audio):
            return "I am practicing."

    class TwoSentenceLLM:
        def generate(self, _messages, on_chunk, _cancelled):
            on_chunk("Good start. Keep going.")

    class Synthesizer:
        def synthesize_stream(self, _text):
            clock.advance(0.125)
            yield [0.1], 22050
            clock.advance(0.125)

    class Player:
        def play(self, _samples, _sample_rate, _cancelled, on_volume=None):
            clock.advance(0.5)

    pipeline = ProcessingPipeline(
        Transcriber(), TwoSentenceLLM(), Synthesizer(), Player()
    )
    try:
        pipeline.run(
            [0.1], ConversationContext(), lambda *_: None, lambda: False
        )
        events = [
            json.loads(line)
            for line in diagnostic_path.read_text(encoding="utf-8").splitlines()
        ]
    finally:
        disable_local_diagnostics()

    milestones = [
        event for event in events
        if event["event"] == "stage_completed"
        and event["stage"] == "tts"
        and "milestone" in event
    ]
    assert [event["milestone"] for event in milestones] == [
        "first_audio_ready",
        "synthesis_total",
    ]
    assert [event["duration_ms"] for event in milestones] == [125, 500]
