"""Regression coverage for metadata leaked through sentence streaming."""

import threading

import pytest

from nlp.llm import ConversationContext
from pipeline import ProcessingPipeline, TurnCancelled


class Transcriber:
    def transcribe(self, _audio):
        return "I go to store yesterday"


class RecordingSynthesizer:
    def __init__(self):
        self.texts = []

    def synthesize_stream(self, text):
        self.texts.append(text)
        yield [0.1], 22050


class Player:
    def play(self, *_args, **_kwargs):
        pass


@pytest.mark.parametrize("chunk_size", [1, 7, 1000])
def test_coaching_annotations_never_reach_streamed_conversation_or_voice(chunk_size):
    reply = (
        "What did you buy? "
        "[Grammar: nice wording. Try a formal phrase instead.] "
        "[Agreement: good structure. Keep practicing.] "
        "[Note: [informal] is acceptable. Keep chatting.] "
        "[Correction: I go to store yesterday → I went to the store yesterday] "
        "[Category: verb_tense]"
    )

    class LLM:
        def generate(self, _messages, on_chunk, _cancelled):
            for index in range(0, len(reply), chunk_size):
                on_chunk(reply[index:index + chunk_size])

    events = []
    synth = RecordingSynthesizer()
    result = ProcessingPipeline(Transcriber(), LLM(), synth, Player()).run(
        [0.1], ConversationContext(), lambda k, v: events.append((k, v)), lambda: False
    )

    visible = "".join(value for kind, value in events if kind == "response_chunk")
    assert visible.strip() == "What did you buy?"
    assert synth.texts == ["What did you buy?"]
    assert result.reply == "What did you buy?"
    assert result.feedback.correction == (
        "I go to store yesterday → I went to the store yesterday"
    )


def test_interrupted_annotation_cannot_be_spoken_or_saved_as_conversation():
    class LLM:
        def generate(self, _messages, on_chunk, _cancelled):
            on_chunk("Keep going. [Grammar: a long note. More text. ")
            raise RuntimeError("disconnected")

    synth = RecordingSynthesizer()
    events = []
    result = ProcessingPipeline(Transcriber(), LLM(), synth, Player()).run(
        [0.1], ConversationContext(), lambda k, v: events.append((k, v)), lambda: False
    )

    assert result.reply == "Keep going."
    assert result.is_complete is False
    assert synth.texts == ["Keep going."]
    assert "Grammar" not in "".join(v for k, v in events if k == "response_chunk")


def test_next_sentence_is_prepared_while_previous_sentence_is_playing():
    second_prepared = threading.Event()

    class LLM:
        def generate(self, _messages, on_chunk, _cancelled):
            on_chunk("First sentence. Second sentence.")

    class Synthesizer:
        def synthesize_stream(self, text):
            if text == "Second sentence.":
                second_prepared.set()
            yield [0.1], 22050

    class BlockingPlayer:
        def __init__(self):
            self.calls = 0

        def play(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                assert second_prepared.wait(1), "next synthesis waited for playback to finish"

    player = BlockingPlayer()
    result = ProcessingPipeline(Transcriber(), LLM(), Synthesizer(), player).run(
        [0.1], ConversationContext(), lambda *_: None, lambda: False
    )

    assert result.audio_error is None
    assert result.is_complete
    assert player.calls == 2


def test_stopped_replay_does_not_resume_when_external_cancel_callback_resets():
    first_started = threading.Event()
    release_first = threading.Event()
    second_waiting = threading.Event()
    lock_released = threading.Event()
    stale_synthesis = threading.Event()

    class TrackedLock:
        def __init__(self):
            self.lock = threading.Lock()
            self.attempts = 0

        def acquire(self, *args, **kwargs):
            self.attempts += 1
            if self.attempts == 2:
                second_waiting.set()
            return self.lock.acquire(*args, **kwargs)

        def release(self):
            self.lock.release()
            lock_released.set()

        def __enter__(self):
            self.acquire()
            return self

        def __exit__(self, *_args):
            self.release()

    class SlowSynthesizer:
        def synthesize_stream(self, text):
            if text == "First replay.":
                first_started.set()
                assert release_first.wait(3)
            else:
                stale_synthesis.set()
            yield [0.1], 22050

    pipeline = ProcessingPipeline(Transcriber(), None, SlowSynthesizer(), Player())
    pipeline._synthesis_lock = TrackedLock()
    stop_first, stop_second = threading.Event(), threading.Event()

    def replay(text, stop):
        try:
            pipeline.speak(text, lambda *_: None, stop.is_set)
        except TurnCancelled:
            pass

    first = threading.Thread(target=replay, args=("First replay.", stop_first))
    second = threading.Thread(target=replay, args=("Second replay.", stop_second))
    first.start()
    try:
        assert first_started.wait(1)
        stop_first.set()
        first.join(1)
        assert not first.is_alive()
        second.start()
        assert second_waiting.wait(1)
        stop_second.set()
        second.join(1)
        assert not second.is_alive()
        # Qt's interruption flag resets when ReplayWorker finishes; emulate it.
        stop_first.clear()
        stop_second.clear()
        release_first.set()
        assert lock_released.wait(1)
        assert not stale_synthesis.wait(0.3), "a stopped replay started fresh synthesis"
    finally:
        stop_first.set()
        stop_second.set()
        release_first.set()
        first.join(1)
        if second.ident is not None:
            second.join(1)


def test_stopped_model_stream_cannot_append_text_after_turn_returns():
    release_model = threading.Event()
    model_finished = threading.Event()
    stop = threading.Event()
    events = []

    class LLM:
        def generate(self, _messages, on_chunk, _cancelled):
            on_chunk("First sentence. ")
            assert release_model.wait(3)
            on_chunk("Late text must not reach the next conversation.")
            model_finished.set()

    class StoppingPlayer:
        def play(self, *_args, **_kwargs):
            stop.set()

    pipeline = ProcessingPipeline(Transcriber(), LLM(), RecordingSynthesizer(), StoppingPlayer())
    try:
        result = pipeline.run(
            [0.1], ConversationContext(), lambda k, v: events.append((k, v)),
            lambda: False, playback_stop_requested=stop.is_set,
        )
        assert result.is_complete is False
        stop.clear()
        release_model.set()
        assert model_finished.wait(1)
        visible = "".join(v for k, v in events if k == "response_chunk")
        assert visible.strip() == "First sentence."
    finally:
        release_model.set()
