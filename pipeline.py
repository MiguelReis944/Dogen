"""One spoken turn through the four local processing stages."""

import queue
import re
import threading
from collections.abc import Callable

from nlp.llm import ConversationContext

# Split on sentence-ending punctuation, keeping the delimiter with the left side.
_SENTENCE_END_RE = re.compile(r'(?<=[.!?])\s+')

# Strip any annotation block the LLM might produce: [Anything: ...].
# Matches [Word(s): content] — keeps the text visible in the UI but silent in TTS.
_COACHING_BLOCK_RE = re.compile(r'\[[A-Z][^:\[\]\n]*:.*?\]\s*', re.DOTALL)


def _for_tts(text: str) -> str:
    return _COACHING_BLOCK_RE.sub('', text).strip()

_DONE = object()


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
        emit("processing", "Transcribing...")
        transcript = self.transcriber.transcribe(audio).strip()
        if cancelled():
            raise TurnCancelled()
        if not transcript:
            emit("empty", "Didn't catch that. Please try again.")
            return None
        emit("transcribed", transcript)

        pending = context.get_messages_for_ollama() + [{"role": "user", "content": transcript}]

        # Sentences flow from the LLM streamer → sentence_q → TTS consumer so that
        # audio playback of the first sentence starts before the LLM finishes the reply.
        sentence_q: queue.Queue = queue.Queue()
        reply_chunks: list[str] = []
        llm_errors: list[Exception] = []

        def _stream_llm():
            buf = ""
            try:
                def on_chunk(token: str):
                    nonlocal buf
                    buf += token
                    reply_chunks.append(token)
                    emit("response_chunk", token)
                    # Flush every complete sentence into the queue immediately.
                    parts = _SENTENCE_END_RE.split(buf)
                    for sentence in parts[:-1]:
                        s = sentence.strip()
                        if s:
                            sentence_q.put(s)
                    buf = parts[-1]

                self.llm.generate(pending, on_chunk, cancelled)
                if buf.strip():
                    sentence_q.put(buf.strip())
            except Exception as exc:
                llm_errors.append(exc)
            finally:
                sentence_q.put(_DONE)

        llm_thread = threading.Thread(target=_stream_llm, daemon=True)
        llm_thread.start()

        emit("audio_playing", "")
        while True:
            item = sentence_q.get()
            if item is _DONE:
                break
            if cancelled():
                llm_thread.join(timeout=2)
                raise TurnCancelled()
            spoken = _for_tts(item)
            if not spoken:
                continue  # correction-only fragment, show in UI but skip TTS
            for wav, sr in self.synthesizer.synthesize_stream(spoken):
                if cancelled():
                    llm_thread.join(timeout=2)
                    raise TurnCancelled()
                self.player.play(wav, sr, cancelled)

        llm_thread.join(timeout=5)
        if llm_errors:
            raise llm_errors[0]

        reply = "".join(reply_chunks).strip()
        if not reply:
            raise RuntimeError("Ollama returned an empty response")
        if cancelled():
            raise TurnCancelled()
        context.add_message("user", transcript)
        context.add_message("assistant", reply)
        return transcript, reply
