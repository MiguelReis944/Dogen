"""First-run setup for packaged Dogen installations."""

from pathlib import Path

from PyQt5.QtCore import QThread, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from scripts import preflight
from ui.dogen_logo import add_dialog_header
from utils.config import AppConfig


OLLAMA_DOWNLOAD_URL = "https://ollama.com/download/windows"


def should_show_setup_wizard(is_packaged: bool, marker_path: str | Path) -> bool:
    """Run onboarding once for packaged installs; never interrupt source runs."""
    return bool(is_packaged and not Path(marker_path).is_file())


def model_names(response) -> list[str]:
    """Normalize the supported dictionary and client-object Ollama responses."""
    models = response.get("models", []) if isinstance(response, dict) else getattr(
        response, "models", []
    )
    names = []
    for model in models or []:
        name = model.get("model", "") if isinstance(model, dict) else getattr(
            model, "model", ""
        )
        if name and name not in names:
            names.append(name)
    return sorted(names)


def model_pull_progress(item) -> int | None:
    """Return Ollama's bounded download percentage, or None for unknown size."""
    get = item.get if isinstance(item, dict) else lambda key, default=None: getattr(
        item, key, default
    )
    total = get("total", 0) or 0
    completed = get("completed", 0) or 0
    if not total:
        return None
    return min(100, max(0, int(completed * 100 / total)))


class SetupWorker(QThread):
    progress_changed = pyqtSignal(str, object)
    result_ready = pyqtSignal(object)

    def __init__(self, operation, config, model="", parent=None):
        super().__init__(parent)
        self.operation = operation
        self.config = config
        self.model = model
        self._ollama_client = None

    def cancel(self):
        """Interrupt a streaming Ollama pull and close its active HTTP client."""
        self.requestInterruption()
        if self._ollama_client is not None:
            try:
                self._ollama_client.close()
            except Exception:
                # The worker will also notice the interruption or HTTP timeout.
                pass

    def _ollama_models(self):
        import ollama

        client = ollama.Client(host=self.config.ollama_host, timeout=5)
        return client, model_names(client.list())

    def _inspect(self):
        self.progress_changed.emit("Checking local speech models…", None)
        try:
            whisper_ready = preflight.check_whisper(self.config.whisper_model)
            whisper_error = ""
        except Exception as exc:
            whisper_ready = False
            whisper_error = str(exc)
        try:
            tts_ready = preflight.check_tts(self.config.tts_model)
            tts_error = ""
        except Exception as exc:
            tts_ready = False
            tts_error = str(exc)
        self.progress_changed.emit("Checking the local Ollama service…", None)
        try:
            _, models = self._ollama_models()
            ollama_error = ""
        except Exception as exc:
            models = []
            ollama_error = str(exc)
        return {
            "operation": self.operation,
            "whisper_ready": bool(whisper_ready),
            "whisper_error": whisper_error,
            "tts_ready": bool(tts_ready),
            "tts_error": tts_error,
            "models": models,
            "ollama_error": ollama_error,
        }

    def _prepare_speech(self):
        try:
            whisper_ready = preflight.check_whisper(self.config.whisper_model)
            if not whisper_ready:
                self.progress_changed.emit(
                    f"Downloading speech recognition model {self.config.whisper_model}…",
                    None,
                )
                preflight.download_whisper(self.config.whisper_model)
            tts_ready = preflight.check_tts(self.config.tts_model)
            if not tts_ready:
                self.progress_changed.emit("Downloading the English voice model…", None)
                preflight.download_tts(self.config.tts_model)
            return {"operation": self.operation, "ok": True}
        except Exception as exc:
            return {"operation": self.operation, "ok": False, "error": str(exc)}

    def _pull_model(self):
        client = None
        try:
            import ollama

            client = ollama.Client(host=self.config.ollama_host, timeout=30)
            self._ollama_client = client
            if self.isInterruptionRequested():
                return {"operation": self.operation, "ok": False, "cancelled": True}
            for item in client.pull(self.model, stream=True):
                if self.isInterruptionRequested():
                    return {"operation": self.operation, "ok": False, "cancelled": True}
                status = item.get("status", "Downloading model…") if isinstance(
                    item, dict
                ) else getattr(item, "status", "Downloading model…")
                self.progress_changed.emit(str(status), model_pull_progress(item))
            if self.isInterruptionRequested():
                return {"operation": self.operation, "ok": False, "cancelled": True}
            models = model_names(client.list())
            return {"operation": self.operation, "ok": True, "models": models}
        except Exception as exc:
            if self.isInterruptionRequested():
                return {"operation": self.operation, "ok": False, "cancelled": True}
            return {"operation": self.operation, "ok": False, "error": str(exc)}
        finally:
            if client is not None:
                try:
                    client.close()
                finally:
                    self._ollama_client = None

    def run(self):
        try:
            if self.operation == "inspect":
                result = self._inspect()
            elif self.operation == "prepare_speech":
                result = self._prepare_speech()
            elif self.operation == "pull_model":
                result = self._pull_model()
            else:
                result = {
                    "operation": self.operation,
                    "ok": False,
                    "error": "Unknown setup operation.",
                }
        except Exception as exc:
            result = {
                "operation": self.operation,
                "ok": False,
                "error": str(exc),
            }
        self.result_ready.emit(result)


