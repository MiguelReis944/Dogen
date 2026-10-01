"""Regression tests for active-session recovery and empty exports."""

import os
import sys
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import main as app_main
from nlp.llm import ConversationContext
from storage.db import Database
from ui import main_window as main_window_module
from ui.main_window import MainWindow
from ui.session_summary_dialog import SessionSummaryDialog
from utils.config import AppConfig
from PyQt5.QtWidgets import QApplication


def _make_window(db, session_id):
    app = QApplication.instance() or QApplication([])
    with patch.object(MainWindow, "_fetch_models", return_value=None):
        window = MainWindow(
            AppConfig(), db, ConversationContext(), session_id,
            auto_start=False, start_maximized=False,
        )
    return app, window


def test_startup_restores_active_session_id_for_the_same_day(tmp_path, monkeypatch):
    db_path = tmp_path / "conversations.db"
    today = str(date.today())
    active_session_id = "new-empty-session"

    with Database(db_path) as db:
        db.set_setting("session_date", today)
        db.set_setting("session_id", active_session_id)
        db.add_message("previous-session", "user", "Older turn", "mistral", 10)

    captured = {}

    class FakeApplication:
        def __init__(self, _args):
            pass

        def setApplicationName(self, _name):
            pass

        def setWindowIcon(self, _icon):
            pass

        def setStyleSheet(self, _style):
            pass

        def exec_(self):
            return 0

    class FakeWindow:
        def __init__(self, _config, _db, _context, session_id, **_kwargs):
            captured["session_id"] = session_id

        def show(self):
            pass

    monkeypatch.setattr(app_main, "Database", lambda _path: Database(db_path))
    monkeypatch.setattr(app_main, "load_config", lambda _path: AppConfig())
    monkeypatch.setattr(app_main, "QApplication", FakeApplication)
    monkeypatch.setattr(app_main, "MainWindow", FakeWindow)
    monkeypatch.setattr(app_main, "dogen_window_icon", lambda: None)
    monkeypatch.setattr(app_main, "set_windows_app_user_model_id", lambda: None)
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(check_input_settings=lambda **_kwargs: None),
    )

    assert app_main.main() == 0
    assert captured["session_id"] == active_session_id


def test_new_session_persists_the_active_session_id(tmp_path):
    today = str(date.today())
    with Database(tmp_path / "conversation.db") as db:
        db.set_setting("session_date", today)
        db.add_message("previous-session", "user", "Older turn", "mistral", 10)
        _app, window = _make_window(db, "previous-session")

        with patch.object(
            SessionSummaryDialog,
            "exec_",
            return_value=SessionSummaryDialog.NEW_SESSION,
        ):
            window._end_session()

        assert window.session_id != "previous-session"
        assert db.get_setting("session_id") == window.session_id
        assert db.get_setting("session_date") == today
        window.close()


def test_export_of_empty_session_warns_before_opening_save_dialog(
    tmp_path, monkeypatch
):
    target = tmp_path / "empty-session.txt"
    message = MagicMock()
    chooser = MagicMock(return_value=(str(target), ""))

    with Database(tmp_path / "conversation.db") as db:
        _app, window = _make_window(db, "empty-session")
        monkeypatch.setattr(
            main_window_module,
            "QMessageBox",
            SimpleNamespace(information=message),
            raising=False,
        )
        monkeypatch.setattr(
            main_window_module.QFileDialog,
            "getSaveFileName",
            chooser,
        )

        window._export_session()

        chooser.assert_not_called()
        message.assert_called_once()
        assert "no messages" in message.call_args.args[2].lower()
        assert not target.exists()
        window.close()
