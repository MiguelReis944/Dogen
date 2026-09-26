"""Dogen's desktop conversation window and background worker."""

import html
import logging
import re
import threading
import time
import uuid

import numpy as np
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QKeySequence, QTextCursor
from PyQt5.QtWidgets import (QAction, QComboBox, QFileDialog, QHBoxLayout,
                              QLabel, QLineEdit, QMainWindow, QMenuBar,
                              QProgressBar, QPushButton, QTextEdit,
                              QVBoxLayout, QWidget)

from audio.player import Player
from audio.recorder import Recorder
from nlp.filler_words import count_fillers, highlight_fillers_html
from nlp.llm import (SCENARIOS, ConversationContext, OllamaClient,
                     build_system_prompt)
from nlp.synthesizer import Synthesizer
from nlp.transcriber import Transcriber
from pipeline import ProcessingPipeline, TurnCancelled
from ui.pet_widget import PetWidget
from ui.session_summary_dialog import SessionSummaryDialog
from ui.settings_dialog import SettingsDialog
from ui.vocab_dialog import VocabDialog

# Maps voice selector label → Coqui model name.
# Female uses gruut (no system deps). Male uses espeak-ng (needs separate install).
VOICE_MODELS = {
    "♀ Female": "tts_models/en/ljspeech/tacotron2-DDC",
    "♂ Male":   "tts_models/en/sam/tacotron-DDC",
}

_CORRECTION_RE = re.compile(r'(\[[A-Z][^:\[\]\n]*:.*?\])', re.DOTALL)

# How many pixels of RMS maps to 100% on the level meter
_VOL_SCALE = 300


class ModelFetcher(QThread):
    """Queries Ollama for available models without blocking the UI."""
    models_ready = pyqtSignal(list)

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host

    def run(self):
        try:
            import ollama
            response = ollama.Client(host=self.host).list()
            models = response.models if hasattr(response, "models") else response.get("models", [])
            names = sorted(
                (m.model if hasattr(m, "model") else m.get("model", "")) for m in models
            )
            self.models_ready.emit([n for n in names if n])
        except Exception:
            self.models_ready.emit([])


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
    turn_completed    = pyqtSignal(str, str, int)
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

    def confirm_transcript(self, text: str):
        self._confirmed_text = text
        self._confirm_event.set()

    def cancel_transcript(self):
        self._confirmed_text = ""
        self._confirm_event.set()

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
                    while not self._cancelled_or_barge_in():
                        block, _ = stream.read(1600)
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

    # ── progress relay ─────────────────────────────────────────────────────────

    def _emit_progress(self, kind, value):
        if kind == "transcribed":
            self.transcribed.emit(value)
        elif kind == "response_chunk":
            self.response_chunk.emit(value)
        elif kind == "audio_playing":
            self._playback_active = True
            if self._barge_in_thread is None or not self._barge_in_thread.is_alive():
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

    # ── main loop ──────────────────────────────────────────────────────────────

    def run(self):
        try:
            if self._prebuilt_pipeline:
                pipeline = self._prebuilt_pipeline
                pipeline.llm.model = self.model
            else:
                self.status_message.emit("Loading local speech models...")
                transcriber = Transcriber(self.config.whisper_model)
                if self._cancelled():
                    return
                try:
                    synthesizer = Synthesizer(self.config.tts_model)
                    synthesizer._speaker = self.config.tts_speaker
                except FileNotFoundError as exc:
                    msg = str(exc)
                    if "espeak" in msg.lower():
                        self.error.emit(
                            "Male voice needs eSpeak-NG. Install from https://espeak-ng.org/ "
                            "then restart Dogen. Or switch back to ♀ Female."
                        )
                    else:
                        self.error.emit(msg)
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

            recorder = Recorder(
                self.config.mic_device,
                self.config.vad_threshold,
                self.config.silence_duration_sec,
                self.config.noise_reduction,
            )

            # Warmup: wait for Ollama and pre-load the model into RAM
            while not self._cancelled():
                try:
                    pipeline.llm.client.list()
                    break
                except Exception:
                    self.status_message.emit("Waiting for Ollama on localhost:11434...")
                    for _ in range(50):
                        if self._cancelled():
                            return
                        self.msleep(100)
            if self._cancelled():
                return
            self.status_message.emit(f"Loading {pipeline.llm.model} into RAM...")
            try:
                pipeline.llm.client.generate(
                    model=pipeline.llm.model, prompt="", options={"num_predict": 0}
                )
            except Exception:
                pass

            is_ptt = self.config.input_mode == "ptt"

            while not self._cancelled():
                # PTT mode: wait for the key press before starting the recorder
                if is_ptt:
                    self.waiting_for_ptt.emit()
                    self._ptt_start_event.clear()
                    self._ptt_stop_event.clear()
                    while not self._cancelled() and not self._ptt_start_event.wait(timeout=0.1):
                        pass
                    if self._cancelled():
                        return

                self.recording_started.emit()
                recording = recorder.record(
                    self._cancelled,
                    on_volume=lambda rms: self.volume_level.emit(rms),
                    stop_fn=self._ptt_stop_event.is_set if is_ptt else None,
                )
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
                        self.turn_completed.emit(*result, int((time.monotonic() - started) * 1000))
                except TurnCancelled:
                    self._playback_active = False
                    if self._barge_in and not self.isInterruptionRequested():
                        # User started speaking during playback: restart recording immediately
                        self._barge_in = False
                        if self._barge_in_thread:
                            self._barge_in_thread.join(timeout=0.5)
                            self._barge_in_thread = None
                        self.ready.emit()
                        continue
                    return
                except Exception as exc:
                    logging.exception("Conversation turn failed")
                    self.error.emit(str(exc))
                finally:
                    self._playback_active = False

                self.ready.emit()

        except Exception as exc:
            logging.exception("Worker startup failed")
            self.error.emit(str(exc))
        finally:
            if self._barge_in_thread:
                self._barge_in_thread.join(timeout=1)


