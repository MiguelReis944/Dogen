"""Background worker that captures and processes spoken conversation turns."""

import threading
import time

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from audio.player import Player
from audio.recorder import Recorder
from nlp.llm import ConversationContext, OllamaClient
from nlp.synthesizer import Synthesizer
from nlp.transcriber import Transcriber
from pipeline import ProcessingPipeline, TurnCancelled
from utils.diagnostics import log_diagnostic


class ConversationWorker(QThread):
    status_message    = pyqtSignal(str)
    recording_started = pyqtSignal()
    recording_finished = pyqtSignal(str, float)
    waiting_for_ptt   = pyqtSignal()
    transcribed       = pyqtSignal(str)
    transcript_review = pyqtSignal(str)   # needs user confirmation before LLM
    response_chunk    = pyqtSignal(str)
    audio_playing     = pyqtSignal()
    error             = pyqtSignal(str)
    ready             = pyqtSignal()
    turn_completed    = pyqtSignal(object, int)
    volume_level      = pyqtSignal(float)
    speech_level      = pyqtSignal(float)   # TTS playback amplitude, drives the pet's mouth

    def __init__(self, config, context, model, pipeline=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.context = context
        self.model = model
        self._prebuilt_pipeline = pipeline
        self.built_pipeline = None
        self._ptt_start_event = threading.Event()
        self._ptt_stop_event  = threading.Event()
        self._barge_in        = False
        self._playback_active = False
        self._barge_in_thread: threading.Thread | None = None
        self._barge_in_stop_event = threading.Event()
        self._confirm_event   = threading.Event()
        self._confirmed_text  = ""

    # ── cancellation ───────────────────────────────────────────────────────────

    def _cancelled(self):
        return self.isInterruptionRequested()

    def _cancelled_or_barge_in(self):
        return self.isInterruptionRequested() or self._barge_in

    # ── PTT ────────────────────────────────────────────────────────────────────

    def begin_ptt(self):
        self._ptt_start_event.set()

    def end_ptt(self):
        self._ptt_stop_event.set()

    def _prepare_ptt_wait(self):
        self._ptt_start_event.clear()
        self._ptt_stop_event.clear()
        self.waiting_for_ptt.emit()

    def confirm_transcript(self, text: str):
        self._confirmed_text = text
        self._confirm_event.set()

    def cancel_transcript(self):
        self._confirmed_text = ""
        self._confirm_event.set()

    def stop_playback(self):
        if self._playback_active:
            self._barge_in = True

    def _make_confirm_fn(self):
        def _confirm(transcript: str) -> str:
            self._confirmed_text = transcript
            self._confirm_event.clear()
            self.transcript_review.emit(transcript)
            while not self._cancelled():
                if self._confirm_event.wait(timeout=0.1):
                    return self._confirmed_text
            return ""
        return _confirm

    # ── barge-in ───────────────────────────────────────────────────────────────

    def _start_barge_in_detector(self):
        threshold = self.config.vad_threshold * 1.5

        def _listen():
            consecutive = 0
            try:
                import sounddevice as sd
                with sd.InputStream(samplerate=16000, channels=1, dtype="float32",
                                    blocksize=1600, device=self.config.mic_device) as stream:
                    while (
                        not self._cancelled_or_barge_in()
                        and not self._barge_in_stop_event.is_set()
                    ):
                        block, _ = stream.read(1600)
                        if self._barge_in_stop_event.is_set():
                            break
                        if not self._playback_active:
                            consecutive = 0
                            continue
                        rms = float(np.sqrt(np.mean(block[:, 0] ** 2)))
                        if rms > threshold:
                            consecutive += 1
                            if consecutive >= 2:
                                self._barge_in = True
                                break
                        else:
                            consecutive = 0
            except Exception:
                pass

        t = threading.Thread(target=_listen, daemon=True)
        t.start()
        return t

    def _stop_barge_in_detector(self):
        self._barge_in_stop_event.set()
        thread = self._barge_in_thread
        if thread is not None:
            thread.join()
            self._barge_in_thread = None

    # ── progress relay ─────────────────────────────────────────────────────────

    def _emit_progress(self, kind, value):
        if kind == "transcribed":
            self.transcribed.emit(value)
        elif kind == "response_chunk":
            self.response_chunk.emit(value)
        elif kind == "audio_playing":
            self._playback_active = True
            if self._barge_in_thread is None or not self._barge_in_thread.is_alive():
                self._barge_in_stop_event.clear()
                self._barge_in_thread = self._start_barge_in_detector()
            self.audio_playing.emit()
        elif kind == "processing":
            self.status_message.emit(value)
        elif kind == "empty":
            self.error.emit(value)
        elif kind == "speech_volume":
            try:
                self.speech_level.emit(float(value))
            except ValueError:
                pass

    def _warm_up_llm(self, pipeline) -> bool:
        while not self._cancelled():
            try:
                pipeline.llm.client.list()
                break
            except Exception:
                self.status_message.emit("Waiting for Ollama on localhost:11434...")
                for _ in range(50):
                    if self._cancelled():
                        return False
                    self.msleep(100)
        if self._cancelled():
            return False
        self.status_message.emit(f"Loading {pipeline.llm.model} into RAM...")
        try:
            pipeline.llm.client.generate(
                model=pipeline.llm.model, prompt="", options={"num_predict": 0},
                keep_alive=-1,
            )
        except Exception as exc:
            log_diagnostic(
                "turn_failed", stage="model", error_type=type(exc).__name__
            )
            self.error.emit(f"Could not load {pipeline.llm.model}: {exc}")
            return False
        return True

    # ── main loop ──────────────────────────────────────────────────────────────

    def run(self):
        try:
            if self._prebuilt_pipeline:
                pipeline = self._prebuilt_pipeline
                pipeline.llm.model = self.model
            else:
                self.status_message.emit("Loading speech recognition…")
                try:
                    transcriber = Transcriber(self.config.whisper_model)
                except Exception as exc:
                    log_diagnostic(
                        "turn_failed", stage="transcribe",
                        error_type=type(exc).__name__,
                    )
                    self.error.emit(str(exc))
                    return
                if self._cancelled():
                    return
                self.status_message.emit("Loading voice…")
                try:
                    synthesizer = Synthesizer(self.config.tts_model)
                    synthesizer._speaker = self.config.tts_speaker
                except Exception as exc:
                    log_diagnostic(
                        "turn_failed", stage="tts", error_type=type(exc).__name__
                    )
                    self.error.emit(str(exc))
                    return
                if self._cancelled():
                    return
                pipeline = ProcessingPipeline(
                    transcriber,
                    OllamaClient(self.config.ollama_host, self.model),
                    synthesizer,
                    Player(self.config.speaker_device),
                )
            self.built_pipeline = pipeline

            try:
                recorder = Recorder(
                    self.config.mic_device,
                    self.config.vad_threshold,
                    self.config.silence_duration_sec,
                    self.config.noise_reduction,
                )
            except Exception as exc:
                log_diagnostic(
                    "turn_failed", stage="capture", error_type=type(exc).__name__
                )
                self.error.emit(str(exc))
                return

            # Warmup: wait for Ollama and pre-load the model into RAM.
            if not self._warm_up_llm(pipeline):
                return

            is_ptt = self.config.input_mode == "ptt"

            while not self._cancelled():
                # PTT mode: wait for the key press before starting the recorder
                if is_ptt:
                    self._prepare_ptt_wait()
                    while not self._cancelled() and not self._ptt_start_event.wait(timeout=0.1):
                        pass
                    if self._cancelled():
                        return

                self.recording_started.emit()
                try:
                    recording = recorder.record(
                        self._cancelled,
                        on_volume=lambda rms: self.volume_level.emit(rms),
                        stop_fn=self._ptt_stop_event.is_set if is_ptt else None,
                    )
                except Exception as exc:
                    log_diagnostic(
                        "turn_failed", stage="capture", error_type=type(exc).__name__
                    )
                    self.error.emit(str(exc))
                    return
                self.recording_finished.emit(recording.stop_reason, recording.duration_sec)

                if recording.stop_reason == "cancelled" or self._cancelled():
                    return
                samples = recording.samples
                if not samples.size:
                    self.error.emit("Didn't catch that. Please try again.")
                    self.ready.emit()
                    continue

                self._barge_in = False
                self._playback_active = False
                started = time.monotonic()

                try:
                    confirm_fn = self._make_confirm_fn() if self.config.review_transcript else None
                    result = pipeline.run(
                        samples, self.context, self._emit_progress,
                        self._cancelled_or_barge_in,
                        confirm_fn=confirm_fn,
                    )
                    if result:
                        self.turn_completed.emit(result, int((time.monotonic() - started) * 1000))
                except TurnCancelled:
                    self._playback_active = False
                    if self._barge_in and not self.isInterruptionRequested():
                        # User started speaking during playback: restart recording immediately
                        self._stop_barge_in_detector()
                        self._barge_in = False
                        self.ready.emit()
                        continue
                    return
                except Exception as exc:
                    self.error.emit(str(exc))
                finally:
                    self._playback_active = False
                    self._stop_barge_in_detector()

                self.ready.emit()

        except Exception as exc:
            log_diagnostic(
                "turn_failed", stage="startup", error_type=type(exc).__name__
            )
            self.error.emit(str(exc))
        finally:
            self._stop_barge_in_detector()
