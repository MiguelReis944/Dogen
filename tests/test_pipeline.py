from nlp.llm import ConversationContext
from pipeline import ProcessingPipeline


class FakeTranscriber:
    def transcribe(self, audio):
        return "I goed to school"


class FakeLLM:
    def generate(self, messages, on_chunk, cancelled):
        assert messages[-1]["content"] == "I goed to school"
        on_chunk("I went to school.")
        return "I went to school."


class FakeSynthesizer:
    def synthesize(self, text):
        assert text == "I went to school."
        return [0.1], 22050


class FakePlayer:
    def play(self, samples, sample_rate, cancelled):
        assert (samples, sample_rate) == ([0.1], 22050)


def test_pipeline_turn_updates_context_and_reports_events():
    events = []
    context = ConversationContext()
    pipeline = ProcessingPipeline(FakeTranscriber(), FakeLLM(), FakeSynthesizer(), FakePlayer())
    result = pipeline.run([0.1], context, lambda kind, value: events.append((kind, value)), lambda: False)
    assert result == ("I goed to school", "I went to school.")
    assert [item["role"] for item in context.messages] == ["user", "assistant"]
    assert [kind for kind, _ in events] == ["transcribed", "response_chunk", "audio_playing"]
