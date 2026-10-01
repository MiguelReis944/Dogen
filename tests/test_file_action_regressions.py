import os
from types import SimpleNamespace
from unittest.mock import ANY, Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from nlp.llm import ConversationContext
from storage.db import Database
from ui import main_window as main_window_module
from ui.main_window import MainWindow
from utils.config import AppConfig


def test_practice_progress_file_action_opens_one_dialog(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversations.db") as db:
        with patch.object(MainWindow, "_fetch_models", return_value=None):
            window = MainWindow(
                AppConfig(), db, ConversationContext(), "session",
                auto_start=False, start_maximized=False,
            )

        dialog = Mock()
        with patch.object(
            main_window_module, "ProgressDialog", return_value=dialog
        ) as progress_dialog:
            window._show_progress()

        progress_dialog.assert_called_once_with(ANY, parent=window)
        dialog.exec_.assert_called_once_with()
        window.close()


def test_session_export_closes_empty_check_cursor_before_modal_dialog(
    tmp_path, monkeypatch
):
    app = QApplication.instance() or QApplication([])
    cursor_generators = []
    exported = tmp_path / "session.txt"

    def session_messages(_session_id):
        def rows():
            try:
                yield SimpleNamespace(
                    role="user", content="hello", created_at="2026-09-30",
                    is_complete=True,
                )
            finally:
                pass

        generator = rows()
        cursor_generators.append(generator)
        return generator

    with Database(tmp_path / "conversations.db") as db:
        with patch.object(MainWindow, "_fetch_models", return_value=None):
            window = MainWindow(
                AppConfig(), db, ConversationContext(), "session",
                auto_start=False, start_maximized=False,
            )
        monkeypatch.setattr(db, "session_messages", session_messages)

        def open_save_dialog(*_args):
            assert cursor_generators[0].gi_frame is None
            return str(exported), ""

        monkeypatch.setattr(
            main_window_module.QFileDialog,
            "getSaveFileName",
            open_save_dialog,
        )
        window._export_session()

        export_text = exported.read_text(encoding="utf-8")
        assert export_text.count("You: hello") == 1
        window.close()
