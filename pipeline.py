"""One spoken turn through the four local processing stages."""

from collections.abc import Callable

from nlp.llm import ConversationContext


class TurnCancelled(Exception):
    pass


class ProcessingPipeline:
    def __init__(self, transcriber, llm, synthesizer, player):
        self.transcriber = transcriber
        self.llm = llm
        self.synthesizer = synthesizer
        self.player = player

    def run(self, audio, context: ConversationContext, emit: Callable[[str, str], None], cancelled: Callable[[], bool]):
        if cancelled():
            raise TurnCancelled()
        transcript = self.transcriber.transcribe(audio).strip()
        if cancelled():
            raise TurnCancelled()
        if not transcript:
            emit("empty", "Didn't catch that. Please try again.")
            return None
        emit("transcribed", transcript)
        pending = context.get_messages_for_ollama() + [{"role": "user", "content": transcript}]
        reply = self.llm.generate(pending, lambda chunk: emit("response_chunk", chunk), cancelled)
        if cancelled():
            raise TurnCancelled()
        if not reply:
            raise RuntimeError("Ollama returned an empty response")
        samples, sample_rate = self.synthesizer.synthesize(reply)
        if cancelled():
            raise TurnCancelled()
        emit("audio_playing", "")
        self.player.play(samples, sample_rate, cancelled)
        if cancelled():
            raise TurnCancelled()
        context.add_message("user", transcript)
        context.add_message("assistant", reply)
        return transcript, reply
