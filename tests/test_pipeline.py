import numpy as np
import pytest

from nlp.llm import ConversationContext
from pipeline import ProcessingPipeline, TurnCancelled


class FakeTranscriber:
    def transcribe(self, audio):
        return "I goed to school"


class FakeLLM:
    def generate(self, messages, on_chunk, cancelled):
        assert messages[-1]["content"] == "I goed to school"
        on_chunk("I went to school.")
        return "I went to school."


class FakeSynthesizer:
    def synthesize_stream(self, text):
        yield [0.1], 22050


class FakePlayer:
    def play(self, samples, sample_rate, cancelled):
        pass  # just consume; sentence-level chunks don't all equal the full reply


def test_pipeline_turn_updates_context_and_reports_events():
    events = []
    context = ConversationContext()
    pipeline = ProcessingPipeline(FakeTranscriber(), FakeLLM(), FakeSynthesizer(), FakePlayer())
    result = pipeline.run([0.1], context, lambda kind, value: events.append((kind, value)), lambda: False)
    assert result == ("I goed to school", "I went to school.")
    assert [item["role"] for item in context.messages] == ["user", "assistant"]
    kinds = [kind for kind, _ in events]
    assert kinds == ["processing", "transcribed", "response_chunk", "audio_playing"]
    # "processing" fires before "transcribed" so the UI can show "Transcribing..."
    assert events[0] == ("processing", "Transcribing...")


def test_pipeline_emits_empty_on_blank_transcript():
    events = []
    context = ConversationContext()

    class BlankTranscriber:
        def transcribe(self, audio):
            return "   "

    pipeline = ProcessingPipeline(BlankTranscriber(), FakeLLM(), FakeSynthesizer(), FakePlayer())
    result = pipeline.run([0.1], context, lambda kind, value: events.append((kind, value)), lambda: False)
    assert result is None
    assert context.messages == []
    kinds = [kind for kind, _ in events]
    assert "empty" in kinds
    assert "transcribed" not in kinds


def test_pipeline_respects_cancellation_before_transcription():
    events = []
    context = ConversationContext()
    pipeline = ProcessingPipeline(FakeTranscriber(), FakeLLM(), FakeSynthesizer(), FakePlayer())
    with pytest.raises(TurnCancelled):
        pipeline.run([0.1], context, lambda kind, value: events.append((kind, value)), lambda: True)
    assert context.messages == []


def test_pipeline_respects_cancellation_after_tts():
    """Cancellation between TTS sentences does not persist context."""
    events = []
    context = ConversationContext()
    calls = []

    class TwoSentenceSynth:
        def synthesize_stream(self, text):
            yield [0.1], 22050
            yield [0.2], 22050

    cancel_after = [False]

    class CancellingPlayer:
        def play(self, samples, sample_rate, cancelled):
            cancel_after[0] = True

    pipeline = ProcessingPipeline(FakeTranscriber(), FakeLLM(), TwoSentenceSynth(), CancellingPlayer())
    with pytest.raises(TurnCancelled):
        pipeline.run([0.1], context, lambda kind, value: events.append((kind, value)), lambda: cancel_after[0])
    # Context must NOT be updated on a cancelled turn
    assert context.messages == []