class SetupWizard(QDialog):
    """Show download, Ollama, and model-selection guidance before first use."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._worker = None
        self._worker_result = None
        self._close_requested = False
        self._speech_models_ready = False
        self._ollama_models = []
        self._ollama_reachable = False
        self.setWindowTitle("Set up Dogen")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        add_dialog_header(self, layout, "Welcome to Dogen")

        intro = QLabel(
            "This one-time check prepares the local speech models and connects Dogen "
            "to Ollama. Model files are downloaded separately and stay on this computer."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.whisper_status = QLabel("Checking…")
        self.tts_status = QLabel("Checking…")
        self.ollama_status = QLabel("Checking…")
        form.addRow("Speech recognition:", self.whisper_status)
        form.addRow("English voice:", self.tts_status)
        form.addRow("Ollama:", self.ollama_status)
        layout.addLayout(form)

        speech_row = QHBoxLayout()
        self.prepare_speech_button = QPushButton("Prepare speech models")
        self.prepare_speech_button.clicked.connect(self._prepare_speech)
        speech_row.addWidget(self.prepare_speech_button)
        self.open_ollama_button = QPushButton("Get Ollama")
        self.open_ollama_button.clicked.connect(self._open_ollama_download)
        speech_row.addWidget(self.open_ollama_button)
        layout.addLayout(speech_row)

        layout.addWidget(QLabel("Choose an installed Ollama model, or enter a model tag to download:"))
        model_row = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setInsertPolicy(QComboBox.NoInsert)
        self.model_combo.setPlaceholderText("Choose an installed model")
        model_row.addWidget(self.model_combo, stretch=1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._inspect)
        model_row.addWidget(self.refresh_button)
        layout.addLayout(model_row)

        self.download_model_button = QPushButton("Download model")
        self.download_model_button.clicked.connect(self._download_model)
        layout.addWidget(self.download_model_button)

        self.progress_label = QLabel("Checking setup…")
        self.progress_label.setWordWrap(True)
        layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        self.hide_next_time = QCheckBox("Don't show this setup guide again")
        layout.addWidget(self.hide_next_time)

        footer = QHBoxLayout()
        footer.addStretch()
        self.continue_button = QPushButton("Continue to Dogen")
        self.continue_button.setDefault(True)
        self.continue_button.clicked.connect(self._continue_to_app)
        footer.addWidget(self.continue_button)
        layout.addLayout(footer)

        self._set_busy(True)
        self._start_operation("inspect")

    def _set_busy(self, busy):
        self.prepare_speech_button.setEnabled(not busy)
        self.open_ollama_button.setEnabled(not busy)
        self.model_combo.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy)
        self.download_model_button.setEnabled(not busy and self._ollama_reachable)
        self.continue_button.setEnabled(not busy)
        if busy:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(100)

    def _start_operation(self, operation, model=""):
        self._set_busy(True)
        self._worker_result = None
        self._worker = SetupWorker(operation, self.config, model, self)
        self._worker.progress_changed.connect(self._on_progress)
        self._worker.result_ready.connect(self._on_result)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_progress(self, message, percent):
        self.progress_label.setText(message)
        if percent is None:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(int(percent))

    def _on_result(self, result):
        self._worker_result = result

    def _on_worker_finished(self):
        if self._close_requested:
            self.reject()
            return
        result = self._worker_result or {
            "operation": "unknown",
            "ok": False,
            "error": "Setup task ended without a result.",
        }
        operation = result.get("operation")
        if operation == "inspect":
            self._show_inspection(result)
        elif operation == "prepare_speech":
            self.progress_label.setText(
                "Speech models are ready."
                if result.get("ok") else f"Could not prepare speech models: {result.get('error', 'unknown error')}"
            )
            self._inspect()
        elif operation == "pull_model":
            if result.get("cancelled"):
                self.progress_label.setText("Model download canceled. You can continue setup later.")
            elif result.get("ok"):
                self._set_models(result.get("models", []))
                self.progress_label.setText("Model downloaded. It is selected for Dogen, not loaded into memory yet.")
                selected = self._worker_model_name(result)
                if selected:
                    self.model_combo.setCurrentText(selected)
            else:
                self.progress_label.setText(f"Could not download the model: {result.get('error', 'unknown error')}")
                self._set_busy(False)
                return
            self._set_busy(False)

    def _worker_model_name(self, result):
        # The downloaded tag remains the combo's editable text after the worker ends.
        return self.model_combo.currentText().strip()

    def _show_inspection(self, result):
        self._speech_models_ready = bool(
            result.get("whisper_ready") and result.get("tts_ready")
        )
        self.whisper_status.setText(
            "Ready" if result.get("whisper_ready") else "Needs download"
        )
        self.whisper_status.setToolTip(result.get("whisper_error", ""))
        self.tts_status.setText("Ready" if result.get("tts_ready") else "Needs download")
        self.tts_status.setToolTip(result.get("tts_error", ""))
        self._set_models(result.get("models", []))
        if result.get("ollama_error"):
            self._ollama_reachable = False
            self.ollama_status.setText("Not reachable")
            self.ollama_status.setToolTip(result["ollama_error"])
            self.progress_label.setText(
                "Install and start Ollama, then choose Refresh. Speech setup can be done now or later."
            )
        elif self._ollama_models:
            self.ollama_status.setText("Connected")
            self.progress_label.setText("Choose a model for Dogen. The selected model will not be loaded until you request it.")
        else:
            self._ollama_reachable = True
            self.ollama_status.setText("Connected; no models installed")
            self.progress_label.setText(
                "Enter an Ollama model tag to download, or continue and install one later."
            )
        if self._speech_models_ready and self._ollama_models:
            self.hide_next_time.setChecked(True)
        self._set_busy(False)

    def _set_models(self, names):
        selected = self.model_combo.currentText().strip() or self.config.ollama_model
        self._ollama_models = list(names or [])
        self.model_combo.clear()
        self.model_combo.addItems(self._ollama_models)
        if selected in self._ollama_models:
            self.model_combo.setCurrentText(selected)
        else:
            self.model_combo.setCurrentIndex(-1)
            self.model_combo.clearEditText()

    def _inspect(self):
        self._start_operation("inspect")

    def _prepare_speech(self):
        self._start_operation("prepare_speech")

    def _download_model(self):
        if not self._ollama_reachable:
            QMessageBox.information(
                self, "Ollama unavailable", "Install and start Ollama, then choose Refresh."
            )
            return
        model = self.model_combo.currentText().strip()
        if not model:
            QMessageBox.information(self, "Choose a model", "Enter an Ollama model tag first.")
            return
        if model in self._ollama_models:
            self.progress_label.setText(f"{model} is installed. It will be used by Dogen after you load it from File → Model.")
            return
        answer = QMessageBox.question(
            self,
            "Download Ollama model",
            f"Download {model} using Ollama? Model downloads can use several gigabytes of internet and disk space.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._start_operation("pull_model", model)

    def _open_ollama_download(self):
        QDesktopServices.openUrl(QUrl(OLLAMA_DOWNLOAD_URL))

    def _continue_to_app(self):
        model = self.model_combo.currentText().strip()
        if model in self._ollama_models:
            self.config.ollama_model = model
        if not self.hide_next_time.isChecked() and not self._speech_models_ready:
            answer = QMessageBox.question(
                self,
                "Setup is incomplete",
                "Dogen may not be able to record or respond until the missing models are prepared. "
                "Continue anyway and show this guide again next time?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        self.accept()

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            if self._worker.operation == "pull_model":
                self._close_requested = True
                self.progress_label.setText("Canceling model download…")
                self.continue_button.setEnabled(False)
                self._worker.cancel()
                event.ignore()
                return
            QMessageBox.information(
                self,
                "Setup is still running",
                "Please wait for the current setup step to finish before closing this window.",
            )
            event.ignore()
            return
        super().closeEvent(event)
