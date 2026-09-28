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
from PyQt5.QtWidgets import (QAction, QComboBox, QFileDialog, QGroupBox,
                              QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                              QProgressBar, QPushButton, QSizePolicy, QSplitter,
                              QStackedWidget, QTextEdit, QVBoxLayout, QWidget)

from audio.player import Player
from audio.recorder import Recorder
from nlp.filler_words import highlight_fillers_html
from nlp.feedback import CoachFeedback
from nlp.llm import (SCENARIOS, ConversationContext, OllamaClient,
                     build_system_prompt)
from nlp.synthesizer import Synthesizer
from nlp.transcriber import Transcriber
from pipeline import ProcessingPipeline, TurnCancelled
from storage.progress import ProgressService
from ui.pet_widget import PetWidget
from ui.progress_dialog import ProgressDialog
from ui.session_summary_dialog import SessionSummaryDialog
from ui.settings_dialog import SettingsDialog
from ui.vocab_dialog import VocabDialog

FEMALE_VOICE_MODEL = "tts_models/en/ljspeech/tacotron2-DDC"

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
                model=pipeline.llm.model, prompt="", options={"num_predict": 0}
            )
        except Exception as exc:
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
                transcriber = Transcriber(self.config.whisper_model)
                if self._cancelled():
                    return
                self.status_message.emit("Loading voice…")
                try:
                    synthesizer = Synthesizer(self.config.tts_model)
                    synthesizer._speaker = self.config.tts_speaker
                except FileNotFoundError as exc:
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

            recorder = Recorder(
                self.config.mic_device,
                self.config.vad_threshold,
                self.config.silence_duration_sec,
                self.config.noise_reduction,
            )

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
                        self.turn_completed.emit(result, int((time.monotonic() - started) * 1000))
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


class ReplayWorker(QThread):
    audio_playing = pyqtSignal()
    speech_level = pyqtSignal(float)
    error = pyqtSignal(str)

    def __init__(self, pipeline, text, parent=None):
        super().__init__(parent)
        self.pipeline = pipeline
        self.text = text

    def _emit_progress(self, kind, value):
        if kind == "audio_playing":
            self.audio_playing.emit()
        elif kind == "speech_volume":
            self.speech_level.emit(float(value))

    def run(self):
        try:
            self.pipeline.speak(self.text, self._emit_progress, self.isInterruptionRequested)
        except TurnCancelled:
            pass
        except Exception as exc:
            logging.exception("Response replay failed")
            self.error.emit(str(exc))


# ── MainWindow ──────────────────────────────────────────────────────────────────


