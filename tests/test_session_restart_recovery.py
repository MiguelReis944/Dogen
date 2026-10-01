"""Integration regression for starting a fresh session and restarting Dogen."""

import os
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import main as app_main
from nlp.llm import SYSTEM_PROMPT, ConversationContext
from storage.db import Database
from ui import main_window as main_window_module
from ui.main_window import MainWindow
from ui.session_summary_dialog import SessionSummaryDialog
from utils.config import AppConfig
from PyQt5.QtWidgets import QApplication


def test_new_session_stays_empty_after_restarting_app_on_same_day(
    tmp_path, monkeypatch
):
    """The new active session id, not prior history, is restored on startup."""
    qt_app = QApplication.instance() or QApplication([])
    fixed_day = date(2026, 10, 1)
    monkeypatch.setattr(app_main, "date", SimpleNamespace(today=lambda: fixed_day))
    monkeypatch.setattr(
        main_window_module, "date", SimpleNamespace(today=lambda: fixed_day)
    )

    db_path = tmp_path / "conversations.db"
    previous_session_id = "previous-session-with-history"
    previous_user_text = "I went to the store yesterday."
    previous_assistant_text = "What did you buy?"
    with Database(db_path) as db:
        db.set_setting("session_date", str(fixed_day))
        db.set_setting("session_id", previous_session_id)
        db.add_turn(
            previous_session_id,
            previous_user_text,
            previous_assistant_text,
            "mistral",
            100,
        )

    windows = []
    startup_states = []
    database_paths = []
    settings_paths = []
    settings_path = Path(__file__).resolve().parents[1] / "settings.json"
    legacy_prompt = "Legacy prompt asking for Better phrasing without correction rules."

    class InlineApplication:
        def __init__(self, _args):
            pass

        def setApplicationName(self, name):
            qt_app.setApplicationName(name)

        def setWindowIcon(self, icon):
            pass

        def setStyleSheet(self, stylesheet):
            qt_app.setStyleSheet(stylesheet)

        def exec_(self):
            window = windows[-1]
            if len(windows) == 1:
                with patch.object(
                    SessionSummaryDialog,
                    "exec_",
                    return_value=SessionSummaryDialog.NEW_SESSION,
                ):
                    window._end_session()
                assert window.context.messages == []
                assert window.history.toPlainText() == ""
            window.close()
            return 0

    def database_factory(requested_path):
        database_paths.append(Path(requested_path))
        return Database(db_path)

    def window_factory(config, db, context, session_id, **kwargs):
        settings_paths.append(Path(kwargs["settings_path"]))
        window = MainWindow(
            config,
            db,
            context,
            session_id,
            auto_start=False,
            start_maximized=False,
            **kwargs,
        )
        windows.append(window)
        startup_states.append(
            (
                session_id,
                [message.copy() for message in context.messages],
                window.history.toPlainText(),
                context.system_prompt,
            )
        )
        return window

    monkeypatch.setattr(app_main, "Database", database_factory)
    monkeypatch.setattr(
        app_main,
        "load_config",
        lambda _path: AppConfig(system_prompt=legacy_prompt),
    )
    monkeypatch.setattr(app_main, "QApplication", InlineApplication)
    monkeypatch.setattr(app_main, "MainWindow", window_factory)
    monkeypatch.setattr(app_main, "dogen_window_icon", lambda: None)
    monkeypatch.setattr(app_main, "set_windows_app_user_model_id", lambda: None)
    monkeypatch.setattr(MainWindow, "_fetch_models", lambda *_args: None)
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(check_input_settings=lambda **_kwargs: None),
    )

    assert app_main.main() == 0

    first_window = windows[0]
    first_startup_id, first_context, first_history, first_system_prompt = startup_states[0]
    assert first_startup_id == previous_session_id
    assert [message["content"] for message in first_context] == [
        previous_user_text,
        previous_assistant_text,
    ]
    assert previous_user_text in first_history
    assert first_system_prompt == SYSTEM_PROMPT
    assert "Do not silently skip a clear English error" in first_system_prompt
    assert "Legacy prompt" not in first_system_prompt
    new_session_id = first_window.session_id
    # _end_session replaces the id after returning from the first event loop.
    with Database(db_path) as db:
        new_session_id = db.get_setting("session_id")
        assert new_session_id != previous_session_id
        assert list(db.session_messages(new_session_id)) == []

    assert app_main.main() == 0

    restarted_window = windows[1]
    assert restarted_window.session_id == new_session_id
    assert restarted_window.context.messages == []
    assert restarted_window.history.toPlainText() == ""
    with Database(db_path) as db:
        assert db.get_setting("session_date") == str(fixed_day)
        assert db.get_setting("session_id") == new_session_id
        assert list(db.session_messages(new_session_id)) == []
        assert [message.content for message in db.session_messages(previous_session_id)] == [
            previous_user_text,
            previous_assistant_text,
        ]

    assert len(database_paths) == 2
    assert database_paths[0] == database_paths[1]
    assert settings_paths == [settings_path, settings_path]
