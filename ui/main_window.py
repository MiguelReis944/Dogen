"""Dogen's desktop conversation window and background worker."""

import logging
import time

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QPushButton, QTextEdit, QVBoxLayout, QWidget

from audio.player import Player
from audio.recorder import Recorder
from nlp.llm import OllamaClient
from nlp.synthesizer import Synthesizer
from nlp.transcriber import Transcriber
from pipeline import ProcessingPipeline, TurnCancelled


class ConversationWorker(QThread):
    recording_started = pyqtSignal()
    transcribed = pyqtSignal(str)
    response_chunk = pyqtSignal(str)
    audio_playing = pyqtSignal()
    error = pyqtSignal(str)
    ready = pyqtSignal()
    turn_completed = pyqtSignal(str, str, int)

    def __init__(self, config, context, parent=None):
        super().__init__(parent)
        self.config = config
        self.context = context

    def _cancelled(self):
        return self.isInterruptionRequested()

    def _emit_progress(self, kind, value):
        if kind == "transcribed":
            self.transcribed.emit(value)
        elif kind == "response_chunk":
            self.response_chunk.emit(value)
        elif kind == "audio_playing":
            self.audio_playing.emit()
        elif kind == "empty":
            self.error.emit(value)

    def run(self):
        try:
            self.error.emit("Loading local speech models...")
            pipeline = ProcessingPipeline(
                Transcriber(self.config.whisper_model),
                OllamaClient(self.config.ollama_host, self.config.ollama_model),
                Synthesizer(self.config.tts_model),
                Player(self.config.speaker_device),
            )
            recorder = Recorder(self.config.mic_device, self.config.vad_threshold,
                                self.config.silence_duration_sec)
            while not self._cancelled():
                try:
                    pipeline.llm.client.list()
                except Exception:
                    self.error.emit("Waiting for Ollama on localhost:11434...")
                    for _ in range(50):
                        if self._cancelled():
                            return
                        self.msleep(100)
                    continue
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
        self._assistant_open = False
        self._closing = False

        body = QWidget()
        layout = QVBoxLayout(body)
        self.status = QLabel("Ready")
        layout.addWidget(self.status)
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
        for message in db.recent_messages(session_id, 2 * context.max_history):
            self.history.append(f"{'You' if message.role == 'user' else 'Dogen'}: {message.content}")

    def start(self):
        if self.worker and self.worker.isRunning():
            return
        self.worker = ConversationWorker(self.config, self.context, self)
        self.worker.recording_started.connect(lambda: self.status.setText("Recording..."))
        self.worker.transcribed.connect(self._on_transcribed)
        self.worker.response_chunk.connect(self._on_chunk)
        self.worker.audio_playing.connect(lambda: self.status.setText("Playing audio..."))
        self.worker.error.connect(self._on_error)
        self.worker.ready.connect(lambda: self.status.setText("Ready for next turn"))
        self.worker.turn_completed.connect(self._on_completed)
        self.worker.finished.connect(self._on_finished)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status.setText("Starting...")
        self.worker.start()

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
        self.status.setText(text)

    def _on_completed(self, user_text, assistant_text, latency_ms):
        self.db.add_message(self.session_id, "user", user_text, self.config.ollama_model, latency_ms)
        self.db.add_message(self.session_id, "assistant", assistant_text, self.config.ollama_model, latency_ms)
        self._assistant_open = False

    def _on_finished(self):
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
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
