"""One spoken turn through the four local processing stages."""

import queue
import re
import threading
import uuid
from time import monotonic
from collections.abc import Callable
from dataclasses import dataclass, field

from nlp.feedback import CoachFeedback, parse_reply
from nlp.filler_words import count_fillers
from nlp.llm import ConversationContext
from utils.diagnostics import log_diagnostic
from storage.models import TurnMetrics

# Split on sentence-ending punctuation, keeping the delimiter with the left side.
_SENTENCE_END_RE = re.compile(r'(?<=[.!?])\s+')

# Strip any annotation block the LLM might produce: [Anything: ...].
# Matches [Word(s): content] — keeps the text visible in the UI but silent in TTS.
_COACHING_BLOCK_RE = re.compile(r'\[[A-Z][^:\[\]\n]*:.*?\]\s*', re.DOTALL)
_ELLIPSIS_RE = re.compile(r'\.{2,}')

# Null correction markers the model sometimes emits when it has nothing real to say.
_NULL_ANNOTATION_RE = re.compile(
    r'\[(Correction|Better phrasing|Explanation|Note)\s*:\s*(None|N/A|no errors?|no correction needed)[^\]]*\]\s*',
    re.IGNORECASE | re.DOTALL,
)


def _strip_null_annotations(text: str) -> str:
    """Remove annotations where the model wrote a marker but had nothing to correct."""
    return _NULL_ANNOTATION_RE.sub('', text).strip()


def _for_tts(text: str) -> str:
    text = _COACHING_BLOCK_RE.sub('', text)
    text = _ELLIPSIS_RE.sub('', text)   # ellipsis causes gruut phonemizer artifacts
    return re.sub(r'\s+', ' ', text).strip()

_DONE = object()


class TurnCancelled(Exception):
    pass


@dataclass(frozen=True)
class TurnResult:
    transcript: str
    reply: str
    feedback: CoachFeedback
    metrics: TurnMetrics | None = None
    is_complete: bool = True
    error: str | None = None
    audio_error: str | None = None
    trace_id: str | None = field(default=None, compare=False)
    failure_stage: str | None = field(default=None, compare=False)


class ProcessingPipeline:
    def __init__(self, transcriber, llm, synthesizer, player):
        self.transcriber = transcriber
        self.llm = llm
        self.synthesizer = synthesizer
        self.player = player

    def speak(self, text: str, emit: Callable[[str, object], None],
              cancelled: Callable[[], bool]) -> None:
        spoken = _for_tts(text)
        if not spoken:
            return
        emit("audio_playing", "")
        for wav, sample_rate in self.synthesizer.synthesize_stream(spoken):
            if cancelled():
                raise TurnCancelled()
            self.player.play(
                wav,
                sample_rate,
                cancelled,
                on_volume=lambda rms: emit("speech_volume", str(rms)),
            )
            if cancelled():
                raise TurnCancelled()

    def run(self, audio, context: ConversationContext, emit: Callable[[str, str], None],
            cancelled: Callable[[], bool], confirm_fn: Callable[[str], str] | None = None):
        if cancelled():
            raise TurnCancelled()
        trace_id = uuid.uuid4().hex
        emit("processing", "Transcribing...")
        stage_started = monotonic()
        try:
            transcript = self.transcriber.transcribe(audio).strip()
        except Exception as exc:
            log_diagnostic(
                "turn_failed", stage="transcribe", error_type=type(exc).__name__,
                trace_id=trace_id,
            )
            raise
        finally:
            log_diagnostic(
                "stage_completed",
                stage="transcribe",
                duration_ms=int((monotonic() - stage_started) * 1000),
                trace_id=trace_id,
            )
        original_transcript = transcript
        if cancelled():
            raise TurnCancelled()
        if not transcript:
            emit("empty", "Didn't catch that. Please try again.")
            return None

        if confirm_fn is not None:
            confirmed = confirm_fn(transcript)
            if cancelled():
                raise TurnCancelled()
            if not confirmed:
                return None
            transcript = confirmed

        emit("transcribed", transcript)

        pending = context.get_messages_for_ollama() + [{"role": "user", "content": transcript}]

        # Sentences flow from the LLM streamer → sentence_q → TTS consumer so that
        # audio playback of the first sentence starts before the LLM finishes the reply.
        sentence_q: queue.Queue = queue.Queue()
        reply_chunks: list[str] = []
        llm_errors: list[Exception] = []

        def _stream_llm():
            buf = ""
            stage_started = monotonic()
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
                if llm_errors:
                    log_diagnostic(
                        "turn_failed", stage="model",
                        error_type=type(llm_errors[0]).__name__, trace_id=trace_id,
                    )
                log_diagnostic(
                    "stage_completed",
                    stage="model",
                    duration_ms=int((monotonic() - stage_started) * 1000),
                    trace_id=trace_id,
                )
                sentence_q.put(_DONE)

        llm_thread = threading.Thread(target=_stream_llm, daemon=True)
        llm_thread.start()

        audio_error = None
        playback_interrupted = False
        while True:
            try:
                item = sentence_q.get(timeout=0.1)
            except queue.Empty:
                if cancelled():
                    llm_thread.join(timeout=0.25)
                    raise TurnCancelled()
                continue
            if item is _DONE:
                if cancelled():
                    raise TurnCancelled()
                break
            if audio_error:
                continue
            stage_started = monotonic()
            try:
                self.speak(item, emit, cancelled)
            except TurnCancelled:
                llm_thread.join(timeout=2)
                playback_interrupted = True
                break
            except Exception as exc:
                # A speaker failure must not discard text already generated by the LLM.
                audio_error = str(exc)
                log_diagnostic(
                    "turn_failed", stage="tts", error_type=type(exc).__name__,
                    trace_id=trace_id,
                )
            finally:
                log_diagnostic(
                    "stage_completed",
                    stage="tts",
                    duration_ms=int((monotonic() - stage_started) * 1000),
                    trace_id=trace_id,
                )

        llm_thread.join(timeout=5)

        raw_reply = _strip_null_annotations("".join(reply_chunks).strip())
        try:
            parsed = parse_reply(raw_reply)
        except Exception as exc:
            log_diagnostic(
                "turn_failed", stage="model", error_type=type(exc).__name__,
                trace_id=trace_id,
            )
            raise
        if not parsed.message and not llm_errors:
            log_diagnostic(
                "turn_failed", stage="model", error_type="EmptyResponse",
                trace_id=trace_id,
            )
            raise RuntimeError("Ollama returned an empty response")
        if cancelled() and not playback_interrupted:
            raise TurnCancelled()
        is_complete = not llm_errors and not playback_interrupted
        if is_complete:
            context.add_message("user", transcript)
            context.add_message("assistant", parsed.message)
        metrics = TurnMetrics(
            word_count=len(re.findall(r"\b[\w']+\b", transcript)),
            filler_count=count_fillers(transcript),
            transcript_edited=" ".join(transcript.split()) != " ".join(original_transcript.split()),
            correction_category=parsed.feedback.category,
        )
        error = str(llm_errors[0]) if llm_errors else None
        if playback_interrupted and error is None:
            error = "Response playback interrupted"
        return TurnResult(
            transcript,
            parsed.message,
            parsed.feedback,
            metrics,
            is_complete=is_complete,
            error=error,
            audio_error=audio_error,
            trace_id=trace_id,
            failure_stage=(
                "model" if llm_errors else "tts" if playback_interrupted else None
            ),
        )
