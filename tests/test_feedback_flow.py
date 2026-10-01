import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from nlp.feedback import CoachFeedback
from nlp.llm import ConversationContext, build_system_prompt
from pipeline import ProcessingPipeline
from storage.db import Database
from ui.main_window import MainWindow
from utils.config import AppConfig


class FixedTranscriber:
    def transcribe(self, audio):
        return "I goed yesterday"


class FixedSynthesizer:
    def synthesize_stream(self, text):
        yield [0.1], 22050


class FixedPlayer:
    def play(self, samples, sample_rate, cancelled, on_volume=None):
        pass


class FixedLLM:
    def __init__(self, response):
        self.response = response

    def generate(self, messages, on_chunk, cancelled):
        on_chunk(self.response)
        return self.response


def _window(db, context):
    app = QApplication.instance() or QApplication([])
    with patch.object(MainWindow, "_fetch_models", return_value=None):
        window = MainWindow(
            AppConfig(), db, context, "session", auto_start=False, start_maximized=False
        )
    return app, window


def test_coaching_feedback_flows_from_model_text_to_fixes(tmp_path):
    app = QApplication.instance() or QApplication([])
    context = ConversationContext(
        system_prompt=build_system_prompt("Free conversation", corrections=True)
    )
    response = (
        "Nice try! What happened next?\n"
        "[Correction: I goed yesterday → I went yesterday]\n"
        "[Better phrasing: I went there yesterday.]\n"
        "[Category: verb_tense]"
    )
    pipeline = ProcessingPipeline(
        FixedTranscriber(), FixedLLM(response), FixedSynthesizer(), FixedPlayer()
    )

    with Database(tmp_path / "conversation.db") as db:
        result = pipeline.run([0.1], context, lambda *_: None, lambda: False)
        db.add_completed_turn(
            "session", result.transcript, result.reply, "test-model", 50,
            result.feedback, result.metrics,
        )
        app, window = _window(db, context)
        try:
            window._render_history()
            fixes = window.fixes.toPlainText()
            assert result.feedback == CoachFeedback(
                correction="I goed yesterday → I went yesterday",
                better_phrasing="I went there yesterday.",
                category="verb_tense",
            )
            assert "I goed yesterday → I went yesterday" in fixes
            assert "I went there yesterday." in fixes
            assert "Category: verb tense" in fixes
        finally:
            window.close()


def test_fluency_mode_does_not_create_fixes_without_structured_feedback(tmp_path):
    app = QApplication.instance() or QApplication([])
    context = ConversationContext(
        system_prompt=build_system_prompt("Free conversation", corrections=False)
    )
    llm = FixedLLM("Sounds like a busy day. What did you do next?")
    pipeline = ProcessingPipeline(FixedTranscriber(), llm, FixedSynthesizer(), FixedPlayer())

    with Database(tmp_path / "conversation.db") as db:
        result = pipeline.run([0.1], context, lambda *_: None, lambda: False)
        db.add_completed_turn(
            "session", result.transcript, result.reply, "test-model", 50,
            result.feedback, result.metrics,
        )
        app, window = _window(db, context)
        try:
            window._render_history()
            assert result.feedback.is_empty
            assert "no clear corrections" in window.fixes.toPlainText().lower()
            assert db.feedback_for_session("session") == []
        finally:
            window.close()
