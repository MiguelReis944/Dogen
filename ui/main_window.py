"""Dogen's desktop conversation window and background worker."""

import html
import uuid
from datetime import date

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QKeySequence, QTextCharFormat, QTextCursor, QTextFormat
from PyQt5.QtWidgets import (QAction, QFileDialog, QGroupBox,
                              QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                              QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSplitter,
                              QStackedWidget, QTextEdit, QVBoxLayout, QWidget)

from nlp.feedback import CoachFeedback, parse_reply, strip_coaching_markup
from nlp.llm import SCENARIOS, ConversationContext, build_system_prompt
from pipeline import TurnCancelled
from storage.progress import ProgressService
from ui.pet_widget import PetWidget
from ui.progress_dialog import ProgressDialog
from ui.session_summary_dialog import SessionSummaryDialog
from ui.settings_dialog import SettingsDialog
from ui.setup_wizard import SetupWizard
from ui.vocab_dialog import VocabDialog
from ui.dogen_logo import apply_dogen_window_icon, apply_hud_title_bar
from ui.conversation_worker import ConversationWorker
from ui.lifecycle import CaptureState, transition
from utils.diagnostics import (
    configure_local_diagnostics,
    disable_local_diagnostics,
    local_diagnostics_path,
    log_diagnostic,
)
from utils.config import save_config

FEMALE_VOICE_MODEL = "tts_models/en/ljspeech/tacotron2-DDC"

# How many pixels of RMS maps to 100% on the level meter
_VOL_SCALE = 600


class ModelFetcher(QThread):
    """Queries Ollama for available models without blocking the UI."""
    models_ready = pyqtSignal(object, object, str)

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host

    def run(self):
        try:
            import ollama
            client = ollama.Client(host=self.host)
            response = client.list()
            models = (
                response.models if hasattr(response, "models")
                else response.get("models", [])
            )
            names = sorted(
                (m.model if hasattr(m, "model") else m.get("model", "")) for m in models
            )
        except Exception as exc:
            self.models_ready.emit([], [], f"Could not connect to Ollama: {exc}")
            return

        try:
            response = client.ps()
            models = (
                response.models if hasattr(response, "models")
                else response.get("models", [])
            )
            resident = []
            for model in models:
                if isinstance(model, dict):
                    name = model.get("name") or model.get("model") or ""
                    size_vram = model.get("size_vram", 0)
                else:
                    name = getattr(model, "name", None) or getattr(model, "model", "")
                    size_vram = getattr(model, "size_vram", 0)
                if name:
                    resident.append({"name": name, "size_vram": int(size_vram or 0)})
            self.models_ready.emit([n for n in names if n], resident, "")
        except Exception as exc:
            self.models_ready.emit(
                [n for n in names if n], [],
                f"Could not read Ollama's resident-model status: {exc}",
            )


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
            log_diagnostic(
                "turn_failed", stage="playback", error_type=type(exc).__name__
            )
            self.error.emit(str(exc))


# ── MainWindow ──────────────────────────────────────────────────────────────────


