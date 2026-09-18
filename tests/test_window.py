import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from nlp.llm import ConversationContext
from storage.db import Database
from ui.main_window import MainWindow
from utils.config import AppConfig


def test_window_keeps_dogen_name_and_start_control(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = MainWindow(AppConfig(), db, ConversationContext(), "session")
        assert window.windowTitle() == "Dogen"
        assert window.start_button.text() == "Start Recording"
        assert not window.stop_button.isEnabled()
        window.close()


def test_failed_turn_removes_provisional_transcript(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = MainWindow(AppConfig(), db, ConversationContext(), "session")
        window._on_transcribed("temporary words")
        assert "temporary words" in window.history.toPlainText()
        window._on_error("TTS failed")
        assert "temporary words" not in window.history.toPlainText()
        window.close()


def test_worker_failure_remains_visible_after_finish(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = MainWindow(AppConfig(), db, ConversationContext(), "session")
        window._on_error("Coqui model is not cached")
        window._on_finished()
        assert window.status.text() == "Coqui model is not cached"
        window.close()
