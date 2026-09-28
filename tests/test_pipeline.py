import numpy as np
import pytest
from unittest.mock import MagicMock

from nlp.llm import ConversationContext, OllamaClient
from nlp.feedback import CoachFeedback
from pipeline import ProcessingPipeline, TurnCancelled, TurnResult, _for_tts, _strip_null_annotations
from storage.models import TurnMetrics


def test_chat_requests_resident_model(monkeypatch):
    fake_ollama = MagicMock()
    fake_ollama.chat.return_value = iter(())
    monkeypatch.setattr("ollama.Client", lambda **kwargs: fake_ollama)

    client = OllamaClient("http://localhost:11434", "mistral")
    client.generate([], lambda _: None, lambda: False)

    assert fake_ollama.chat.call_args.kwargs["keep_alive"] == -1


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
    def play(self, samples, sample_rate, cancelled, on_volume=None):
        pass  # just consume; sentence-level chunks don't all equal the full reply


def test_pipeline_turn_updates_context_and_reports_events():
    events = []
    context = ConversationContext()
    pipeline = ProcessingPipeline(FakeTranscriber(), FakeLLM(), FakeSynthesizer(), FakePlayer())
    result = pipeline.run([0.1], context, lambda kind, value: events.append((kind, value)), lambda: False)
    assert result == TurnResult(
        "I goed to school",
        "I went to school.",
        CoachFeedback(),
        TurnMetrics(4, 0, False, None),
    )
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
        def play(self, samples, sample_rate, cancelled, on_volume=None):
            cancel_after[0] = True

    pipeline = ProcessingPipeline(FakeTranscriber(), FakeLLM(), TwoSentenceSynth(), CancellingPlayer())
    with pytest.raises(TurnCancelled):
        pipeline.run([0.1], context, lambda kind, value: events.append((kind, value)), lambda: cancel_after[0])
    # Context must NOT be updated on a cancelled turn
    assert context.messages == []


def test_pipeline_confirm_fn_replaces_transcript_before_llm():
    events = []
    context = ConversationContext()

    class EditAwareLLM:
        def generate(self, messages, on_chunk, cancelled):
            assert messages[-1]["content"] == "I went to school"
            on_chunk("Great!")
            return "Great!"

    pipeline = ProcessingPipeline(FakeTranscriber(), EditAwareLLM(), FakeSynthesizer(), FakePlayer())
    result = pipeline.run(
        [0.1], context, lambda kind, value: events.append((kind, value)), lambda: False,
        confirm_fn=lambda text: "I went to school",
    )
    assert result == TurnResult(
        "I went to school",
        "Great!",
        CoachFeedback(),
        TurnMetrics(4, 0, True, None),
    )
    assert ("transcribed", "I went to school") in events
    assert [m["content"] for m in context.messages] == ["I went to school", "Great!"]


def test_pipeline_confirm_fn_cancel_discards_turn():
    events = []
    context = ConversationContext()
    pipeline = ProcessingPipeline(FakeTranscriber(), FakeLLM(), FakeSynthesizer(), FakePlayer())
    result = pipeline.run(
        [0.1], context, lambda kind, value: events.append((kind, value)), lambda: False,
        confirm_fn=lambda text: "",  # user discarded the turn
    )
    assert result is None
    assert context.messages == []
    assert not any(kind == "transcribed" for kind, _ in events)


def test_for_tts_strips_ellipsis_that_breaks_the_phonemizer():
    assert _for_tts("connecting Python with...") == "connecting Python with"
    assert _for_tts("Wait... really?") == "Wait really?"


def test_strip_null_annotations_removes_empty_correction_markers():
    text = 'Great job! [Correction: None] [Explanation: no errors to correct]'
    assert _strip_null_annotations(text) == "Great job!"


def test_speak_replays_clean_text_without_conversation_side_effects():
    synthesized = []
    played = []

    class RecordingSynthesizer:
        def synthesize_stream(self, text):
            synthesized.append(text)
            yield [0.1], 22050

    class RecordingPlayer:
        def play(self, samples, sample_rate, cancelled, on_volume=None):
            played.append((samples, sample_rate))

    class ForbiddenLLM:
        def generate(self, *args, **kwargs):
            raise AssertionError("replay must not call the LLM")

    pipeline = ProcessingPipeline(
        FakeTranscriber(), ForbiddenLLM(), RecordingSynthesizer(), RecordingPlayer()
    )
    events = []

    pipeline.speak(
        "Nice work. [Correction: I goed → I went]",
        lambda kind, value: events.append((kind, value)),
        lambda: False,
    )

    assert synthesized == ["Nice work."]
    assert played == [([0.1], 22050)]
    assert events[0] == ("audio_playing", "")


def test_speak_stops_between_audio_chunks_when_cancelled():
    cancelled = False

    class TwoChunkSynthesizer:
        def synthesize_stream(self, text):
            yield [0.1], 22050
            yield [0.2], 22050

    class CancellingPlayer:
        def play(self, samples, sample_rate, is_cancelled, on_volume=None):
            nonlocal cancelled
            cancelled = True

    pipeline = ProcessingPipeline(
        FakeTranscriber(), FakeLLM(), TwoChunkSynthesizer(), CancellingPlayer()
    )

    with pytest.raises(TurnCancelled):
        pipeline.speak("Two chunks.", lambda kind, value: None, lambda: cancelled)


def test_pipeline_returns_message_and_structured_feedback_separately():
    class CoachingLLM:
        def generate(self, messages, on_chunk, cancelled):
            response = (
                "What did you buy?\n"
                "[Correction: I go yesterday → I went yesterday]\n"
                "[Better phrasing: I stopped by yesterday.]\n"
                "[Category: verb_tense]"
            )
            on_chunk(response)
            return response

    context = ConversationContext()
    pipeline = ProcessingPipeline(
        FakeTranscriber(), CoachingLLM(), FakeSynthesizer(), FakePlayer()
    )

    result = pipeline.run([0.1], context, lambda kind, value: None, lambda: False)

    assert result == TurnResult(
        transcript="I goed to school",
        reply="What did you buy?",
        feedback=CoachFeedback(
            correction="I go yesterday → I went yesterday",
            better_phrasing="I stopped by yesterday.",
            category="verb_tense",
        ),
        metrics=TurnMetrics(4, 0, False, "verb_tense"),
    )
    assert context.messages[-1]["content"] == "What did you buy?"


def test_pipeline_builds_metrics_from_confirmed_transcript():
    class AcceptEditedTranscriptLLM:
        def generate(self, messages, on_chunk, cancelled):
            on_chunk("Great!")
            return "Great!"

    context = ConversationContext()
    pipeline = ProcessingPipeline(
        FakeTranscriber(), AcceptEditedTranscriptLLM(), FakeSynthesizer(), FakePlayer()
    )

    result = pipeline.run(
        [0.1],
        context,
        lambda kind, value: None,
        lambda: False,
        confirm_fn=lambda text: "Actually I went to school",
    )

    assert result.metrics == TurnMetrics(
        word_count=5,
        filler_count=1,
        transcript_edited=True,
        correction_category=None,
    )
