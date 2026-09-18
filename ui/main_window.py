"""Dogen's desktop conversation window and background worker."""

import html
import logging
import re
import time

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QMainWindow,
                              QPushButton, QTextEdit, QVBoxLayout, QWidget)

from audio.player import Player
from audio.recorder import Recorder
from nlp.llm import OllamaClient
from nlp.synthesizer import Synthesizer
from nlp.transcriber import Transcriber
from pipeline import ProcessingPipeline, TurnCancelled

_CORRECTION_RE = re.compile(r'(\[(?:Correction|Better phrasing):.*?\])', re.DOTALL)


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
    status_message = pyqtSignal(str)
    recording_started = pyqtSignal()
    transcribed = pyqtSignal(str)
    response_chunk = pyqtSignal(str)
    audio_playing = pyqtSignal()
    error = pyqtSignal(str)
    ready = pyqtSignal()
    turn_completed = pyqtSignal(str, str, int)

    def __init__(self, config, context, model, pipeline=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.context = context
        self.model = model
        self._prebuilt_pipeline = pipeline
        self.built_pipeline = None

    def _cancelled(self):
        return self.isInterruptionRequested()

    def _emit_progress(self, kind, value):
        if kind == "transcribed":
            self.transcribed.emit(value)
        elif kind == "response_chunk":
            self.response_chunk.emit(value)
        elif kind == "audio_playing":
            self.audio_playing.emit()
        elif kind == "processing":
            self.status_message.emit(value)
        elif kind == "empty":
            self.error.emit(value)

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
                synthesizer = Synthesizer(self.config.tts_model)
                if self._cancelled():
                    return
                pipeline = ProcessingPipeline(
                    transcriber,
                    OllamaClient(self.config.ollama_host, self.model),
                    synthesizer,
                    Player(self.config.speaker_device),
                )
            self.built_pipeline = pipeline
            recorder = Recorder(self.config.mic_device, self.config.vad_threshold,
                                self.config.silence_duration_sec)
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
                # num_predict=0 loads the model into RAM without generating any tokens
                pipeline.llm.client.generate(
                    model=pipeline.llm.model,
                    prompt="",
                    options={"num_predict": 0},
                )
            except Exception:
                pass  # warmup failure is non-fatal
            while not self._cancelled():
                self.recording_started.emit()
                samples = recorder.record(self._cancelled)
                if self._cancelled():
                    return
                if not samples.size:
                    self.error.emit("Didn't catch that. Please try again.")
                    self.ready.emit()
                    continue
                started = time.monotonic()
                try:
                    result = pipeline.run(samples, self.context, self._emit_progress, self._cancelled)
                    if result:
                        self.turn_completed.emit(*result, int((time.monotonic() - started) * 1000))
                except TurnCancelled:
                    return
                except Exception as exc:
                    logging.exception("Conversation turn failed")
                    self.error.emit(str(exc))
                self.ready.emit()
        except Exception as exc:
            logging.exception("Worker startup failed")
            self.error.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self, config, db, context, session_id):
        super().__init__()
        self.setWindowTitle("Dogen")
        self.resize(760, 600)
        self.config = config
        self.db = db
        self.context = context
        self.session_id = session_id
        self.worker = None
        self._pipeline = None  # cached across Stop/Start cycles
        self._assistant_open = False
        self._closing = False
        self._last_error = None

        body = QWidget()
        layout = QVBoxLayout(body)

        top_row = QHBoxLayout()
        self.status = QLabel("Ready")
        top_row.addWidget(self.status, stretch=1)
        top_row.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(180)
        if config.ollama_model:
            self.model_combo.addItem(config.ollama_model)
        self.model_combo.setEnabled(False)
        top_row.addWidget(self.model_combo)
        layout.addLayout(top_row)

        self.history = QTextEdit()
        self.history.setReadOnly(True)
        layout.addWidget(self.history)

        controls = QHBoxLayout()
        self.start_button = QPushButton("Start Recording")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)
        layout.addLayout(controls)

        self.setCentralWidget(body)
        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self.stop)
        self._render_history()
        self._fetch_models()

    def _fetch_models(self):
        self._fetcher = ModelFetcher(self.config.ollama_host, self)
        self._fetcher.models_ready.connect(self._on_models_ready)
        self._fetcher.start()

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

    def _selected_model(self):
        return self.model_combo.currentText() or self.config.ollama_model or "mistral"

    def _format_message(self, role, content):
        label = "You" if role == "user" else "Dogen"
        escaped = html.escape(content)
        if role == "assistant":
            def _colorize(m):
                tag = m.group(1)
                color = "#e67e22" if tag.startswith("[Correction:") else "#27ae60"
                return f'<span style="color:{color}">{tag}</span>'
            escaped = _CORRECTION_RE.sub(_colorize, escaped)
        return f"<b>{label}:</b> {escaped}"

    def _render_history(self):
        self.history.clear()
        for message in self.db.recent_messages(self.session_id, 2 * self.context.max_history):
            self.history.append(self._format_message(message.role, message.content))
        self._assistant_open = False

    def start(self):
        if self.worker and self.worker.isRunning():
            return
        self.model_combo.setEnabled(False)
        self.worker = ConversationWorker(
            self.config, self.context, self._selected_model(), self._pipeline, self
        )
        self.worker.status_message.connect(self.status.setText)
        self.worker.recording_started.connect(self._on_recording_started)
        self.worker.transcribed.connect(self._on_transcribed)
        self.worker.response_chunk.connect(self._on_chunk)
        self.worker.audio_playing.connect(lambda: self.status.setText("Playing audio..."))
        self.worker.error.connect(self._on_error)
        self.worker.ready.connect(self._on_ready)
        self.worker.turn_completed.connect(self._on_completed)
        self.worker.finished.connect(self._on_finished)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self._last_error = None
        self.status.setText("Starting...")
        self.worker.start()

    def _on_recording_started(self):
        self._last_error = None
        self.status.setText("Recording...")

    def _on_ready(self):
        if self._last_error is None:
            self.status.setText("Ready for next turn")

    def stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.status.setText("Stopping...")
            self.stop_button.setEnabled(False)

    def _append(self, text):
        cursor = self.history.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        self.history.setTextCursor(cursor)
        self.history.ensureCursorVisible()

    def _on_transcribed(self, text):
        self.history.append(f"You: {text}")
        self._append("\nDogen: ")
        self._assistant_open = True
        self.status.setText("Thinking...")

    def _on_chunk(self, text):
        self._append(text)

    def _on_error(self, text):
        if self._assistant_open:
            self._render_history()
        self._last_error = text
        self.status.setText(text)

    def _on_completed(self, user_text, assistant_text, latency_ms):
        try:
            self.db.add_turn(self.session_id, user_text, assistant_text,
                             self._selected_model(), latency_ms)
            self._render_history()
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
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.model_combo.setEnabled(True)
        if self._last_error is None:
            self.status.setText("Ready")
        if self._closing:
            self.close()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self._closing = True
            self.stop()
            event.ignore()
        else:
            event.accept()
