"""One spoken turn through the four local processing stages."""

import queue
import re
import threading
import uuid
from time import monotonic
from collections.abc import Callable
from dataclasses import dataclass, field

from nlp.feedback import CoachFeedback, parse_reply, strip_coaching_markup
from nlp.filler_words import count_fillers
from nlp.llm import ConversationContext
from utils.diagnostics import log_diagnostic
from storage.models import TurnMetrics

# Split on sentence-ending punctuation, keeping the delimiter with the left side.
_SENTENCE_END_RE = re.compile(r'(?<=[.!?])\s+')

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
    text = strip_coaching_markup(text)
    text = _ELLIPSIS_RE.sub('', text)   # ellipsis causes gruut phonemizer artifacts
    return re.sub(r'\s+', ' ', text).strip()


class _ReplyTextStream:
    """Hold bracketed text until its closing delimiter, before sentence splitting."""

    def __init__(self):
        self._bracket = None
        self._depth = 0

    def feed(self, token: str) -> str:
        visible = []
        for char in token:
            if self._bracket is not None:
                self._bracket += char
                self._depth += (char == "[") - (char == "]")
                if self._depth == 0:
                    visible.append(strip_coaching_markup(self._bracket))
                    self._bracket = None
            elif char == "[":
                self._bracket = char
                self._depth = 1
            else:
                visible.append(char)
        # An unfinished block remains private even when a model stream is interrupted.
        return "".join(visible)

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
        self._synthesis_lock = threading.Lock()

    def speak(self, text: str, emit: Callable[[str, object], None],
              cancelled: Callable[[], bool], trace_id: str | None = None,
              tts_timing: dict | None = None) -> None:
        self._play_chunks(
            lambda stopped: self._audio_chunks(text, stopped, trace_id, tts_timing),
            emit, cancelled,
        )

    def _audio_chunks(self, text, cancelled, trace_id, tts_timing):
        spoken = _for_tts(text)
        if not spoken or cancelled():
            return
        synthesis_started = monotonic()
        if tts_timing is not None and tts_timing["started"] is None:
            tts_timing["started"] = synthesis_started
        synthesis_duration = 0.0
        try:
            # An interrupted producer may still finish a synchronous model call.
            # Serialize it with the next turn/replay rather than sharing Coqui state.
            acquired = False
            while not cancelled():
                if self._synthesis_lock.acquire(timeout=0.05):
                    acquired = True
                    break
            if not acquired:
                return
            try:
                if cancelled():
                    return
                iterator_started = monotonic()
                try:
                    audio_chunks = iter(self.synthesizer.synthesize_stream(spoken))
                finally:
                    synthesis_duration += monotonic() - iterator_started
                while not cancelled():
                    next_started = monotonic()
                    try:
                        chunk = next(audio_chunks)
                    except StopIteration:
                        synthesis_duration += monotonic() - next_started
                        break
                    except Exception:
                        synthesis_duration += monotonic() - next_started
                        raise
                    audio_ready_at = monotonic()
                    synthesis_duration += audio_ready_at - next_started
                    if tts_timing is not None and not tts_timing["first_audio_ready"]:
                        first_ready_started = tts_timing["started"]
                        log_diagnostic(
                            "stage_completed", stage="tts", milestone="first_audio_ready",
                            duration_ms=int((audio_ready_at - first_ready_started) * 1000),
                            trace_id=trace_id,
                        )
                        tts_timing["first_audio_ready"] = True
                    if cancelled():
                        raise TurnCancelled()
                    yield chunk
            finally:
                self._synthesis_lock.release()
        finally:
            if tts_timing is not None:
                tts_timing["synthesis_duration"] += synthesis_duration

    def _play_chunks(self, chunk_factory, emit, cancelled):
        """Prepare bounded audio ahead of playback to avoid one TTS pause per sentence."""
        ready = queue.Queue(maxsize=2)
        done = threading.Event()
        stopped = threading.Event()
        errors = []

        def preparation_cancelled():
            return stopped.is_set() or cancelled()

        def prepare():
            chunks = chunk_factory(preparation_cancelled)
            try:
                for chunk in chunks:
                    while not preparation_cancelled():
                        try:
                            ready.put(chunk, timeout=0.05)
                            break
                        except queue.Full:
                            continue
                    if preparation_cancelled():
                        break
            except Exception as exc:
                errors.append(exc)
            finally:
                chunks.close()
                done.set()

        producer = threading.Thread(target=prepare, daemon=True)
        producer.start()
        try:
            while True:
                if cancelled():
                    raise TurnCancelled()
                try:
                    wav, sample_rate = ready.get(timeout=0.1)
                except queue.Empty:
                    if done.is_set():
                        if errors:
                            raise errors[0]
                        break
                    continue
                emit("audio_playing", "")
                self.player.play(
                    wav, sample_rate, cancelled,
                    on_volume=lambda rms: emit("speech_volume", str(rms)),
                )
                if cancelled():
                    raise TurnCancelled()
        finally:
            stopped.set()
            producer.join(timeout=0.25)

    def run(self, audio, context: ConversationContext, emit: Callable[[str, str], None],
            cancelled: Callable[[], bool], confirm_fn: Callable[[str], str] | None = None,
            playback_stop_requested: Callable[[], bool] | None = None):
        playback_stop_requested = playback_stop_requested or (lambda: False)
        turn_stopped = threading.Event()

        def audio_cancelled():
            return turn_stopped.is_set() or cancelled() or playback_stop_requested()

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
            clean_stream = _ReplyTextStream()
            stage_started = monotonic()
            first_token_recorded = False
            first_sentence_recorded = False
            try:
                def on_chunk(token: str):
                    nonlocal buf, first_token_recorded, first_sentence_recorded
                    if audio_cancelled():
                        return
                    if not first_token_recorded:
                        log_diagnostic(
                            "stage_completed",
                            stage="model",
                            milestone="first_token",
                            duration_ms=int((monotonic() - stage_started) * 1000),
                            trace_id=trace_id,
                        )
                        first_token_recorded = True
                    reply_chunks.append(token)
                    visible = clean_stream.feed(token)
                    if not visible:
                        return
                    buf += visible
                    emit("response_chunk", visible)
                    # Flush every complete sentence into the queue immediately.
                    parts = _SENTENCE_END_RE.split(buf)
                    for sentence in parts[:-1]:
                        s = sentence.strip()
                        if s:
                            sentence_q.put(s)
                            if not first_sentence_recorded:
                                log_diagnostic(
                                    "stage_completed",
                                    stage="model",
                                    milestone="first_sentence_ready",
                                    duration_ms=int((monotonic() - stage_started) * 1000),
                                    trace_id=trace_id,
                                )
                                first_sentence_recorded = True
                    buf = parts[-1]

                self.llm.generate(pending, on_chunk, audio_cancelled)
                if buf.strip():
                    sentence_q.put(buf.strip())
                    if not first_sentence_recorded:
                        log_diagnostic(
                            "stage_completed",
                            stage="model",
                            milestone="first_sentence_ready",
                            duration_ms=int((monotonic() - stage_started) * 1000),
                            trace_id=trace_id,
                        )
                        first_sentence_recorded = True
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
        tts_timing = {
            "started": None,
            "first_audio_ready": False,
            "synthesis_duration": 0.0,
        }
        def queued_audio(preparation_cancelled):
            while not preparation_cancelled():
                try:
                    item = sentence_q.get(timeout=0.1)
                except queue.Empty:
                    continue
                if item is _DONE:
                    return
                yield from self._audio_chunks(
                    item, preparation_cancelled, trace_id, tts_timing
                )

        playback_started = monotonic()
        try:
            self._play_chunks(queued_audio, emit, audio_cancelled)
        except TurnCancelled:
            turn_stopped.set()
            if cancelled():
                llm_thread.join(timeout=0.25)
                raise
            playback_interrupted = True
        except Exception as exc:
            audio_error = str(exc)
            log_diagnostic(
                "turn_failed", stage="tts", error_type=type(exc).__name__, trace_id=trace_id,
            )
        finally:
            log_diagnostic(
                "stage_completed", stage="tts",
                duration_ms=int((monotonic() - playback_started) * 1000), trace_id=trace_id,
            )

        # Even if audio fails, keep collecting the complete text response.
        while llm_thread.is_alive() and not audio_cancelled():
            llm_thread.join(timeout=0.1)
        if cancelled():
            turn_stopped.set()
            raise TurnCancelled()
        if playback_stop_requested():
            playback_interrupted = True
        llm_thread.join(timeout=0.25)
        turn_stopped.set()
        if tts_timing["started"] is not None:
            log_diagnostic(
                "stage_completed",
                stage="tts",
                milestone="synthesis_total",
                duration_ms=int(tts_timing["synthesis_duration"] * 1000),
                trace_id=trace_id,
            )

        raw_reply = _strip_null_annotations("".join(reply_chunks).strip())
        try:
            parsed = parse_reply(raw_reply, user_text=transcript)
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
        if cancelled():
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
