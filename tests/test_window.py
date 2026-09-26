import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from nlp.llm import ConversationContext
from nlp.feedback import CoachFeedback
from pipeline import TurnResult
from storage.db import Database
from storage.models import TurnMetrics
from storage.progress import ProgressStats
from ui.main_window import MainWindow
from ui.progress_dialog import ProgressDialog
from ui.settings_dialog import SettingsDialog
from utils.config import AppConfig


def _make_window(db, cfg=None, session="session"):
    """Create a MainWindow with ModelFetcher patched out (no Ollama connection)."""
    if cfg is None:
        cfg = AppConfig()
    with patch.object(MainWindow, "_fetch_models", return_value=None):
        return MainWindow(cfg, db, ConversationContext(), session)


def test_window_keeps_dogen_name_and_start_control(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)
        assert window.windowTitle() == "Dogen"
        assert window.start_button.text() == "Start Recording"
        assert not window.stop_button.isEnabled()
        window.close()


def test_failed_turn_removes_provisional_transcript(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)
        window._on_transcribed("temporary words")
        assert "temporary words" in window.history.toPlainText()
        window._on_error("TTS failed")
        assert "temporary words" not in window.history.toPlainText()
        window.close()


def test_worker_failure_remains_visible_after_finish(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)
        window._on_error("Coqui model is not cached")
        window._on_finished()
        assert window.status.text() == "Coqui model is not cached"
        window.close()


def test_format_message_highlights_correction_tags(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)
        html = window._format_message(
            "assistant",
            "Good try! [Correction: I goed → I went] [Better phrasing: I went to school]"
        )
        assert '#e67e22' in html   # Correction tag: orange
        assert '#27ae60' in html   # Better phrasing tag: green
        assert 'I goed' in html
        window.close()


def test_format_message_user_role_no_colors(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)
        html = window._format_message("user", "Hello [Correction: fake]")
        assert '#e67e22' not in html
        assert '<b>You:</b>' in html
        window.close()


def test_on_models_ready_populates_combo(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)
        window._on_models_ready(["llama3", "mistral", "phi3"])
        texts = [window.model_combo.itemText(i) for i in range(window.model_combo.count())]
        assert texts == ["llama3", "mistral", "phi3"]
        assert window.model_combo.isEnabled()
        window.close()


def test_on_models_ready_empty_falls_back_to_config(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        cfg = AppConfig(ollama_model="mistral")
        window = _make_window(db, cfg)
        window._on_models_ready([])
        assert window.model_combo.currentText() == "mistral"
        assert window.model_combo.isEnabled()
        window.close()


def test_recording_finished_shows_capture_diagnostics(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)

        window._on_recording_finished("silence", 6.24)

        assert window.status.text() == "Captured 6.2s · silence"
        window.close()


def test_settings_exposes_stable_turn_control_names(tmp_path):
    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog(AppConfig(), tmp_path / "settings.json")

    assert dialog.findChild(type(dialog._input_mode), "inputModeCombo") is dialog._input_mode
    assert dialog.findChild(type(dialog._pause_preset), "pausePresetCombo") is dialog._pause_preset
    assert dialog.findChild(type(dialog._review), "transcriptReviewCheck") is dialog._review
    dialog.close()


def test_pause_presets_persist_exact_seconds(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = AppConfig(silence_duration_sec=1.3)
    path = tmp_path / "settings.json"
    dialog = SettingsDialog(config, path)

    assert dialog._pause_preset.currentText() == "Custom"
    dialog._pause_preset.setCurrentText("Long")
    dialog._save()

    assert config.silence_duration_sec == 3.0
    dialog.close()


def test_response_audio_controls_follow_replay_state(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)

        assert window.replay_response_button.objectName() == "replayResponseButton"
        assert window.stop_audio_button.objectName() == "stopAudioButton"
        assert not window.replay_response_button.isEnabled()
        assert not window.stop_audio_button.isEnabled()

        window._pipeline = object()
        window._on_completed(
            TurnResult("Hello", "Hi there", CoachFeedback(), TurnMetrics(1, 0, False, None)),
            100,
        )
        window._on_waiting_for_ptt()

        assert window.replay_response_button.isEnabled()
        assert db.session_stats("session")["turns"] == 1
        window.close()


def test_completed_turn_renders_and_persists_feedback_separately(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)
        result = TurnResult(
            "I goed home",
            "What did you do there?",
            CoachFeedback(
                correction="I goed home → I went home",
                better_phrasing="I headed home.",
                category="verb_tense",
            ),
            TurnMetrics(3, 0, False, "verb_tense"),
        )

        window._on_completed(result, 100)

        text = window.history.toPlainText()
        assert "What did you do there?" in text
        assert "Coach feedback" in text
        assert "I goed home → I went home" in text
        assert db.feedback_for_session("session") == [result.feedback]
        assert db.recent_messages("session", 2)[1].content == "What did you do there?"
        window.close()


def test_progress_dialog_has_honest_empty_state():
    app = QApplication.instance() or QApplication([])

    class EmptyProgress:
        def stats(self, period_days, today):
            return ProgressStats(period_days, 0, 0, 0.0, 0, 0, None, None, {}, 0)

    dialog = ProgressDialog(EmptyProgress())

    assert dialog.status_label.text() == "Complete your first conversation to see progress"
    dialog.close()


def test_progress_dialog_requires_three_days_for_trend():
    app = QApplication.instance() or QApplication([])

    class SparseProgress:
        def stats(self, period_days, today):
            return ProgressStats(period_days, 2, 2, 20.0, 8, 80, 2.5, 0.25, {}, 3)

    dialog = ProgressDialog(SparseProgress())

    assert dialog.status_label.text() == "More practice days are needed for a trend"
    dialog.close()


def test_main_window_exposes_progress_action(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)

        assert window.progress_action.objectName() == "progressAction"
        assert window.progress_action.text() == "Progress…"
        window.close()