# ── MainWindow ──────────────────────────────────────────────────────────────────


class MainWindow(QMainWindow):
    def __init__(self, config, db, context, session_id, settings_path=None):
        super().__init__()
        self.setWindowTitle("Dogen")
        self.resize(780, 640)
        self.config = config
        self.db = db
        self.context = context
        self.session_id = session_id
        self.settings_path = settings_path
        self.worker = None
        self._pipeline = None
        self._assistant_open = False
        self._closing = False
        self._last_error = None
        self._corrections_on = True
        self._session_fillers = 0  # running filler word count for current session

        self._build_menu()

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        # ── pet body ───────────────────────────────────────────────────────────
        self.pet = PetWidget()
        self.pet.setMaximumHeight(170)
        layout.addWidget(self.pet)

        # ── top row ────────────────────────────────────────────────────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self.status = QLabel(self._idle_instruction())
        top_row.addWidget(self.status, stretch=1)

        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("color: #888; font-size: 12px;")
        top_row.addWidget(self.stats_label)

        self.flow_btn = QPushButton("Mode: Coaching")
        self.flow_btn.setCheckable(True)
        self.flow_btn.setToolTip(
            "Coaching: Dogen points out grammar mistakes.\n"
            "Fluency: pure conversation, no corrections.\n"
            "Click to switch."
        )
        self.flow_btn.setMinimumWidth(140)
        self.flow_btn.toggled.connect(self._on_flow_toggled)
        top_row.addWidget(self.flow_btn)

        top_row.addWidget(QLabel("Voice:"))
        self.voice_combo = QComboBox()
        self.voice_combo.addItems(list(VOICE_MODELS.keys()))
        self.voice_combo.setMinimumWidth(110)
        self.voice_combo.currentTextChanged.connect(self._on_voice_changed)
        top_row.addWidget(self.voice_combo)

        top_row.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(180)
        if config.ollama_model:
            self.model_combo.addItem(config.ollama_model)
        self.model_combo.setEnabled(False)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        top_row.addWidget(self.model_combo)

        layout.addLayout(top_row)

        # ── volume bar ─────────────────────────────────────────────────────────
        self.vol_bar = QProgressBar()
        self.vol_bar.setRange(0, 100)
        self.vol_bar.setTextVisible(False)
        self.vol_bar.setMaximumHeight(5)
        self.vol_bar.setVisible(False)
        self.vol_bar.setStyleSheet(
            "QProgressBar { border: none; background: #222; border-radius: 2px; }"
            "QProgressBar::chunk { background: #4ade80; border-radius: 2px; }"
        )
        layout.addWidget(self.vol_bar)

        # ── history ────────────────────────────────────────────────────────────
        self.history = QTextEdit()
        self.history.setReadOnly(True)
        layout.addWidget(self.history)

        # ── bottom row ─────────────────────────────────────────────────────────
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)

        bottom_row.addWidget(QLabel("Scenario:"))
        self.scenario_combo = QComboBox()
        self.scenario_combo.addItems(list(SCENARIOS.keys()))
        self.scenario_combo.setMinimumWidth(180)
        self.scenario_combo.currentTextChanged.connect(self._on_scenario_changed)
        bottom_row.addWidget(self.scenario_combo, stretch=1)

        vocab_btn = QPushButton("Vocabulary")
        vocab_btn.setToolTip("Show corrections collected during practice")
        vocab_btn.setMinimumWidth(90)
        vocab_btn.clicked.connect(self._show_vocab)
        bottom_row.addWidget(vocab_btn)

        new_session_btn = QPushButton("New Session")
        new_session_btn.setToolTip("Save a summary of this session and start a fresh, empty chat")
        new_session_btn.setMinimumWidth(120)
        new_session_btn.clicked.connect(self._end_session)
        bottom_row.addWidget(new_session_btn)

        self.start_button = QPushButton("Start Recording")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        bottom_row.addWidget(self.start_button)
        bottom_row.addWidget(self.stop_button)
        layout.addLayout(bottom_row)

        # ── transcript review bar (hidden until review_transcript is on) ───────
        self._review_bar = QWidget()
        review_layout = QHBoxLayout(self._review_bar)
        review_layout.setContentsMargins(0, 2, 0, 2)
        review_layout.setSpacing(6)
        self._review_edit = QLineEdit()
        self._review_edit.setPlaceholderText("Transcript — edit if needed, then press Enter")
        self._review_edit.returnPressed.connect(self._on_confirm_transcript)
        self._review_countdown = QLabel("")
        self._review_countdown.setStyleSheet("color: #888; font-size: 12px; min-width: 28px;")
        confirm_btn = QPushButton("✓ Send")
        confirm_btn.setToolTip("Send this transcript to Dogen now")
        confirm_btn.setMinimumWidth(80)
        confirm_btn.clicked.connect(self._on_confirm_transcript)
        cancel_btn = QPushButton("Retry")
        cancel_btn.setToolTip("Discard this transcript and record the turn again")
        cancel_btn.setMinimumWidth(70)
        cancel_btn.clicked.connect(self._on_cancel_transcript)
        review_layout.addWidget(QLabel("Heard:"))
        review_layout.addWidget(self._review_edit, stretch=1)
        review_layout.addWidget(self._review_countdown)
        review_layout.addWidget(confirm_btn)
        review_layout.addWidget(cancel_btn)
        self._review_bar.setVisible(False)
        layout.addWidget(self._review_bar)

        self._review_timer = QTimer(self)
        self._review_timer.setInterval(1000)
        self._review_timer.timeout.connect(self._review_tick)
        self._review_seconds_left = 0

        self.setCentralWidget(body)
        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self.stop)

        self._render_history()
        self._update_stats()
        self._fetch_models()
        self._restore_model_preference()

    # ── menu ───────────────────────────────────────────────────────────────────

    def _build_menu(self):
        bar = self.menuBar()
        file_menu = bar.addMenu("File")

        settings_action = QAction("Settings…", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)

        file_menu.addSeparator()

        export_action = QAction("Export session…", self)
        export_action.setShortcut(QKeySequence("Ctrl+E"))
        export_action.triggered.connect(self._export_session)
        file_menu.addAction(export_action)

    # ── keyboard shortcuts ─────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        if event.isAutoRepeat():
            super().keyPressEvent(event)
            return
        key = event.key()
        if key == Qt.Key_F2:
            self._toggle_recording()
        elif key == Qt.Key_Space:
            if self.config.input_mode == "ptt":
                self._begin_ptt()
            else:
                self._toggle_recording()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if not event.isAutoRepeat() and event.key() == Qt.Key_Space:
            if self.config.input_mode == "ptt" and self.worker and self.worker.isRunning():
                self.worker.end_ptt()
        super().keyReleaseEvent(event)

    def _toggle_recording(self):
        if self.worker and self.worker.isRunning():
            self.stop()
        elif self.start_button.isEnabled():
            self.start()

    def _begin_ptt(self):
        if not (self.worker and self.worker.isRunning()) and self.start_button.isEnabled():
            self.start()
        if self.worker and self.worker.isRunning():
            self.worker.begin_ptt()

    # ── models ─────────────────────────────────────────────────────────────────

    def _fetch_models(self):
        self._fetcher = ModelFetcher(self.config.ollama_host, self)
        self._fetcher.models_ready.connect(self._on_models_ready)
        self._fetcher.start()

    def _restore_model_preference(self):
        saved = self.db.get_setting("last_model")
        if saved:
            idx = self.model_combo.findText(saved)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
        saved_voice = self.db.get_setting("voice")
        if saved_voice:
            idx = self.voice_combo.findText(saved_voice)
            if idx >= 0:
                self.voice_combo.setCurrentIndex(idx)

    def _on_models_ready(self, names):
        current = self.model_combo.currentText()
        self.model_combo.clear()
        if names:
            self.model_combo.addItems(names)
            idx = self.model_combo.findText(current)
            self.model_combo.setCurrentIndex(max(idx, 0))
            self.model_combo.setEnabled(True)
        else:
            placeholder = current or self.config.ollama_model or "mistral"
            self.model_combo.addItem(placeholder)
            self.model_combo.setEnabled(True)
        self._restore_model_preference()

    def _on_voice_changed(self, label: str):
        model = VOICE_MODELS.get(label)
        if model:
            self.config.tts_model = model
            self._pipeline = None  # force synthesizer reload on next Start
            self.db.set_setting("voice", label)

    def _on_model_changed(self, name):
        if name:
            self.db.set_setting("last_model", name)

    def _selected_model(self):
        return self.model_combo.currentText() or self.config.ollama_model or "mistral"

    # ── flow / scenario ────────────────────────────────────────────────────────

    def _on_flow_toggled(self, fluency_mode: bool):
        self._corrections_on = not fluency_mode
        self.flow_btn.setText("Mode: Fluency" if fluency_mode else "Mode: Coaching")
        self._apply_system_prompt()

    def _on_scenario_changed(self, scenario_key: str):
        self._apply_system_prompt()
        self.context.reset(self.context.system_prompt)
        self._render_history()

    def _apply_system_prompt(self):
        scenario = self.scenario_combo.currentText()
        self.context.system_prompt = build_system_prompt(scenario, corrections=self._corrections_on)

    # ── stats ──────────────────────────────────────────────────────────────────

    def _update_stats(self):
        stats = self.db.session_stats(self.session_id)
        if stats["turns"]:
            avg_s = stats["avg_latency_ms"] / 1000
            self.stats_label.setText(f"{stats['turns']} turns · {avg_s:.1f}s avg")
        else:
            self.stats_label.setText("")

    # ── history rendering ──────────────────────────────────────────────────────

    def _format_message(self, role, content):
        label = "You" if role == "user" else "Dogen"
        escaped = html.escape(content)
        if role == "user":
            escaped = highlight_fillers_html(escaped)
        elif role == "assistant":
            def _colorize(m):
                tag = m.group(1)
                if tag.startswith("[Correction:"):
                    color = "#e67e22"
                elif tag.startswith("[Better phrasing:"):
                    color = "#27ae60"
                else:
                    color = "#3b82f6"
                return f'<span style="color:{color}">{tag}</span>'
            escaped = _CORRECTION_RE.sub(_colorize, escaped)
        return f"<b>{label}:</b> {escaped}"

    def _render_history(self):
        self.history.clear()
        # Scoped to the current session only — a new session must start blank.
        messages = self.db.recent_messages(self.session_id, 200)
        for message in messages:
            self.history.append(self._format_message(message.role, message.content))
        self._assistant_open = False

    # ── start / stop ───────────────────────────────────────────────────────────

    def start(self):
        if self.worker and self.worker.isRunning():
            return
        self.model_combo.setEnabled(False)
        self.voice_combo.setEnabled(False)
        self.scenario_combo.setEnabled(False)
        self.worker = ConversationWorker(
            self.config, self.context, self._selected_model(), self._pipeline, self
        )
        self.worker.status_message.connect(self.status.setText)
        self.worker.recording_started.connect(self._on_recording_started)
        self.worker.recording_finished.connect(self._on_recording_finished)
        self.worker.waiting_for_ptt.connect(self._on_waiting_for_ptt)
        self.worker.transcribed.connect(self._on_transcribed)
        self.worker.transcript_review.connect(self._on_transcript_review)
        self.worker.response_chunk.connect(self._on_chunk)
        self.worker.audio_playing.connect(self._on_audio_playing)
        self.worker.error.connect(self._on_error)
        self.worker.ready.connect(self._on_ready)
        self.worker.turn_completed.connect(self._on_completed)
        self.worker.finished.connect(self._on_finished)
        self.worker.volume_level.connect(self._on_volume)
        self.worker.speech_level.connect(self.pet.set_volume)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self._last_error = None
        self.status.setText("Starting...")
        self.worker.start()

    def stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            if self.config.input_mode == "ptt":
                self.worker.end_ptt()
                self.worker.begin_ptt()  # unblock any waiting
            self.status.setText("Stopping...")
            self.stop_button.setEnabled(False)

    # ── worker signal handlers ─────────────────────────────────────────────────

    def _on_recording_started(self):
        self._last_error = None
        self.vol_bar.setVisible(True)
        self.vol_bar.setValue(0)
        self.pet.set_state("listening")
        label = "Release to send" if self.config.input_mode == "ptt" else "Recording..."
        self.status.setText(label)

    def _on_recording_finished(self, stop_reason: str, duration_sec: float):
        self.status.setText(f"Captured {duration_sec:.1f}s · {stop_reason}")

    def _on_waiting_for_ptt(self):
        self.vol_bar.setVisible(False)
        self.pet.set_state("idle")
        self.status.setText("Hold Space or the microphone button to speak")

    def _on_volume(self, rms: float):
        self.vol_bar.setValue(min(100, int(rms * _VOL_SCALE)))
        self.pet.set_volume(rms)

    def _on_audio_playing(self):
        self.pet.set_state("speaking")
        self.status.setText("Playing audio...")

    def _on_ready(self):
        self.vol_bar.setVisible(False)
        self.pet.set_state("idle")
        if self._last_error is None:
            self.status.setText(self._idle_instruction())

    def _on_transcript_review(self, text: str):
        """Show the editable review bar with a 5-second auto-confirm countdown."""
        self._review_edit.setText(text)
        self._review_seconds_left = 5
        self._review_countdown.setText(f"{self._review_seconds_left}s")
        self._review_bar.setVisible(True)
        self._review_edit.setFocus()
        self._review_edit.selectAll()
        self._review_timer.start()
        self.status.setText("Edit the transcript, then send or retry · sending in 5s")

    def _review_tick(self):
        self._review_seconds_left -= 1
        if self._review_seconds_left <= 0:
            self._on_confirm_transcript()
        else:
            self._review_countdown.setText(f"{self._review_seconds_left}s")

    def _on_confirm_transcript(self):
        self._review_timer.stop()
        self._review_bar.setVisible(False)
        if self.worker and self.worker.isRunning():
            self.worker.confirm_transcript(self._review_edit.text().strip())

    def _on_cancel_transcript(self):
        self._review_timer.stop()
        self._review_bar.setVisible(False)
        if self.worker and self.worker.isRunning():
            self.worker.cancel_transcript()

    def _on_transcribed(self, text):
        fillers = count_fillers(text)
        self._session_fillers += fillers
        self.history.append(f"You: {text}")
        self._append("\nDogen: ")
        self._assistant_open = True
        self.pet.set_state("thinking")
        self.status.setText("Thinking...")

    def _on_chunk(self, text):
        self._append(text)

    def _on_error(self, text):
        if self._assistant_open:
            self._render_history()
        self._last_error = text
        self.pet.set_state("idle")
        self.status.setText(text)

    def _on_completed(self, user_text, assistant_text, latency_ms):
        try:
            self.db.add_turn(self.session_id, user_text, assistant_text,
                             self._selected_model(), latency_ms)
            self._render_history()
            self._update_stats()
            self._last_error = None
        except Exception as exc:
            logging.exception("Could not save conversation turn")
            if len(self.context.messages) >= 2:
                del self.context.messages[-2:]
            self._render_history()
            self._last_error = f"Could not save turn: {exc}"
            self.status.setText(f"Could not save turn: {exc}")

    def _on_finished(self):
        if self.worker and self.worker.built_pipeline:
            self._pipeline = self.worker.built_pipeline
        if self._assistant_open:
            self._render_history()
        self.vol_bar.setVisible(False)
        self.pet.set_state("idle")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.model_combo.setEnabled(True)
        self.voice_combo.setEnabled(True)
        self.scenario_combo.setEnabled(True)
        if self._last_error is None:
            self.status.setText(self._idle_instruction())
        if self._closing:
            self.close()

    # ── text append ────────────────────────────────────────────────────────────

    def _append(self, text):
        cursor = self.history.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        self.history.setTextCursor(cursor)
        self.history.ensureCursorVisible()

    def _idle_instruction(self):
        if self.config.input_mode == "ptt":
            return "Hold Space or the microphone button to speak"
        return "Start speaking; Dogen sends after the selected pause"

    # ── settings ───────────────────────────────────────────────────────────────

    def _open_settings(self):
        from pathlib import Path
        path = self.settings_path or Path("settings.json")
        dlg = SettingsDialog(self.config, path, parent=self)
        if dlg.exec_():
            # Invalidate pipeline so next start picks up new whisper model etc.
            self._pipeline = None

    # ── session management ─────────────────────────────────────────────────────

    def _end_session(self):
        if self.worker and self.worker.isRunning():
            self.stop()
            return
        stats = self.db.session_full_stats(self.session_id)
        stats["fillers"] = self._session_fillers
        dlg = SessionSummaryDialog(stats, parent=self)
        result = dlg.exec_()
        if result == SessionSummaryDialog.NEW_SESSION:
            self.session_id = uuid.uuid4().hex
            self._session_fillers = 0
            self.context.reset()
            self._pipeline = None
            self._render_history()
            self._update_stats()
            self.status.setText("New session started")

    # ── vocab ──────────────────────────────────────────────────────────────────

    def _show_vocab(self):
        items = self.db.get_vocab()
        dlg = VocabDialog(items, on_clear=self._clear_vocab, parent=self)
        dlg.exec_()

    def _clear_vocab(self):
        self.db.clear_vocab()

    # ── export ─────────────────────────────────────────────────────────────────

    def _export_session(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export session", f"dogen-session-{self.session_id[:8]}.txt",
            "Text files (*.txt);;All files (*)"
        )
        if not path:
            return
        messages = self.db.recent_all_messages(10000)
        lines = []
        last_date = None
        for m in messages:
            date = m.created_at[:10] if m.created_at else ""
            if date != last_date:
                lines.append(f"\n── {date} ──\n")
                last_date = date
            label = "You" if m.role == "user" else "Dogen"
            lines.append(f"{label}: {m.content}\n")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            self.status.setText(f"Exported to {path}")
        except OSError as exc:
            self.status.setText(f"Export failed: {exc}")

    # ── close ──────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self._closing = True
            self.stop()
            event.ignore()
        else:
            event.accept()
