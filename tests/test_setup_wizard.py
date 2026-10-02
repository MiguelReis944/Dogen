import os
import sys
from types import ModuleType, SimpleNamespace
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QCloseEvent

from ui.setup_wizard import (
    SetupWizard,
    SetupWorker,
    model_names,
    model_pull_progress,
    should_show_setup_wizard,
)
from utils.config import AppConfig


def test_setup_wizard_only_runs_for_a_packaged_first_launch(tmp_path):
    marker = tmp_path / "first_run_setup_complete"

    assert not should_show_setup_wizard(False, marker)
    assert should_show_setup_wizard(True, marker)

    marker.touch()
    assert not should_show_setup_wizard(True, marker)


def test_model_names_normalizes_ollama_response_shapes():
    assert model_names({"models": [{"model": "alpha:latest"}, {"model": "beta:3b"}]}) == [
        "alpha:latest", "beta:3b"
    ]
    assert model_names(SimpleNamespace(models=[
        SimpleNamespace(model="alpha:latest"),
        SimpleNamespace(model="beta:3b"),
    ])) == ["alpha:latest", "beta:3b"]


def test_model_pull_progress_is_bounded_and_handles_unknown_size():
    assert model_pull_progress({"completed": 25, "total": 100}) == 25
    assert model_pull_progress(SimpleNamespace(completed=250, total=100)) == 100
    assert model_pull_progress({"completed": 20, "total": 0}) is None


def test_setup_wizard_can_open_without_blocking_on_model_checks(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(SetupWizard, "_start_operation", lambda *args: None)

    wizard = SetupWizard(AppConfig())

    assert wizard.windowTitle() == "Set up Dogen"
    assert wizard.model_combo.isEditable()
    assert wizard.continue_button.text() == "Continue to Dogen"
    wizard.close()
    app.processEvents()


def test_inspection_does_not_show_completed_progress_when_voice_is_missing(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(SetupWizard, "_start_operation", lambda *args: None)
    wizard = SetupWizard(AppConfig())

    wizard._show_inspection({
        "whisper_ready": True,
        "whisper_error": "",
        "tts_ready": False,
        "tts_error": "",
        "models": ["llama3.2:3b"],
        "ollama_error": "",
    })

    assert wizard.tts_status.text() == "Needs download"
    assert wizard.progress_bar.isHidden()
    assert wizard.prepare_speech_button.isEnabled()
    wizard.close()
    app.processEvents()


def test_prepare_failure_remains_visible_after_refreshing_model_status(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(SetupWizard, "_start_operation", lambda *args: None)
    wizard = SetupWizard(AppConfig())
    wizard._worker_result = {
        "operation": "prepare_speech",
        "ok": False,
        "error": "No module named 'transformers'",
    }

    wizard._on_worker_finished()
    wizard._show_inspection({
        "whisper_ready": True,
        "whisper_error": "",
        "tts_ready": False,
        "tts_error": "",
        "models": ["llama3.2:3b"],
        "ollama_error": "",
    })

    assert wizard.progress_label.text() == (
        "Could not prepare speech models: No module named 'transformers'"
    )
    assert wizard.tts_status.text() == "Needs download"
    wizard.close()
    app.processEvents()


def test_speech_preparation_failure_reports_stage_and_traceback(monkeypatch):
    worker = SetupWorker("prepare_speech", AppConfig())
    monkeypatch.setattr("ui.setup_wizard.preflight.check_whisper", lambda _name: True)
    monkeypatch.setattr("ui.setup_wizard.preflight.check_tts", lambda _name: False)

    def fail_download(_name):
        raise OSError("could not get source code")

    monkeypatch.setattr("ui.setup_wizard.preflight.download_tts", fail_download)

    result = worker._prepare_speech()

    assert result["ok"] is False
    assert result["stage"] == "English voice download"
    assert result["error"] == "could not get source code"
    assert "fail_download" in result["traceback"]


def test_prepare_error_details_can_be_copied_from_setup_wizard(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(SetupWizard, "_start_operation", lambda *args: None)
    wizard = SetupWizard(AppConfig())
    wizard._worker_result = {
        "operation": "prepare_speech",
        "ok": False,
        "stage": "English voice download",
        "error": "could not get source code",
        "traceback": "Traceback (most recent call last):\nOSError: could not get source code",
    }

    wizard._on_worker_finished()
    wizard._show_inspection({
        "whisper_ready": True,
        "whisper_error": "",
        "tts_ready": False,
        "tts_error": "",
        "models": ["llama3.2:3b"],
        "ollama_error": "",
    })
    wizard.copy_error_button.click()

    assert wizard.progress_label.text() == (
        "Could not prepare speech models during English voice download: "
        "could not get source code"
    )
    assert QApplication.clipboard().text() == (
        "English voice download: could not get source code\n\n"
        "Traceback (most recent call last):\nOSError: could not get source code"
    )
    wizard.close()
    app.processEvents()


def test_ollama_model_pull_uses_a_timeout_and_closes_on_cancellation(monkeypatch):
    client_state = {}

    class FakeClient:
        def __init__(self, host, timeout):
            client_state["timeout"] = timeout

        def pull(self, model, stream):
            raise AssertionError("a canceled pull must not start")

        def close(self):
            client_state["closed"] = True

    ollama_module = ModuleType("ollama")
    ollama_module.Client = FakeClient
    monkeypatch.setitem(sys.modules, "ollama", ollama_module)

    worker = SetupWorker("pull_model", AppConfig(), "large-model:latest")
    monkeypatch.setattr(worker, "isInterruptionRequested", lambda: True)

    result = worker._pull_model()

    assert result["cancelled"] is True
    assert client_state["timeout"] is not None
    assert client_state["closed"] is True


def test_setup_worker_cancel_closes_active_ollama_client(monkeypatch):
    closed = []
    interrupted = []
    worker = SetupWorker("pull_model", AppConfig(), "large-model:latest")
    worker._ollama_client = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(worker, "requestInterruption", lambda: interrupted.append(True))

    worker.cancel()

    assert interrupted == [True]
    assert closed == [True]


def test_closing_during_model_download_requests_cancellation(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(SetupWizard, "_start_operation", lambda *args: None)
    wizard = SetupWizard(AppConfig())
    cancellations = []
    wizard._worker = SimpleNamespace(
        operation="pull_model",
        isRunning=lambda: True,
        cancel=lambda: cancellations.append(True),
    )
    event = QCloseEvent()

    wizard.closeEvent(event)

    assert cancellations == [True]
    assert wizard._close_requested is True
    assert not event.isAccepted()
    wizard._worker = None
    wizard.close()
