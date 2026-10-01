import threading
import re
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

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

    assert fake_ollama.chat.call_args.kwargs["keep_alive"] == "5m"


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


def test_pipeline_diagnostics_contain_stage_durations_but_no_conversation_text():
    private_text = "PRIVATE PHRASE 7391"

    class PrivateTranscriber:
        def transcribe(self, audio):
            return private_text

    class PrivateLLM:
        def generate(self, messages, on_chunk, cancelled):
            on_chunk("Reply about " + private_text)
            return "Reply about " + private_text

    pipeline = ProcessingPipeline(
        PrivateTranscriber(), PrivateLLM(), FakeSynthesizer(), FakePlayer()
    )
    context = ConversationContext()

    with patch("pipeline.log_diagnostic") as diagnostic:
        pipeline.run([0.1], context, lambda *_: None, lambda: False)

    logged_calls = diagnostic.call_args_list
    stages = {
        call.kwargs.get("stage")
        for call in logged_calls
        if call.args[0] == "stage_completed"
    }
    assert {"transcribe", "model", "tts"} <= stages
    assert all("duration_ms" in call.kwargs for call in logged_calls)
    trace_ids = {call.kwargs["trace_id"] for call in logged_calls}
    assert len(trace_ids) == 1
    assert re.fullmatch(r"[a-f0-9]{32}", trace_ids.pop())
    assert private_text not in repr(logged_calls)


def test_pipeline_respects_cancellation_before_transcription():
    events = []
    context = ConversationContext()
    pipeline = ProcessingPipeline(FakeTranscriber(), FakeLLM(), FakeSynthesizer(), FakePlayer())
    with pytest.raises(TurnCancelled):
        pipeline.run([0.1], context, lambda kind, value: events.append((kind, value)), lambda: True)
    assert context.messages == []


def test_pipeline_respects_cancellation_after_tts():
    """Cancellation during TTS returns an interrupted result, not context."""
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
    with patch("pipeline.log_diagnostic") as diagnostic:
        result = pipeline.run(
            [0.1], context, lambda kind, value: events.append((kind, value)),
            lambda: False,
            playback_stop_requested=lambda: cancel_after[0],
        )

    assert isinstance(result, TurnResult)
    assert result.transcript == "I goed to school"
    assert result.reply == "I went to school."
    assert result.is_complete is False
    assert result.error == "Response playback interrupted"
    assert result.failure_stage == "tts"
    assert not any(
        call.args[0] == "turn_failed" and call.kwargs.get("stage") == "model"
        for call in diagnostic.call_args_list
    )
    assert context.messages == []


def test_stop_audio_between_sentences_returns_replayable_partial_turn():
    first_audio_played = threading.Event()
    stop_observed = threading.Event()
    stop_checks_after_audio = [0]

    class StreamingLLM:
        def generate(self, _messages, on_chunk, _cancelled):
            on_chunk("The first sentence is complete. ")
            assert first_audio_played.wait(timeout=1)
            assert stop_observed.wait(timeout=1)

    class PlayerAfterFirstSentence:
        def play(self, _samples, _sample_rate, _cancelled, on_volume=None):
            first_audio_played.set()

    def stop_requested():
        if first_audio_played.is_set():
            stop_checks_after_audio[0] += 1
            if stop_checks_after_audio[0] >= 2:
                stop_observed.set()
                return True
        return False

    context = ConversationContext()
    pipeline = ProcessingPipeline(
        FakeTranscriber(), StreamingLLM(), FakeSynthesizer(), PlayerAfterFirstSentence()
    )

    result = pipeline.run(
        [0.1], context, lambda *_: None, lambda: False,
        playback_stop_requested=stop_requested,
    )

    assert isinstance(result, TurnResult)
    assert result.reply == "The first sentence is complete."
    assert result.is_complete is False
    assert result.error == "Response playback interrupted"
    assert context.messages == []


def test_pipeline_returns_interrupted_result_when_llm_fails_before_first_token():
    class BrokenLLM:
        def generate(self, messages, on_chunk, cancelled):
            raise RuntimeError("stream disconnected before first token")

    context = ConversationContext()
    pipeline = ProcessingPipeline(
        FakeTranscriber(), BrokenLLM(), FakeSynthesizer(), FakePlayer()
    )

    with patch("pipeline.log_diagnostic") as diagnostic:
        result = pipeline.run([0.1], context, lambda *_: None, lambda: False)

    assert isinstance(result, TurnResult)
    assert result.transcript == "I goed to school"
    assert result.reply == ""
    assert result.is_complete is False
    assert result.error == "stream disconnected before first token"
    assert result.metrics.word_count == 4
    assert result.failure_stage == "model"
    assert any(
        call.args[0] == "turn_failed" and call.kwargs.get("stage") == "model"
        for call in diagnostic.call_args_list
    )
    assert context.messages == []


def test_pipeline_transcription_failure_uses_transcribe_diagnostic_stage():
    class BrokenTranscriber:
        def transcribe(self, _audio):
            raise RuntimeError("recognizer unavailable")

    pipeline = ProcessingPipeline(
        BrokenTranscriber(), FakeLLM(), FakeSynthesizer(), FakePlayer()
    )
    with patch("pipeline.log_diagnostic") as diagnostic:
        with pytest.raises(RuntimeError, match="recognizer unavailable"):
            pipeline.run([0.1], ConversationContext(), lambda *_: None, lambda: False)

    assert any(
        call.args[0] == "turn_failed" and call.kwargs.get("stage") == "transcribe"
        for call in diagnostic.call_args_list
    )
    assert not any(
        call.args[0] == "turn_failed" and call.kwargs.get("stage") == "model"
        for call in diagnostic.call_args_list
    )


def test_pipeline_cancellation_interrupts_wait_for_first_llm_chunk():
    llm_started = threading.Event()
    release_llm = threading.Event()
    cancel = threading.Event()
    finished = threading.Event()
    outcome = []

    class WaitingLLM:
        def generate(self, messages, on_chunk, cancelled):
            llm_started.set()
            release_llm.wait(timeout=2)

    pipeline = ProcessingPipeline(
        FakeTranscriber(), WaitingLLM(), FakeSynthesizer(), FakePlayer()
    )

    def run_pipeline():
        try:
            pipeline.run([0.1], ConversationContext(), lambda *_: None, cancel.is_set)
        except Exception as exc:
            outcome.append(exc)
        finally:
            finished.set()

    runner = threading.Thread(target=run_pipeline, daemon=True)
    runner.start()
    try:
        assert llm_started.wait(timeout=1)
        cancel.set()
        assert finished.wait(timeout=0.4), "cancel waited for the stalled LLM stream"
        assert len(outcome) == 1
        assert isinstance(outcome[0], TurnCancelled)
    finally:
        release_llm.set()
        runner.join(timeout=1)


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
                "[Correction: I goed → I went]\n"
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
            correction="I goed → I went",
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
