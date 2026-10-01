import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from nlp.feedback import CoachFeedback
from nlp.llm import SCENARIOS, ConversationContext, build_system_prompt
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
        self.messages = None

    def generate(self, messages, on_chunk, cancelled):
        self.messages = messages
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
        system_prompt=build_system_prompt("Free conversation", fluency_mode=False)
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
            assert fixes.strip() == "I goed yesterday → I went yesterday"
            assert "More natural:" not in fixes
        finally:
            window.close()


def test_fluency_mode_keeps_corrections_enabled_and_displays_them_as_text(tmp_path):
    app = QApplication.instance() or QApplication([])
    context = ConversationContext(
        system_prompt=build_system_prompt("Free conversation", fluency_mode=True)
    )
    response = (
        "Sounds like a busy day. What did you do next?\n"
        "[Correction: I goed yesterday → I went yesterday]\n"
        "[Category: verb_tense]"
    )
    llm = FixedLLM(response)
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
            assert result.feedback.correction == "I goed yesterday → I went yesterday"
            assert "I goed yesterday → I went yesterday" in window.fixes.toPlainText()
            assert window.fixes.isReadOnly()
            assert db.feedback_for_session("session") == [result.feedback]
            assert "Do not silently skip a clear English error" in llm.messages[0]["content"]
            assert "never invent a correction for natural English" in llm.messages[0]["content"]
            assert "Do NOT add any bracket annotation blocks" not in llm.messages[0]["content"]
        finally:
            window.close()


def test_all_scenarios_require_corrections_without_inventing_them():
    for scenario in SCENARIOS:
        for fluency_mode in (False, True):
            prompt = build_system_prompt(scenario, fluency_mode=fluency_mode)

            assert "Do not silently skip a clear English error" in prompt
            assert "never invent a correction for natural English" in prompt
            assert "occasional grammar slip" not in prompt
