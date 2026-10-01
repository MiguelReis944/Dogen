"""Turn-level regressions for replies interrupted before persistence."""

import os
import re
from unittest.mock import Mock, patch

import pytest
from PyQt5.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from nlp.llm import ConversationContext
from pipeline import ProcessingPipeline, TurnResult
from storage.db import Database
from ui import main_window as main_window_module
from ui.main_window import MainWindow
from utils.config import AppConfig


def _make_window(db, context):
    with patch.object(MainWindow, "_fetch_models", return_value=None):
        return MainWindow(
            AppConfig(), db, context, "session",
            auto_start=False, start_maximized=False,
        )


def _run_interrupted_turn(scenario, context):
    cancel_after_playback = [False]

    class Transcriber:
        def transcribe(self, _audio):
            return "Tell me about the plan"

    class LLM:
        def generate(self, _messages, on_chunk, _cancelled):
            if scenario == "llm_error":
                raise RuntimeError("stream disconnected before first token")
            on_chunk("Here is one useful thought.")

    class Synthesizer:
        def synthesize_stream(self, _text):
            yield [0.1], 22050

    class Player:
        def play(self, *_args, **_kwargs):
            if scenario == "tts_cancel":
                cancel_after_playback[0] = True

    pipeline = ProcessingPipeline(Transcriber(), LLM(), Synthesizer(), Player())
    return pipeline.run(
        [0.1], context, lambda *_: None, lambda: False,
        playback_stop_requested=lambda: cancel_after_playback[0],
    )


@pytest.mark.parametrize(
    ("scenario", "expected_reply"),
    [
        ("llm_error", ""),
        ("tts_cancel", "Here is one useful thought."),
    ],
)
def test_interrupted_turn_is_persisted_visible_and_exportable(
    tmp_path, monkeypatch, scenario, expected_reply
):
    app = QApplication.instance() or QApplication([])
    context = ConversationContext()
    result = _run_interrupted_turn(scenario, context)

    assert isinstance(result, TurnResult)
    assert re.fullmatch(r"[a-f0-9]{32}", result.trace_id)
    assert result.transcript == "Tell me about the plan"
    assert result.reply == expected_reply
    assert result.is_complete is False
    assert context.messages == []

    target = tmp_path / f"{scenario}.txt"
    diagnostics = Mock()
    monkeypatch.setattr(main_window_module, "log_diagnostic", diagnostics)
    with Database(tmp_path / "conversations.db") as db:
        window = _make_window(db, context)
        window._on_completed(result, 100)
        expected_event = "turn_interrupted" if scenario == "tts_cancel" else "turn_failed"
        expected_stage = "tts" if scenario == "tts_cancel" else "model"
        assert any(
            call.args[0] == expected_event
            and call.kwargs.get("stage") == expected_stage
            and call.kwargs.get("trace_id") == result.trace_id
            for call in diagnostics.call_args_list
        )

        messages = db.recent_messages("session", 10)
        assert [(message.role, message.content, message.is_complete) for message in messages] == [
            ("user", "Tell me about the plan", False),
            ("assistant", expected_reply, False),
        ]
        assert db.recent_context_messages("session", 10) == []
        assert db.session_stats("session")["turns"] == 0
        assert db.connection.execute(
            "SELECT COUNT(*) FROM turn_metrics WHERE session_id=?", ("session",)
        ).fetchone()[0] == 0
        history = window.history.toPlainText()
        assert "Tell me about the plan" in history
        assert "Dogen (response interrupted)" in history
        if expected_reply:
            assert expected_reply in history

        with patch.object(
            main_window_module.QFileDialog,
            "getSaveFileName",
            return_value=(str(target), ""),
        ):
            window._export_session()

        exported = target.read_text(encoding="utf-8")
        assert "You: Tell me about the plan" in exported
        assert "Dogen (response interrupted):" in exported
        if expected_reply:
            assert expected_reply in exported
        window.close()