class MainWindow(QMainWindow):
    def __init__(self, config, db, context, session_id, settings_path=None,
                 auto_start=True, start_maximized=True):
        super().__init__()
        base_font = QFont("Segoe UI")
        base_font.setPixelSize(15)
        self.setFont(base_font)
        self.setWindowTitle("Dogen")
        apply_dogen_window_icon(self)
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
        self._replay_error = None
        self._response_notice = None
        self._restart_after_settings = False
        self._fluency_mode = False
        self._capture_state = CaptureState.READY
        self._configuration_locked = False
        self._model_names = []
        self._current_model = config.ollama_model or ""
        self._loaded_model = None
        self._last_turn_model = None
        self._resident_models = []
        self._model_fetch_error = ""
        self._models_ready = False
        self._speech_ready = False
        self._model_load_pending = False
        self._worker_waiting_for_ptt = False
        self._model_request_on_start = None
        self.status_group = None

        # The focused conversation experience has one supported input and voice.
        self.config.input_mode = "ptt"
        self.config.tts_model = FEMALE_VOICE_MODEL

        self._selected_scenario = next(iter(SCENARIOS))

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
        self.history.setFont(base_font)
        self.history.setReadOnly(True)
        self.history.setPlaceholderText("Your conversation will appear here.")
        content.addWidget(self.history)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(8)

        self.today_group = QGroupBox("Today")
        today_layout = QVBoxLayout(self.today_group)
        self.today = QLabel()
        self.today.setObjectName("todaySummary")
        self.today.setFont(base_font)
        self.today.setWordWrap(True)
        self.today.setToolTip(
            "Recorded time is captured microphone audio (including silence while recording). "
            "Words and fillers are estimated from the final transcript, which may be edited. "
            "Coach corrections are explicit feedback; a practice streak counts a user attempt, "
            "even if the model response was interrupted. Older sessions have no recorded duration."
        )
        today_layout.addWidget(self.today)
        side_layout.addWidget(self.today_group, stretch=1)

        self.fixes_group = QGroupBox("Fixes")
        fixes_layout = QVBoxLayout(self.fixes_group)
        self.fixes = QTextEdit()
        self.fixes.setObjectName("fixesPanel")
        self.fixes.setReadOnly(True)
        self.fixes.setPlaceholderText("Short corrections for clear English errors will appear here.")
        fixes_layout.addWidget(self.fixes)
        side_layout.addWidget(self.fixes_group, stretch=3)

        self._apply_practice_font_size()

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
        self._review_countdown.setStyleSheet("color: #888; font-size: 12px; min-width: 42px;")
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
        self._review_seconds_left: int | None = None

        self._today_refresh_timer = QTimer(self)
        self._today_refresh_timer.setInterval(60_000)
        self._today_refresh_timer.timeout.connect(self._render_today)
        self._today_refresh_timer.start()

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
            #statusText { font-size: 15px; }
            #sessionStats { color: #91A4B7; font-size: 13px; }
            #loadingStatus { color: #91A4B7; padding-left: 8px; }
            #captureHud { background: #111B26; border: 1px solid #263747; border-radius: 6px; }
            #captureStack { min-height: 28px; }
            #voiceLevel { border: 1px solid #263747; background: #111B26; min-height: 20px; }
            #voiceLevel::chunk { background: #49D887; }
            #recordButton { background: #49D887; color: #08110C; border: none;
                            padding: 8px 16px; font-weight: 600; }
            #recordButton:disabled { background: #263747; color: #91A4B7; }
        """)
        apply_hud_title_bar(self)
        if start_maximized:
            self.setWindowState(self.windowState() | Qt.WindowMaximized)
        if auto_start:
            self._set_capture_state(CaptureState.LOADING, "Starting local models…")
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
        self.file_menu = file_menu

        self.loading_menu_action = QAction("Loading local models…", self)
        self.loading_menu_action.setObjectName("loadingMenuAction")
        self.loading_menu_action.setEnabled(False)
        self.loading_menu_action.setVisible(False)
        self.loading_menu_action.setToolTip(
            "Speech components load automatically. Choose and load an Ollama model separately."
        )
        file_menu.addAction(self.loading_menu_action)

        self.new_session_action = QAction("New session", self)
        self.new_session_action.triggered.connect(self._end_session)
        file_menu.addAction(self.new_session_action)

        self.vocabulary_action = QAction("Vocabulary", self)
        self.vocabulary_action.triggered.connect(self._show_vocab)
        file_menu.addAction(self.vocabulary_action)

        self.progress_action = QAction("Practice progress", self)
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
            action.setChecked(scenario == self._selected_scenario)
            action.triggered.connect(
                lambda checked, name=scenario: self._select_scenario(name)
            )

        self.model_menu = file_menu.addMenu("Model")
        self._rebuild_model_menu()
        self.model_menu.aboutToShow.connect(self._fetch_models)

        file_menu.addSeparator()

        self.settings_action = QAction("Settings", self)
        self.settings_action.setShortcut(QKeySequence("Ctrl+,"))
        self.settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(self.settings_action)

        self.setup_guide_action = QAction("Setup guide…", self)
        self.setup_guide_action.setToolTip(
            "Check speech models and Ollama, or return to first-run setup."
        )
        self.setup_guide_action.triggered.connect(self._open_setup_guide)
        file_menu.addAction(self.setup_guide_action)

        export_action = QAction("Export session", self)
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
        elif (
            self._speech_ready and self._current_model
            and self._loaded_model != self._current_model
        ):
            self._load_selected_model()
        elif self._capture_state == "ready" and self.worker and self.worker.isRunning():
            self.worker.begin_ptt()
            self.record_button.setEnabled(False)
            self.record_button.setText("Starting…")
        elif not (self.worker and self.worker.isRunning()):
            self._load_selected_model()

    # ── models ─────────────────────────────────────────────────────────────────

    def _fetch_models(self):
        if hasattr(self, "_fetcher") and self._fetcher.isRunning():
            return
        self._fetcher = ModelFetcher(self.config.ollama_host, self)
        self._fetcher.models_ready.connect(self._on_models_ready)
        self._fetcher.start()

    def _restore_model_preference(self):
        saved = self.db.get_setting("last_model")
        preferred = saved or self.config.ollama_model
        resolved = self._match_model_name(preferred)
        self._current_model = resolved or (
            self._model_names[0] if self._model_names else ""
        )

    def _match_model_name(self, preferred):
        if preferred in self._model_names:
            return preferred
        if preferred and ":" not in preferred:
            return next(
                (name for name in self._model_names if name.split(":", 1)[0] == preferred),
                None,
            )
        return None

    def _on_models_ready(self, names, resident_models=(), error=""):
        self._models_ready = True
        self._model_names = list(names or [])
        self._resident_models = list(resident_models or [])
        self._model_fetch_error = error or ""
        self._restore_model_preference()
        self._rebuild_model_menu()
        self._update_model_controls()
        if not self._model_names:
            self._set_status(error or "No Ollama models are installed. Install a model, then refresh this list.")

    def _rebuild_model_menu(self):
        if not hasattr(self, "model_menu"):
            return
        self.model_menu.clear()
        self.model_selected_status = self.model_menu.addAction("")
        self.model_selected_status.setEnabled(False)
        self.model_runtime_status = self.model_menu.addAction("")
        self.model_runtime_status.setEnabled(False)
        self.model_last_turn_status = self.model_menu.addAction("")
        self.model_last_turn_status.setEnabled(False)
        self.model_resident_status = self.model_menu.addAction("")
        self.model_resident_status.setEnabled(False)
        self.model_menu.addSeparator()

        if not self._model_names:
            empty = self.model_menu.addAction(
                "Loading installed models…" if not self._models_ready
                else "No Ollama models found"
            )
            empty.setEnabled(False)
        for name in self._model_names:
            action = self.model_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(name == self._current_model)
            action.triggered.connect(lambda checked, value=name: self._select_model(value))
        self.model_menu.addSeparator()
        self.load_model_action = self.model_menu.addAction("Load selected model")
        self.load_model_action.setToolTip(
            "Loads only after you choose it. Switching releases the previous Dogen model "
            "from the shared Ollama service; another app using that same model may reload it."
        )
        self.load_model_action.triggered.connect(self._load_selected_model_action)
        self.unload_other_models_action = self.model_menu.addAction(
            "Unload other models and load selected…"
        )
        self.unload_other_models_action.triggered.connect(self._confirm_unload_other_models)
        self.refresh_models_action = self.model_menu.addAction("Refresh model list")
        self.refresh_models_action.triggered.connect(self._fetch_models)
        self._update_model_menu_status()
        self._update_model_controls()

    def _update_model_menu_status(self):
        if not hasattr(self, "model_selected_status"):
            return
        selected = self._current_model or "none"
        self.model_selected_status.setText(f"Selected: {selected}")
        self.model_runtime_status.setText(
            f"Dogen will use: {self._loaded_model or 'not loaded'}"
        )
        self.model_runtime_status.setToolTip(
            "The model assigned to Dogen for its next response. Ollama may release it "
            "after five minutes without a request."
        )
        self.model_last_turn_status.setText(
            f"Last response used: {self._last_turn_model or 'none this session'}"
        )
        total_vram = sum(
            max(0, int(model.get("size_vram", 0) or 0))
            for model in self._resident_models
        )
        if self._model_fetch_error and self._models_ready:
            memory_text = "Ollama memory: status unavailable"
            memory_tooltip = self._model_fetch_error
        elif self._models_ready:
            memory_text = f"Ollama VRAM: {total_vram / 1_000_000_000:.1f} GB shared"
            resident_names = ", ".join(
                model.get("name", "") for model in self._resident_models
            ) or "none"
            memory_tooltip = (
                f"Resident models: {resident_names}. This is shared Ollama GPU usage, "
                "not a per-application measurement."
            )
        else:
            memory_text = "Ollama VRAM: checking…"
            memory_tooltip = "Checking which models are currently resident in Ollama."
        self.model_resident_status.setText(memory_text)
        self.model_resident_status.setToolTip(memory_tooltip)

    def _update_model_controls(self):
        if not hasattr(self, "model_menu"):
            return
        selecting_allowed = (
            self._models_ready
            and not self._model_load_pending
            and (
                not self._configuration_locked
                or (self._capture_state is CaptureState.LOADING and self._loaded_model is None)
            )
        )
        self.model_menu.setEnabled(selecting_allowed)
        if hasattr(self, "load_model_action"):
            self.load_model_action.setEnabled(
                self._speech_ready and bool(self._current_model)
                and self._current_model in self._model_names
                and not self._model_load_pending
                and not self._configuration_locked
            )
            other_resident = any(
                model.get("name") != self._current_model
                for model in self._resident_models
            )
            self.unload_other_models_action.setEnabled(
                self._speech_ready and bool(self._current_model) and other_resident
                and not self._model_load_pending and not self._configuration_locked
            )
        if not hasattr(self, "record_button"):
            return
        if self._model_load_pending:
            self.record_button.setText("Loading model…")
            self.record_button.setEnabled(False)
        elif self._last_error:
            self.record_button.setText("Unavailable")
            self.record_button.setEnabled(False)
        elif not self._speech_ready:
            self.record_button.setText("Loading speech models…")
            self.record_button.setEnabled(False)
        elif not self._models_ready or not self._current_model:
            self.record_button.setText("Ollama model unavailable")
            self.record_button.setEnabled(False)
        elif self._loaded_model != self._current_model:
            self.record_button.setText("Load selected model")
            self.record_button.setEnabled(not self._configuration_locked)
        elif (
            self._capture_state == CaptureState.READY
            and self.worker and self.worker.isRunning()
            and self._worker_waiting_for_ptt
        ):
            self.record_button.setText("Start recording")
            self.record_button.setEnabled(not self._configuration_locked)
        elif self._capture_state == CaptureState.READY and not (
            self.worker and self.worker.isRunning()
        ):
            self.record_button.setText("Start recording")
            self.record_button.setEnabled(not self._configuration_locked)
        elif self._capture_state == CaptureState.READY:
            self.record_button.setText("Preparing microphone…")
            self.record_button.setEnabled(False)
        self._update_model_menu_status()

    def _select_model(self, name: str):
        if name in self._model_names:
            self._current_model = name
            self._on_model_changed(name)
            self._rebuild_model_menu()

    def _load_selected_model_action(self, checked=False):
        self._load_selected_model()

    def _load_selected_model(self, unload_models=()):
        if (
            not self._current_model
            or self._current_model not in self._model_names
            or not self._speech_ready
            or self._model_load_pending
        ):
            return
        self._model_load_pending = True
        self._configuration_locked = True
        self.loading_menu_action.setText(f"Loading {self._current_model}…")
        self.loading_menu_action.setVisible(True)
        self._set_capture_state(CaptureState.LOADING, f"Loading {self._current_model} into Ollama…")
        self._update_model_controls()
        if self.worker and self.worker.isRunning():
            self.worker.request_model_load(self._current_model, unload_models)
        else:
            self._model_request_on_start = (self._current_model, tuple(unload_models))
            self.start()

    def _confirm_unload_other_models(self, checked=False):
        others = [
            model for model in self._resident_models
            if model.get("name") and model.get("name") != self._current_model
        ]
        if not others:
            self._fetch_models()
            self._set_status("No other Ollama models are currently listed as resident.")
            return
        details = "\n".join(
            f"• {model['name']} ({int(model.get('size_vram', 0) or 0) / 1_000_000_000:.1f} GB VRAM)"
            for model in others
        )
        answer = QMessageBox.question(
            self,
            "Free Ollama VRAM",
            "Ollama is shared by all apps on this computer. Unloading these models may "
            "interrupt another app using them:\n\n"
            f"{details}\n\nUnload them, then load {self._current_model}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._load_selected_model(unload_models=[model["name"] for model in others])

    def _on_speech_ready(self):
        self._speech_ready = True
        self._configuration_locked = False
        self.loading_menu_action.setVisible(False)
        self._set_configuration_enabled(True)
        if self._model_names:
            message = "Choose a model in File → Model, then load it to start."
        else:
            message = self._model_fetch_error or "Waiting for an installed Ollama model."
        self._set_capture_state(CaptureState.READY, message)
        self._update_model_controls()

    def _on_model_loaded(self, name):
        self._loaded_model = name
        self._model_request_on_start = None
        self._update_model_menu_status()
        QTimer.singleShot(500, self._fetch_models)

    def _on_model_unloaded(self, name):
        if self._loaded_model == name:
            self._loaded_model = None
        self._update_model_menu_status()

    def _on_model_load_failed(self, name, message):
        self._model_load_pending = False
        self._model_request_on_start = None
        self.loading_menu_action.setVisible(False)
        self._configuration_locked = False
        self._set_configuration_enabled(True)
        self._set_capture_state(CaptureState.READY, message)
        self._update_model_controls()
        QTimer.singleShot(500, self._fetch_models)

    def _select_scenario(self, name: str):
        if name in SCENARIOS:
            self._selected_scenario = name
            self._on_scenario_changed(name)
            for action in self.scenario_menu.actions():
                action.setChecked(action.text() == name)

    def _on_model_changed(self, name):
        if name:
            self.db.set_setting("last_model", name)

    def _selected_model(self):
        return self._current_model

    # ── flow / scenario ────────────────────────────────────────────────────────

    def _on_flow_toggled(self, fluency_mode: bool):
        self._fluency_mode = fluency_mode
        self._apply_system_prompt()

    def _on_scenario_changed(self, scenario_key: str):
        self._apply_system_prompt()
        self.context.reset(self.context.system_prompt)
        self._render_history()

    def _apply_system_prompt(self):
        scenario = self._selected_scenario
        self.context.system_prompt = build_system_prompt(
            scenario, fluency_mode=self._fluency_mode
        )

    # ── stats ──────────────────────────────────────────────────────────────────

    def _update_stats(self):
        stats = self.db.session_stats(self.session_id)
        if stats["turns"]:
            avg_s = stats["avg_latency_ms"] / 1000
            self.stats_label.setText(f"{stats['turns']} turns · {avg_s:.1f}s avg")
        else:
            self.stats_label.setText("")
        self._render_today()

    def _render_today(self):
        stats = ProgressService(self.db).stats(1, date.today())
        recorded_seconds = int(round(stats.minutes_practiced * 60))
        recorded_time = f"{recorded_seconds // 60}m {recorded_seconds % 60:02d}s"
        filler_text = (
            f"{stats.fillers_per_100_words:.1f}"
            if stats.fillers_per_100_words is not None
            else "Not enough data"
        )
        self.today.setText(
            f"Recorded audio: {recorded_time} / "
            f"{self.config.daily_recording_goal_minutes} min\n"
            f"Words transcribed: {stats.words_transcribed}\n"
            f"Completed turns: {stats.completed_turns}\n"
            f"Fillers / 100 transcribed words: {filler_text}\n"
            f"Coach corrections: {stats.correction_count}\n"
            f"Practice streak: {stats.current_streak}"
        )

    # ── history rendering ──────────────────────────────────────────────────────

    def _format_message(self, role, content, is_complete=True):
        label = "You" if role == "user" else (
            "Dogen (response interrupted)" if not is_complete else "Dogen"
        )
        if role == "assistant":
            content = strip_coaching_markup(content)
        escaped = html.escape(content)
        label_color = "#75baff" if role == "user" else "#58d68d"
        return (
            f'<span style="color:{label_color}"><b>{html.escape(label)}:</b></span> '
            f'<span style="color:#e6edf3">{escaped}</span>'
        )

    def _render_history(self):
        self.history.clear()
        # Scoped to the current session only — a new session must start blank.
        messages = self.db.recent_messages(self.session_id, 200)
        for message in messages:
            self.history.append(self._format_message(
                message.role, message.content, message.is_complete
            ))
        self._render_fixes()
        self._assistant_open = False

    def _render_fixes(self):
        self.fixes.clear()
        rendered = [
            self._format_feedback(feedback)
            for feedback in self.db.feedback_for_session(self.session_id)
        ]
        rendered = [item for item in rendered if item]
        if not rendered:
            self.fixes.setPlainText(
                "No correction yet. Dogen will show a short text correction when your English needs one."
            )
            return
        for item in rendered:
            self.fixes.append(item)

    def _format_feedback(self, feedback: CoachFeedback):
        if not feedback.correction:
            return ""
        accepted = parse_reply(f"[Correction: {feedback.correction}]").feedback
        if accepted.correction:
            return f'<span style="color:#e67e22">{html.escape(accepted.correction)}</span>'
        return ""

    # ── start / stop ───────────────────────────────────────────────────────────

    def _set_configuration_enabled(self, enabled: bool):
        self._configuration_locked = not enabled
        self.new_session_action.setEnabled(enabled)
        self.scenario_menu.setEnabled(enabled)
        self.flow_action.setEnabled(enabled)
        self.settings_action.setEnabled(enabled)
        self._update_model_controls()

    def _set_status(self, text: str):
        state = self._capture_state
        if state is CaptureState.SHUTDOWN:
            return
        if state not in set(CaptureState):
            state = CaptureState.READY
        self._set_capture_state(state, text)

    def _set_capture_state(self, state: CaptureState | str, message: str = ""):
        next_state = transition(self._capture_state, state)
        if next_state != self._capture_state:
            log_diagnostic("state_transition", state=next_state.value)
        if self._capture_state is CaptureState.RECORDING and next_state is not CaptureState.RECORDING:
            self.pet.set_volume(0)
        self._capture_state = next_state
        if message:
            self.status.setText(message)
        self.capture_stack.setCurrentWidget(
            self.volume_bar
            if next_state is CaptureState.RECORDING
            else self.loading_status
        )
        if next_state is not CaptureState.RECORDING:
            self.volume_bar.setValue(0)

    def _render_volume(self, rms: float):
        if self._capture_state != "recording":
            self.volume_bar.setValue(0)
            return
        self.volume_bar.setValue(min(100, max(0, int(rms * _VOL_SCALE))))

    def start(self):
        if self.worker and self.worker.isRunning():
            return
        self._speech_ready = False
        self._worker_waiting_for_ptt = False
        self._set_configuration_enabled(False)
        self.loading_menu_action.setVisible(True)
        self.replay_response_button.setEnabled(False)
        self.worker = ConversationWorker(
            self.config, self.context,
            self._selected_model() or self.config.ollama_model or "mistral",
            self._pipeline, self, active_model=self._loaded_model,
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
        self.worker.speech_ready.connect(self._on_speech_ready)
        self.worker.model_loaded.connect(self._on_model_loaded)
        self.worker.model_unloaded.connect(self._on_model_unloaded)
        self.worker.model_load_failed.connect(self._on_model_load_failed)
        self.worker.ready.connect(self._on_ready)
        self.worker.turn_completed.connect(self._on_completed)
        self.worker.finished.connect(self._on_finished)
        self.worker.volume_level.connect(self._on_volume)
        self.worker.speech_level.connect(self.pet.set_volume)
        self._set_capture_state("loading")
        self.record_button.setEnabled(False)
        self.record_button.setText("Loading…")
        self._last_error = None
        self._set_capture_state(CaptureState.LOADING, "Loading speech models…")
        self._update_model_controls()
        self.record_button.setText("Loading speech models…")
        self.record_button.setEnabled(False)
        self._set_status("Loading speech models…")
        if self._model_request_on_start:
            model, unload_models = self._model_request_on_start
            self.worker.request_model_load(model, unload_models)
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
        self._worker_waiting_for_ptt = False
        self._set_configuration_enabled(False)
        self.loading_menu_action.setVisible(False)
        self._last_error = None
        self._replay_error = None
        self._response_notice = None
        self._set_capture_state("recording")
        self.pet.set_state("listening")
        self.replay_response_button.setEnabled(False)
        self.stop_audio_button.setEnabled(False)
        self.record_button.setText("Finish recording")
        self.record_button.setEnabled(True)
        self._set_capture_state("recording", "Recording — click Finish recording when you're done")

    def _on_recording_finished(self, stop_reason: str, duration_sec: float):
        log_diagnostic(
            "recording_finished",
            stop_reason=stop_reason,
            duration_ms=int(duration_sec * 1000),
        )
        try:
            self.db.add_recording_duration(self.session_id, duration_sec)
            self._render_today()
        except Exception as exc:
            log_diagnostic(
                "persistence_error", stage="storage", error_type=type(exc).__name__
            )
        self._set_capture_state("processing")
        self.record_button.setText("Processing…")
        self.record_button.setEnabled(False)
        self._set_status(f"Captured {duration_sec:.1f}s · {stop_reason}")

    def _on_waiting_for_ptt(self):
        self.loading_menu_action.setVisible(False)
        self._model_load_pending = False
        self._worker_waiting_for_ptt = True
        self._set_configuration_enabled(True)
        self._set_capture_state("ready")
        self.pet.set_state("idle")
        pipeline = self._pipeline or getattr(self.worker, "built_pipeline", None)
        self.replay_response_button.setEnabled(bool(self._last_assistant_text and pipeline))
        self.stop_audio_button.setEnabled(False)
        self.record_button.setText("Start recording")
        self.record_button.setEnabled(True)
        self._set_capture_state(
            "ready", self._response_notice or
            f"Ready — {self._loaded_model}; click Start recording to speak"
        )
        self._update_model_controls()

    def _on_volume(self, rms: float):
        self._render_volume(rms)
        if self._capture_state == "recording":
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
            self._set_status(self._response_notice or self._idle_instruction())

    def _on_transcript_review(self, text: str):
        """Show the editable transcript and its configured auto-send behavior."""
        self._review_edit.setText(text)
        self._review_bar.setVisible(True)
        self._review_edit.setFocus()
        self._review_edit.selectAll()
        auto_send_seconds = getattr(self.config, "review_transcript_auto_send_seconds", 15)
        if auto_send_seconds in (10, 15, 30):
            self._review_seconds_left = auto_send_seconds
            self._review_countdown.setText(f"{auto_send_seconds}s")
            self._review_timer.start()
            self._set_status(
                f"Edit the transcript, then send or retry · sending in {auto_send_seconds}s"
            )
        else:
            self._review_timer.stop()
            self._review_seconds_left = None
            self._review_countdown.setText("Never")
            self._set_status(
                "Review the transcript, then send or retry · automatic sending is off"
            )

    def _review_tick(self):
        if self._review_seconds_left is None:
            self._review_timer.stop()
            self._review_countdown.setText("Never")
            return
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
        self.history.append(self._format_message("user", text))
        self._append_role_label("Dogen", "#58d68d")
        self._assistant_open = True
        self.pet.set_state("thinking")
        self._set_capture_state("processing")
        self._set_status("Thinking...")

    def _on_chunk(self, text):
        self._append(text)

    def _on_error(self, text):
        self.loading_menu_action.setVisible(False)
        if self._assistant_open:
            self._render_history()
        self._last_error = text
        self.pet.set_state("idle")
        self._set_capture_state("error")
        self._set_status(text)

    def _on_completed(self, result, latency_ms):
        trace_id = getattr(result, "trace_id", None)
        if result.is_complete:
            log_diagnostic(
                "turn_finished", duration_ms=latency_ms, trace_id=trace_id
            )
        elif getattr(result, "failure_stage", None) == "tts":
            log_diagnostic(
                "turn_interrupted", stage="tts", error_type="PlaybackInterrupted",
                trace_id=trace_id,
            )
        else:
            log_diagnostic(
                "turn_failed",
                stage=getattr(result, "failure_stage", None) or "model",
                error_type="InterruptedStream",
                trace_id=trace_id,
            )
        try:
            model_used = self._loaded_model or "unknown"
            self._last_turn_model = model_used
            self._update_model_menu_status()
            if result.is_complete:
                self.db.add_completed_turn(
                    self.session_id,
                    result.transcript,
                    result.reply,
                    model_used,
                    latency_ms,
                    result.feedback,
                    result.metrics,
                )
                self._last_assistant_text = result.reply
                self._response_notice = (
                    f"Response saved, but audio playback failed: {result.audio_error}"
                    if result.audio_error else None
                )
            else:
                self.db.add_interrupted_turn(
                    self.session_id,
                    result.transcript,
                    result.reply,
                    model_used,
                    latency_ms,
                    result.feedback,
                )
                self._last_assistant_text = result.reply
                self._response_notice = (
                    "Response interrupted and saved: "
                    + (result.error or "the model stream ended unexpectedly")
                )
            self._render_history()
            self._update_stats()
            self._last_error = None
        except Exception as exc:
            log_diagnostic(
                "persistence_error", stage="storage", error_type=type(exc).__name__,
                trace_id=trace_id,
            )
            if len(self.context.messages) >= 2:
                del self.context.messages[-2:]
            self._render_history()
            self._last_error = f"Could not save turn: {exc}"
            self._set_status(f"Could not save turn: {exc}")

    def _on_finished(self):
        self.loading_menu_action.setVisible(False)
        if self.worker and self.worker.built_pipeline and not self._restart_after_settings:
            self._pipeline = self.worker.built_pipeline
        if self._assistant_open:
            self._render_history()
        self._set_capture_state("error" if self._last_error else "ready")
        self.pet.set_state("idle")
        if self._last_error is None:
            self._speech_ready = bool(self.worker and self.worker.built_pipeline)
            self.record_button.setEnabled(True)
            self.record_button.setText("Start recording")
        else:
            self.record_button.setEnabled(False)
            self.record_button.setText("Unavailable")
        self._set_configuration_enabled(True)
        self.stop_audio_button.setEnabled(False)
        self.replay_response_button.setEnabled(bool(self._last_assistant_text and self._pipeline))
        if self._last_error is None:
            self._set_status(
                self._response_notice or (
                    f"Ready — {self._loaded_model}; click Start recording to speak"
                    if self._loaded_model else "Choose a model in File → Model, then load it to start."
                )
            )
            self._update_model_controls()
        if self._closing:
            self._restart_after_settings = False
            self.close()
            return
        if self._restart_after_settings:
            self._restart_after_settings = False
            self._pipeline = None
            self.context.max_history = self.config.context_size
            QTimer.singleShot(0, self.start)
            return

    # ── text append ────────────────────────────────────────────────────────────

    def _append_role_label(self, label, color):
        cursor = self.history.textCursor()
        cursor.movePosition(QTextCursor.End)
        neutral = QTextCharFormat()
        neutral.setForeground(self.history.palette().text())
        cursor.insertText("\n", neutral)
        label_format = QTextCharFormat()
        label_format.setForeground(QColor(color))
        label_format.setFontWeight(QFont.Bold)
        cursor.insertText(f"{label}: ", label_format)
        self.history.setTextCursor(cursor)
        self.history.ensureCursorVisible()

    def _append(self, text):
        cursor = self.history.textCursor()
        cursor.movePosition(QTextCursor.End)
        neutral = QTextCharFormat()
        neutral.setForeground(self.history.palette().text())
        cursor.insertText(text, neutral)
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
        self._replay_error = None
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
        self._replay_error = f"Could not play this response: {text}"

    def _on_replay_finished(self):
        self.stop_audio_button.setEnabled(False)
        self.pet.set_state("idle")
        pipeline = self._pipeline or (self.worker.built_pipeline if self.worker else None)
        self.replay_response_button.setEnabled(bool(self._last_assistant_text and pipeline))
        if self._last_error:
            self._set_capture_state("error", self._last_error)
            self.record_button.setEnabled(False)
            self.record_button.setText("Unavailable")
        else:
            self._set_capture_state("ready", self._replay_error or self._idle_instruction())

    # ── settings ───────────────────────────────────────────────────────────────

    def _apply_practice_font_size(self):
        size = self.config.practice_font_size_px
        for widget in (self.history, self.today, self.fixes):
            # Update the widget rule before setFont so an existing inline rule
            # cannot force the old size back onto the QTextEdit document.
            widget.setStyleSheet(f"font-size: {size}px;")
            font = widget.font()
            font.setPixelSize(size)
            widget.setFont(font)
            if isinstance(widget, QTextEdit):
                widget.document().setDefaultFont(font)
                cursor = widget.textCursor()
                cursor.select(QTextCursor.Document)
                text_format = QTextCharFormat()
                text_format.setProperty(QTextFormat.FontPixelSize, size)
                cursor.mergeCharFormat(text_format)
                cursor.clearSelection()
                widget.setTextCursor(cursor)
                current_format = widget.currentCharFormat()
                current_format.setProperty(QTextFormat.FontPixelSize, size)
                widget.setCurrentCharFormat(current_format)

    def _open_settings(self):
        from pathlib import Path
        path = self.settings_path or Path("settings.json")
        dlg = SettingsDialog(self.config, path, parent=self)
        if dlg.exec_():
            self._apply_practice_font_size()
            if self.config.diagnostics_enabled:
                diagnostics_path = local_diagnostics_path()
                if diagnostics_path is None or not configure_local_diagnostics(
                    diagnostics_path
                ):
                    QMessageBox.warning(
                        self,
                        "Diagnostics unavailable",
                        "Dogen could not create its local diagnostics file. "
                        "The app will continue without recording diagnostics.",
                    )
            else:
                disable_local_diagnostics()
            self.context.max_history = self.config.context_size
            self._render_today()
            self._pipeline = None
            if self.worker and self.worker.isRunning():
                # Recorder and models are owned by the worker; restart it between turns
                # so accepted settings take effect without racing an active capture.
                self._restart_after_settings = True
                self.stop()

    def _show_progress(self):
        ProgressDialog(ProgressService(self.db), parent=self).exec_()

    def _open_setup_guide(self):
        if self._capture_state not in (CaptureState.READY, CaptureState.ERROR):
            QMessageBox.information(
                self,
                "Finish the current turn first",
                "Open the setup guide after recording and response playback are finished.",
            )
            return
        from pathlib import Path

        settings_path = self.settings_path or Path("settings.json")
        dialog = SetupWizard(self.config, self)
        if not dialog.exec_():
            return
        save_config(self.config, settings_path)
        if self.config.ollama_model:
            self.db.set_setting("last_model", self.config.ollama_model)
        if dialog.hide_next_time.isChecked():
            marker_path = settings_path.with_name("first_run_setup_complete")
            marker_path.parent.mkdir(parents=True, exist_ok=True)
            marker_path.touch()
        self._fetch_models()

    # ── session management ─────────────────────────────────────────────────────

    def _end_session(self):
        if self.worker and self.worker.isRunning() and self._capture_state != "ready":
            return
        stats = self.db.session_full_stats(self.session_id)
        dlg = SessionSummaryDialog(stats, parent=self)
        result = dlg.exec_()
        if result == SessionSummaryDialog.NEW_SESSION:
            self.session_id = uuid.uuid4().hex
            self.db.set_setting("session_date", str(date.today()))
            self.db.set_setting("session_id", self.session_id)
            self.context.reset()
            self._pipeline = None
            self._last_assistant_text = ""
            self._response_notice = None
            self.replay_response_button.setEnabled(False)
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
        message_check = self.db.session_messages(self.session_id)
        try:
            first_message = next(message_check, None)
        finally:
            message_check.close()
        if first_message is None:
            notice = "This session has no messages to export."
            QMessageBox.information(self, "Export session", notice)
            self._set_status(notice)
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export session", f"dogen-session-{self.session_id[:8]}.txt",
            "Text files (*.txt);;All files (*)"
        )
        if not path:
            return
        messages = self.db.session_messages(self.session_id)
        try:
            with open(path, "w", encoding="utf-8") as f:
                last_date = None
                for m in messages:
                    date = m.created_at[:10] if m.created_at else ""
                    if date != last_date:
                        f.write(f"\n── {date} ──\n")
                        last_date = date
                    label = "You" if m.role == "user" else (
                        "Dogen (response interrupted)" if not m.is_complete else "Dogen"
                    )
                    f.write(f"{label}: {m.content}\n")
            self.status.setText(f"Exported to {path}")
        except OSError as exc:
            self.status.setText(f"Export failed: {exc}")
        finally:
            messages.close()

    # ── close ──────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._startup_timer and self._startup_timer.isActive():
            self._startup_timer.stop()
        if self.worker and self.worker.isRunning():
            self._closing = True
            self.stop()
            event.ignore()
        else:
            self._set_capture_state(CaptureState.SHUTDOWN)
            event.accept()
