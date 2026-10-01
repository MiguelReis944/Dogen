"""Historical coaching annotations must not reappear in the conversation."""

import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from nlp.feedback import CoachFeedback
from nlp.llm import ConversationContext
from storage.db import Database
from ui.main_window import MainWindow
from utils.config import AppConfig


def test_history_hides_legacy_coaching_notes_without_changing_saved_messages(tmp_path):
    app = QApplication.instance() or QApplication([])
    saved = "That sounds fun. [Grammar: good wording.] [Agreement: nice structure.]"
    with Database(tmp_path / "conversations.db") as db:
        db.add_message("session", "user", "What's your name?", "test", 0)
        db.add_message("session", "assistant", saved, "test", 0)
        with patch.object(MainWindow, "_fetch_models", return_value=None):
            window = MainWindow(
                AppConfig(), db, ConversationContext(), "session",
                auto_start=False, start_maximized=False,
            )
        try:
            visible = window.history.toPlainText()
            assert "That sounds fun." in visible
            assert "Grammar" not in visible
            assert "Agreement" not in visible
            assert db.recent_messages("session", 2)[-1].content == saved
            assert window._format_feedback(CoachFeedback(
                correction="What's your name → What is your name?"
            )) == ""
            assert "I went yesterday" in window._format_feedback(CoachFeedback(
                correction="I go yesterday → I went yesterday", category="verb_tense"
            ))
        finally:
            window.close()
