import json
import logging

from utils.diagnostics import (
    configure_local_diagnostics,
    disable_local_diagnostics,
    log_diagnostic,
)
from utils.config import AppConfig, load_config


def test_diagnostics_are_noop_until_user_enables_them(caplog):
    from logging import getLogger

    logger = getLogger("dogen.diagnostics")
    disable_local_diagnostics()
    logger.propagate = True
    with caplog.at_level(logging.INFO, logger="dogen.diagnostics"):
        log_diagnostic("recording_finished", stop_reason="ptt_release", duration_ms=4200)

    assert caplog.text == ""


def test_diagnostics_keep_only_allowlisted_privacy_safe_fields(tmp_path):
    private_phrase = "I live at 123 Secret Street"
    log_path = tmp_path / "diagnostics.log"
    configure_local_diagnostics(log_path)

    log_diagnostic(
        "recording_finished",
        stop_reason="ptt_release",
        duration_ms=4200,
        transcript=private_phrase,
        response=private_phrase,
        api_key="secret-token",
        message=private_phrase,
    )

    output = log_path.read_text(encoding="utf-8")
    assert "recording_finished" in output
    assert "ptt_release" in output
    assert "4200" in output
    assert private_phrase not in output
    assert "secret-token" not in output
    assert json.loads(output) == {
        "duration_ms": 4200,
        "event": "recording_finished",
        "stop_reason": "ptt_release",
    }
    handler = logging.getLogger("dogen.diagnostics").handlers[0]
    assert handler.maxBytes == 512_000
    assert handler.backupCount == 2


def test_diagnostics_reject_arbitrary_event_and_invalid_stop_reason(tmp_path):
    log_path = tmp_path / "diagnostics.log"
    configure_local_diagnostics(log_path)
    log_diagnostic("my private sentence", stop_reason="my private sentence")

    assert log_path.read_text(encoding="utf-8") == ""


def test_disabling_diagnostics_closes_handler_and_stops_future_writes(tmp_path):
    log_path = tmp_path / "diagnostics.log"
    assert configure_local_diagnostics(log_path) is True
    log_diagnostic("recording_finished", stop_reason="ptt_release")

    disable_local_diagnostics()
    log_diagnostic("recording_finished", stop_reason="ptt_release")

    assert len(log_path.read_text(encoding="utf-8").splitlines()) == 1
    assert not any(
        hasattr(handler, "_dogen_diagnostics_path")
        for handler in logging.getLogger("dogen.diagnostics").handlers
    )


def test_diagnostic_configuration_failure_does_not_raise_or_enable_logging(
    tmp_path, monkeypatch
):
    def fail_to_create(*_args, **_kwargs):
        raise OSError("access denied")

    monkeypatch.setattr("utils.diagnostics.RotatingFileHandler", fail_to_create)

    assert configure_local_diagnostics(tmp_path / "diagnostics.log") is False
    assert not any(
        hasattr(handler, "_dogen_diagnostics_path")
        for handler in logging.getLogger("dogen.diagnostics").handlers
    )


def test_error_type_accepts_class_names_not_arbitrary_identifiers(tmp_path):
    log_path = tmp_path / "diagnostics.log"
    configure_local_diagnostics(log_path)
    log_diagnostic("turn_failed", stage="model", error_type="RuntimeError")
    log_diagnostic("turn_failed", stage="model", error_type="joao.silva")

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert lines == [
        '{"error_type":"RuntimeError","event":"turn_failed","stage":"model"}',
        '{"event":"turn_failed","stage":"model"}',
    ]
    assert "joao.silva" not in "\n".join(lines)


def test_tts_interruption_is_allowlisted_as_interruption_not_failure(tmp_path):
    log_path = tmp_path / "diagnostics.log"
    configure_local_diagnostics(log_path)
    log_diagnostic(
        "turn_interrupted",
        stage="tts",
        error_type="PlaybackInterrupted",
        trace_id="a" * 32,
    )

    event = json.loads(log_path.read_text(encoding="utf-8"))
    assert event == {
        "error_type": "PlaybackInterrupted",
        "event": "turn_interrupted",
        "stage": "tts",
        "trace_id": "a" * 32,
    }


def test_diagnostics_are_off_by_default_and_can_be_enabled_in_settings(tmp_path):
    from PyQt5.QtWidgets import QApplication

    from ui.settings_dialog import SettingsDialog

    app = QApplication.instance() or QApplication([])
    config = AppConfig()
    assert config.diagnostics_enabled is False

    dialog = SettingsDialog(config, tmp_path / "settings.json")
    assert dialog._diagnostics.isChecked() is False
    dialog._diagnostics.setChecked(True)
    dialog._save()

    assert config.diagnostics_enabled is True
    assert load_config(tmp_path / "settings.json").diagnostics_enabled is True
    dialog.close()


def test_settings_apply_diagnostics_toggle_without_restarting_app(tmp_path, monkeypatch):
    import os
    from unittest.mock import Mock, patch

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication

    from nlp.llm import ConversationContext
    from storage.db import Database
    from ui import main_window as main_window_module
    from ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    config = AppConfig()
    dialog = Mock()
    toggle = [True]

    def accept_settings():
        config.diagnostics_enabled = toggle[0]
        return 1

    dialog.exec_.side_effect = accept_settings
    monkeypatch.setattr(main_window_module, "SettingsDialog", lambda *_a, **_k: dialog)
    monkeypatch.setattr(
        main_window_module,
        "local_diagnostics_path",
        lambda: tmp_path / "diagnostics.log",
    )

    with Database(tmp_path / "conversations.db") as db:
        with patch.object(MainWindow, "_fetch_models", return_value=None):
            window = MainWindow(
                config, db, ConversationContext(), "session",
                auto_start=False, start_maximized=False,
            )

        window._open_settings()
        assert any(
            hasattr(handler, "_dogen_diagnostics_path")
            for handler in logging.getLogger("dogen.diagnostics").handlers
        )

        toggle[0] = False
        window._open_settings()
        assert not any(
            hasattr(handler, "_dogen_diagnostics_path")
            for handler in logging.getLogger("dogen.diagnostics").handlers
        )
        window.close()