class MainWindow(QMainWindow):
    def __init__(self, config, db, context, session_id, settings_path=None,
                 auto_start=True, start_maximized=True):
        super().__init__()
        self.setWindowTitle("Dogen")
        self.setMinimumSize(1100, 700)
        self.resize(1280, 820)
        self.config = config
        self.db = db
        self.context = context
        self.session_id = session_id
        self.settings_path = settings_path
        self.worker = None
        self._pipeline = None
        self._replay_worker = None
        self._last_assistant_text = ""
        self._assistant_open = False
        self._closing = False
        self._startup_timer = None
        self._last_error = None
        self._corrections_on = True
        self._capture_state = "ready"
        self._record_when_ready = False
        self.status_group = None

        # The focused conversation experience has one supported input and voice.
        self.config.input_mode = "ptt"
        self.config.tts_model = FEMALE_VOICE_MODEL

        # These selectors remain as non-visual state holders for the File menu.
        self.model_combo = QComboBox(self)
        if config.ollama_model:
            self.model_combo.addItem(config.ollama_model)
        self.model_combo.setEnabled(False)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        self.model_combo.hide()

        self.scenario_combo = QComboBox(self)
        self.scenario_combo.addItems(list(SCENARIOS.keys()))
        self.scenario_combo.currentTextChanged.connect(self._on_scenario_changed)
        self.scenario_combo.hide()

        self._build_menu()

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)

        # ── pet body ───────────────────────────────────────────────────────────
        self.pet = PetWidget()
        self.pet.setMaximumHeight(170)
        layout.addWidget(self.pet)

        # ── conversation + side information ───────────────────────────────────
        content = QSplitter(Qt.Horizontal)
        self.status = QLabel(self._idle_instruction())
        self.status.setObjectName("statusText")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        self.stats_label = QLabel("")
        self.stats_label.setObjectName("sessionStats")

        self.history = QTextEdit()
        self.history.setObjectName("conversationHistory")
        self.history.setReadOnly(True)
        self.history.setPlaceholderText("Your conversation will appear here.")
        content.addWidget(self.history)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(8)

        self.fixes_group = QGroupBox("Fixes")
        fixes_layout = QVBoxLayout(self.fixes_group)
        self.fixes = QTextEdit()
        self.fixes.setObjectName("fixesPanel")
        self.fixes.setReadOnly(True)
        self.fixes.setPlaceholderText("Corrections and better phrasing will appear here.")
        fixes_layout.addWidget(self.fixes)
        side_layout.addWidget(self.fixes_group, stretch=3)

        side.setMinimumWidth(320)
        side.setMaximumWidth(420)
        content.addWidget(side)
        content.setChildrenCollapsible(False)
        content.setStretchFactor(0, 7)
        content.setStretchFactor(1, 3)
        content.setSizes([680, 300])
        self.history.setMinimumWidth(500)
        layout.addWidget(content, stretch=1)

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

        # ── capture controls ───────────────────────────────────────────────────
        self.capture_hud = QWidget()
        self.capture_hud.setObjectName("captureHud")
        capture_row = QHBoxLayout(self.capture_hud)
        capture_row.setContentsMargins(12, 8, 12, 8)
        capture_row.setSpacing(10)
        self.capture_stack = QStackedWidget()
        self.capture_stack.setObjectName("captureStack")
        self.loading_status = self.status
        self.loading_status.setObjectName("loadingStatus")
        self.loading_status.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.loading_status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.loading_status.setMaximumHeight(46)
        self.volume_bar = QProgressBar()
        self.volume_bar.setObjectName("voiceLevel")
        self.volume_bar.setRange(0, 100)
        self.volume_bar.setTextVisible(False)
        self.volume_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.volume_bar.setMinimumHeight(22)
        self.vol_bar = self.volume_bar
        self.capture_stack.addWidget(self.loading_status)
        self.capture_stack.addWidget(self.volume_bar)
        self.capture_stack.setCurrentWidget(self.loading_status)
        capture_row.addWidget(self.capture_stack, stretch=1)

        self.record_button = QPushButton("Start recording")
        self.record_button.setObjectName("recordButton")
        self.record_button.setMinimumWidth(150)
        capture_row.addWidget(self.record_button)
        layout.addWidget(self.capture_hud)

        self._review_timer = QTimer(self)
        self._review_timer.setInterval(1000)
        self._review_timer.timeout.connect(self._review_tick)
        self._review_seconds_left = 0

        self.setCentralWidget(body)
        self._set_capture_state("ready", self._idle_instruction())
        self.record_button.clicked.connect(self._toggle_recording)

        self._render_history()
        self._update_stats()
        self._fetch_models()
        self._restore_model_preference()
        self.setStyleSheet(self.styleSheet() + """
            QMainWindow, QWidget { background: #0B1118; color: #E8F1F5; }
            QMenuBar, QMenu { background: #111B26; color: #E8F1F5; }
            QMenuBar::item:selected, QMenu::item:selected { background: #263747; }
            QTextEdit { background: #0B1118; border: 1px solid #263747; padding: 8px; }
            QGroupBox { border: 1px solid #263747; margin-top: 10px; padding-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
            #statusText { font-size: 13px; }
            #sessionStats { color: #91A4B7; font-size: 12px; }
            #loadingStatus { color: #91A4B7; padding-left: 8px; }
            #captureHud { background: #111B26; border: 1px solid #263747; border-radius: 6px; }
            #captureStack { min-height: 28px; }
            #voiceLevel { border: 1px solid #263747; background: #111B26; min-height: 20px; }
            #voiceLevel::chunk { background: #49D887; }
            #recordButton { background: #49D887; color: #08110C; border: none;
                            padding: 8px 16px; font-weight: 600; }
            #recordButton:disabled { background: #263747; color: #91A4B7; }
        """)
        if start_maximized:
            self.setWindowState(self.windowState() | Qt.WindowMaximized)
        if auto_start:
            self._capture_state = "loading"
            self.loading_status.setText("Starting local models…")
            self.record_button.setText("Loading…")
            self.record_button.setEnabled(False)
            self._startup_timer = QTimer(self)
            self._startup_timer.setSingleShot(True)
            self._startup_timer.timeout.connect(self.start)
            self._startup_timer.start(0)

    # ── menu ───────────────────────────────────────────────────────────────────

    def _build_menu(self):
        bar = self.menuBar()
        file_menu = bar.addMenu("File")

        self.new_session_action = QAction("New session", self)
        self.new_session_action.triggered.connect(self._end_session)
        file_menu.addAction(self.new_session_action)

        self.vocabulary_action = QAction("Vocabulary…", self)
        self.vocabulary_action.triggered.connect(self._show_vocab)
        file_menu.addAction(self.vocabulary_action)

        self.progress_action = QAction("Progress…", self)
        self.progress_action.setObjectName("progressAction")
        self.progress_action.triggered.connect(self._show_progress)
        file_menu.addAction(self.progress_action)

        file_menu.addSeparator()

        self.replay_response_button = QAction("Replay response", self)
        self.replay_response_button.setObjectName("replayResponseButton")
        self.replay_response_button.setEnabled(False)
        self.replay_response_button.triggered.connect(self._replay_response)
        file_menu.addAction(self.replay_response_button)

        self.stop_audio_button = QAction("Stop audio", self)
        self.stop_audio_button.setObjectName("stopAudioButton")
        self.stop_audio_button.setEnabled(False)
        self.stop_audio_button.triggered.connect(self._stop_audio)
        file_menu.addAction(self.stop_audio_button)

        self.flow_action = QAction("Fluency mode", self)
        self.flow_action.setCheckable(True)
        self.flow_action.toggled.connect(self._on_flow_toggled)
        file_menu.addAction(self.flow_action)

        self.scenario_menu = file_menu.addMenu("Scenario")
        for scenario in SCENARIOS:
            action = self.scenario_menu.addAction(scenario)
            action.setCheckable(True)
            action.setChecked(scenario == self.scenario_combo.currentText())
            action.triggered.connect(
                lambda checked, name=scenario: self._select_scenario(name)
            )

        self.model_menu = file_menu.addMenu("Model")
        self._rebuild_model_menu()

        file_menu.addSeparator()

        self.settings_action = QAction("Settings…", self)
        self.settings_action.setShortcut(QKeySequence("Ctrl+,"))
        self.settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(self.settings_action)

        export_action = QAction("Export session…", self)
        export_action.setShortcut(QKeySequence("Ctrl+E"))
        export_action.triggered.connect(self._export_session)
        file_menu.addAction(export_action)

        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    # ── keyboard shortcuts ─────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        if event.isAutoRepeat():
            super().keyPressEvent(event)
            return
        key = event.key()
        if key in (Qt.Key_F2, Qt.Key_Space):
            self._toggle_recording()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        super().keyReleaseEvent(event)

    def _toggle_recording(self):
        if self._capture_state == "recording" and self.worker and self.worker.isRunning():
            self.worker.end_ptt()
            self.record_button.setEnabled(False)
            self.record_button.setText("Finishing…")
        elif self._capture_state == "ready" and self.worker and self.worker.isRunning():
            self.worker.begin_ptt()
            self.record_button.setEnabled(False)
            self.record_button.setText("Starting…")
        elif not (self.worker and self.worker.isRunning()):
            self._record_when_ready = True
            self.start()

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
        self._rebuild_model_menu()

    def _rebuild_model_menu(self):
        if not hasattr(self, "model_menu"):
            return
        self.model_menu.clear()
        current = self.model_combo.currentText()
        for index in range(self.model_combo.count()):
            name = self.model_combo.itemText(index)
            action = self.model_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(name == current)
            action.triggered.connect(lambda checked, value=name: self._select_model(value))

    def _select_model(self, name: str):
        index = self.model_combo.findText(name)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)
        self._rebuild_model_menu()

    def _select_scenario(self, name: str):
        index = self.scenario_combo.findText(name)
        if index >= 0:
            self.scenario_combo.setCurrentIndex(index)
        for action in self.scenario_menu.actions():
            action.setChecked(action.text() == name)

    def _on_model_changed(self, name):
        if name:
            self.db.set_setting("last_model", name)

    def _selected_model(self):
        return self.model_combo.currentText() or self.config.ollama_model or "mistral"

    # ── flow / scenario ────────────────────────────────────────────────────────

    def _on_flow_toggled(self, fluency_mode: bool):
        self._corrections_on = not fluency_mode
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
        self._render_fixes()
        self._assistant_open = False

    def _render_fixes(self):
        self.fixes.clear()
        for feedback in self.db.feedback_for_session(self.session_id):
            self.fixes.append(self._format_feedback(feedback))

    def _format_feedback(self, feedback: CoachFeedback):
        lines = ["<b>Coach feedback</b>"]
        if feedback.correction:
            lines.append(f'<span style="color:#e67e22">Correction: {html.escape(feedback.correction)}</span>')
        if feedback.better_phrasing:
            lines.append(
                f'<span style="color:#27ae60">Better phrasing: '
                f'{html.escape(feedback.better_phrasing)}</span>'
            )
        if feedback.category:
            lines.append(f"Category: {html.escape(feedback.category.replace('_', ' '))}")
        return "<br>".join(lines)

    # ── start / stop ───────────────────────────────────────────────────────────

    def _set_configuration_enabled(self, enabled: bool):
        self.model_combo.setEnabled(enabled)
        self.scenario_combo.setEnabled(enabled)
        self.model_menu.setEnabled(enabled)
        self.scenario_menu.setEnabled(enabled)
        self.flow_action.setEnabled(enabled)
        self.settings_action.setEnabled(enabled)

    def _set_status(self, text: str):
        state = self._capture_state
        if state not in {"loading", "ready", "recording", "processing", "error"}:
            state = "ready"
        self._set_capture_state(state, text)

    def _set_capture_state(self, state: str, message: str = ""):
        if state not in {"loading", "ready", "recording", "processing", "error"}:
            raise ValueError(f"Unknown capture state: {state}")
        self._capture_state = state
        if message:
            self.status.setText(message)
        self.capture_stack.setCurrentWidget(
            self.volume_bar if state == "recording" else self.loading_status
        )
        if state != "recording":
            self.volume_bar.setValue(0)

    def _render_volume(self, rms: float):
        if self._capture_state != "recording":
            self.volume_bar.setValue(0)
            return
        self.volume_bar.setValue(min(100, max(0, int(rms * _VOL_SCALE))))

    def start(self):
        if self.worker and self.worker.isRunning():
            return
        self._set_configuration_enabled(False)
        self.replay_response_button.setEnabled(False)
        self.worker = ConversationWorker(
            self.config, self.context, self._selected_model(), self._pipeline, self
        )
        self.worker.status_message.connect(self._set_status)
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
        self._set_capture_state("loading")
        self.record_button.setEnabled(False)
        self.record_button.setText("Loading…")
        self._last_error = None
        self._set_status("Starting...")
        self.worker.start()

    def stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            if self.config.input_mode == "ptt":
                self.worker.end_ptt()
                self.worker.begin_ptt()  # unblock any waiting
            self._set_status("Stopping...")

    # ── worker signal handlers ─────────────────────────────────────────────────

    def _on_recording_started(self):
        self._last_error = None
        self._set_capture_state("recording")
        self.pet.set_state("listening")
        self.replay_response_button.setEnabled(False)
        self.stop_audio_button.setEnabled(False)
        self.record_button.setText("Finish recording")
        self.record_button.setEnabled(True)
        self._set_capture_state("recording", "Recording — click Finish recording when you're done")

    def _on_recording_finished(self, stop_reason: str, duration_sec: float):
        self._set_capture_state("processing")
        self.record_button.setText("Processing…")
        self.record_button.setEnabled(False)
        self._set_status(f"Captured {duration_sec:.1f}s · {stop_reason}")

    def _on_waiting_for_ptt(self):
        self._set_capture_state("ready")
        self.pet.set_state("idle")
        pipeline = self._pipeline or getattr(self.worker, "built_pipeline", None)
        self.replay_response_button.setEnabled(bool(self._last_assistant_text and pipeline))
        self.stop_audio_button.setEnabled(False)
        self.record_button.setText("Start recording")
        self.record_button.setEnabled(True)
        self._set_capture_state("ready", "Ready — click Start recording to speak")
        if self._record_when_ready and self.worker and self.worker.isRunning():
            self._record_when_ready = False
            self.worker.begin_ptt()
            self.record_button.setEnabled(False)
            self.record_button.setText("Starting…")

    def _on_volume(self, rms: float):
        self._render_volume(rms)
        self.pet.set_volume(rms)

    def _on_audio_playing(self):
        self.pet.set_state("speaking")
        self._set_capture_state("processing", "Playing audio...")
        self.replay_response_button.setEnabled(False)
        self.stop_audio_button.setEnabled(True)

    def _on_ready(self):
        self.pet.set_state("idle")
        self.stop_audio_button.setEnabled(False)
        if self._last_error is None:
            self._set_status(self._idle_instruction())

    def _on_transcript_review(self, text: str):
        """Show the editable review bar with a 5-second auto-confirm countdown."""
        self._review_edit.setText(text)
        self._review_seconds_left = 5
        self._review_countdown.setText(f"{self._review_seconds_left}s")
        self._review_bar.setVisible(True)
        self._review_edit.setFocus()
        self._review_edit.selectAll()
        self._review_timer.start()
        self._set_status("Edit the transcript, then send or retry · sending in 5s")

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
        self.history.append(f"You: {text}")
        self._append("\nDogen: ")
        self._assistant_open = True
        self.pet.set_state("thinking")
        self._set_capture_state("processing")
        self._set_status("Thinking...")

    def _on_chunk(self, text):
        self._append(text)

    def _on_error(self, text):
        if self._assistant_open:
            self._render_history()
        self._last_error = text
        self.pet.set_state("idle")
        self._set_capture_state("error")
        self._set_status(text)

    def _on_completed(self, result, latency_ms):
        try:
            self.db.add_completed_turn(
                self.session_id,
                result.transcript,
                result.reply,
                self._selected_model(),
                latency_ms,
                result.feedback,
                result.metrics,
            )
            self._render_history()
            self._update_stats()
            self._last_assistant_text = result.reply
            self._last_error = None
        except Exception as exc:
            logging.exception("Could not save conversation turn")
            if len(self.context.messages) >= 2:
                del self.context.messages[-2:]
            self._render_history()
            self._last_error = f"Could not save turn: {exc}"
            self._set_status(f"Could not save turn: {exc}")

    def _on_finished(self):
        if self.worker and self.worker.built_pipeline:
            self._pipeline = self.worker.built_pipeline
        if self._assistant_open:
            self._render_history()
        self._set_capture_state("error" if self._last_error else "ready")
        self.pet.set_state("idle")
        if self._last_error is None:
            self.record_button.setEnabled(True)
            self.record_button.setText("Start recording")
        else:
            self.record_button.setEnabled(False)
            self.record_button.setText("Unavailable")
        self._set_configuration_enabled(True)
        self.stop_audio_button.setEnabled(False)
        self.replay_response_button.setEnabled(bool(self._last_assistant_text and self._pipeline))
        if self._last_error is None:
            self._set_status(self._idle_instruction())
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
        return "Ready — click Start recording to speak"

    def _replay_response(self):
        pipeline = self._pipeline or (self.worker.built_pipeline if self.worker else None)
        if not self._last_assistant_text or pipeline is None:
            return
        if self._replay_worker and self._replay_worker.isRunning():
            return
        self.replay_response_button.setEnabled(False)
        self._replay_worker = ReplayWorker(pipeline, self._last_assistant_text, self)
        self._replay_worker.audio_playing.connect(self._on_audio_playing)
        self._replay_worker.speech_level.connect(self.pet.set_volume)
        self._replay_worker.error.connect(self._on_replay_error)
        self._replay_worker.finished.connect(self._on_replay_finished)
        self._replay_worker.start()

    def _stop_audio(self):
        if self._replay_worker and self._replay_worker.isRunning():
            self._replay_worker.requestInterruption()
        if self.worker and self.worker.isRunning():
            self.worker.stop_playback()
        self.stop_audio_button.setEnabled(False)

    def _on_replay_error(self, text):
        self._last_error = f"Could not play this response: {text}"
        self._set_status(self._last_error)

    def _on_replay_finished(self):
        self.stop_audio_button.setEnabled(False)
        self.pet.set_state("idle")
        pipeline = self._pipeline or (self.worker.built_pipeline if self.worker else None)
        self.replay_response_button.setEnabled(bool(self._last_assistant_text and pipeline))
        state = "error" if self._last_error else "ready"
        self._set_capture_state(state, self._last_error or self._idle_instruction())

    # ── settings ───────────────────────────────────────────────────────────────

    def _open_settings(self):
        from pathlib import Path
        path = self.settings_path or Path("settings.json")
        dlg = SettingsDialog(self.config, path, parent=self)
        if dlg.exec_():
            # Invalidate pipeline so next start picks up new whisper model etc.
            self._pipeline = None

    def _show_progress(self):
        ProgressDialog(ProgressService(self.db), parent=self).exec_()

    # ── session management ─────────────────────────────────────────────────────

    def _end_session(self):
        if self.worker and self.worker.isRunning():
            self.stop()
            return
        stats = self.db.session_full_stats(self.session_id)
        dlg = SessionSummaryDialog(stats, parent=self)
        result = dlg.exec_()
        if result == SessionSummaryDialog.NEW_SESSION:
            self.session_id = uuid.uuid4().hex
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
        if self._startup_timer and self._startup_timer.isActive():
            self._startup_timer.stop()
        if self.worker and self.worker.isRunning():
            self._closing = True
            self.stop()
            event.ignore()
        else:
            event.accept()
