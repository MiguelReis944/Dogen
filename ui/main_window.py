"""Dogen's desktop conversation window and background worker."""

import html
import re
import uuid
from datetime import date

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QKeySequence, QTextCursor
from PyQt5.QtWidgets import (QAction, QFileDialog, QGroupBox,
                              QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                              QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSplitter,
                              QStackedWidget, QTextEdit, QVBoxLayout, QWidget)

from nlp.filler_words import highlight_fillers_html
from nlp.feedback import CoachFeedback
from nlp.llm import SCENARIOS, ConversationContext, build_system_prompt
from pipeline import TurnCancelled
from storage.progress import ProgressService
from ui.pet_widget import PetWidget
from ui.progress_dialog import ProgressDialog
from ui.session_summary_dialog import SessionSummaryDialog
from ui.settings_dialog import SettingsDialog
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

FEMALE_VOICE_MODEL = "tts_models/en/ljspeech/tacotron2-DDC"

_CORRECTION_RE = re.compile(r'(\[[A-Z][^:\[\]\n]*:.*?\])', re.DOTALL)

# How many pixels of RMS maps to 100% on the level meter
_VOL_SCALE = 600
_REVIEW_COUNTDOWN_SECONDS = 15


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
        self._record_when_ready = False
        self.status_group = None

        # The focused conversation experience has one supported input and voice.
        self.config.input_mode = "ptt"
        self.config.tts_model = FEMALE_VOICE_MODEL

        self._model_names = [config.ollama_model or "mistral"]
        self._current_model = self._model_names[0]
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
            "Model-dependent options will unlock when startup is complete."
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

        file_menu.addSeparator()

        self.settings_action = QAction("Settings", self)
        self.settings_action.setShortcut(QKeySequence("Ctrl+,"))
        self.settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(self.settings_action)

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
        if saved in self._model_names:
            self._current_model = saved
            self._rebuild_model_menu()

    def _on_models_ready(self, names):
        self._model_names = names or [self._current_model]
        if self._current_model not in self._model_names:
            self._current_model = self._model_names[0]
        self._restore_model_preference()
        self._rebuild_model_menu()
        pipeline = self._pipeline or (self.worker.built_pipeline if self.worker else None)
        if pipeline is not None:
            pipeline.llm.model = self._current_model

    def _rebuild_model_menu(self):
        if not hasattr(self, "model_menu"):
            return
        self.model_menu.clear()
        for name in self._model_names:
            action = self.model_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(name == self._current_model)
            action.triggered.connect(lambda checked, value=name: self._select_model(value))

    def _select_model(self, name: str):
        if name in self._model_names:
            self._current_model = name
            pipeline = self._pipeline or (
                self.worker.built_pipeline if self.worker else None
            )
            if pipeline is not None:
                pipeline.llm.model = name
            self._on_model_changed(name)
            self._rebuild_model_menu()

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
            self.history.append(self._format_message(
                message.role, message.content, message.is_complete
            ))
        self._render_fixes()
        self._assistant_open = False

    def _render_fixes(self):
        self.fixes.clear()
        feedback_items = self.db.feedback_for_session(self.session_id)
        if not feedback_items:
            self.fixes.setPlainText(
                "No correction yet. Dogen will show a short text correction when your English needs one."
            )
            return
        for feedback in feedback_items:
            self.fixes.append(self._format_feedback(feedback))

    def _format_feedback(self, feedback: CoachFeedback):
        lines = []
        if feedback.correction:
            lines.append(f'<span style="color:#e67e22">{html.escape(feedback.correction)}</span>')
        return "<br>".join(lines)

    # ── start / stop ───────────────────────────────────────────────────────────

    def _set_configuration_enabled(self, enabled: bool):
        self.new_session_action.setEnabled(enabled)
        self.model_menu.setEnabled(enabled)
        self.scenario_menu.setEnabled(enabled)
        self.flow_action.setEnabled(enabled)
        self.settings_action.setEnabled(enabled)

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
        self._set_configuration_enabled(False)
        self.loading_menu_action.setVisible(True)
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
        self._set_configuration_enabled(True)
        self._set_capture_state("ready")
        self.pet.set_state("idle")
        pipeline = self._pipeline or getattr(self.worker, "built_pipeline", None)
        self.replay_response_button.setEnabled(bool(self._last_assistant_text and pipeline))
        self.stop_audio_button.setEnabled(False)
        self.record_button.setText("Start recording")
        self.record_button.setEnabled(True)
        self._set_capture_state(
            "ready", self._response_notice or "Ready — click Start recording to speak"
        )
        if self._record_when_ready and self.worker and self.worker.isRunning():
            self._record_when_ready = False
            self.worker.begin_ptt()
            self.record_button.setEnabled(False)
            self.record_button.setText("Starting…")

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
        """Show the editable review bar with a 15-second auto-confirm countdown."""
        self._review_edit.setText(text)
        self._review_seconds_left = _REVIEW_COUNTDOWN_SECONDS
        self._review_countdown.setText(f"{self._review_seconds_left}s")
        self._review_bar.setVisible(True)
        self._review_edit.setFocus()
        self._review_edit.selectAll()
        self._review_timer.start()
        self._set_status(
            f"Edit the transcript, then send or retry · sending in {_REVIEW_COUNTDOWN_SECONDS}s"
        )

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
            if result.is_complete:
                self.db.add_completed_turn(
                    self.session_id,
                    result.transcript,
                    result.reply,
                    self._selected_model(),
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
                    self._selected_model(),
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
            self.record_button.setEnabled(True)
            self.record_button.setText("Start recording")
        else:
            self.record_button.setEnabled(False)
            self.record_button.setText("Unavailable")
        self._set_configuration_enabled(True)
        self.stop_audio_button.setEnabled(False)
        self.replay_response_button.setEnabled(bool(self._last_assistant_text and self._pipeline))
        if self._last_error is None:
            self._set_status(self._response_notice or self._idle_instruction())
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

    def _open_settings(self):
        from pathlib import Path
        path = self.settings_path or Path("settings.json")
        dlg = SettingsDialog(self.config, path, parent=self)
        if dlg.exec_():
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
