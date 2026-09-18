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
