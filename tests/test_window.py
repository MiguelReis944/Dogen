import os
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QPushButton

from nlp.llm import ConversationContext
from nlp.feedback import CoachFeedback
from pipeline import TurnResult
from storage.db import Database
from storage.models import TurnMetrics
from storage.progress import ProgressStats
from ui.main_window import ConversationWorker, MainWindow
from ui.progress_dialog import ProgressDialog
from ui.settings_dialog import SettingsDialog
from utils.config import AppConfig


def _make_window(db, cfg=None, session="session"):
    """Create a MainWindow with ModelFetcher patched out (no Ollama connection)."""
    if cfg is None:
        cfg = AppConfig()
    with patch.object(MainWindow, "_fetch_models", return_value=None):
        return MainWindow(
            cfg, db, ConversationContext(), session,
            auto_start=False, start_maximized=False,
        )


def test_window_opens_maximized_and_schedules_engine_without_recording(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        with (
            patch.object(MainWindow, "_fetch_models", return_value=None),
            patch.object(MainWindow, "start", return_value=None) as start,
        ):
            window = MainWindow(
                AppConfig(), db, ConversationContext(), "session",
                auto_start=True, start_maximized=True,
            )
            app.processEvents()

        assert start.call_count == 1
        assert window.windowState() & Qt.WindowMaximized
        assert window.record_button.text() == "Loading…"
        assert not window.record_button.isEnabled()
        assert window.worker is None
        window.close()


def test_closing_before_first_event_cancels_automatic_start(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        with (
            patch.object(MainWindow, "_fetch_models", return_value=None),
            patch.object(MainWindow, "start", return_value=None) as start,
        ):
            window = MainWindow(
                AppConfig(), db, ConversationContext(), "session",
                auto_start=True, start_maximized=False,
            )
            window.close()
            app.processEvents()

        assert start.call_count == 0


def test_ollama_warmup_failure_keeps_worker_unavailable():
    app = QApplication.instance() or QApplication([])

    class BrokenWarmupClient:
        def list(self):
            return []

        def generate(self, **kwargs):
            raise RuntimeError("model is missing")

    pipeline = SimpleNamespace(
        llm=SimpleNamespace(client=BrokenWarmupClient(), model="missing")
    )
    worker = ConversationWorker(AppConfig(), ConversationContext(), "missing")
    errors = []
    worker.error.connect(errors.append)

    assert not worker._warm_up_llm(pipeline)
    assert errors == ["Could not load missing: model is missing"]


def test_ollama_warmup_requests_resident_model():
    app = QApplication.instance() or QApplication([])
    client = MagicMock()
    pipeline = SimpleNamespace(llm=SimpleNamespace(client=client, model="mistral"))
    worker = ConversationWorker(AppConfig(), ConversationContext(), "mistral")

    assert worker._warm_up_llm(pipeline)
    assert client.generate.call_args.kwargs["keep_alive"] == -1


def test_window_keeps_dogen_name_and_single_record_control(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)
        assert window.windowTitle() == "Dogen"
        assert window.record_button.text() == "Start recording"
        visible_controls = [
            button for button in window.centralWidget().findChildren(QPushButton)
            if not window._review_bar.isAncestorOf(button)
        ]
        assert visible_controls == [window.record_button]
        window.close()


def test_window_has_stable_minimum_and_capture_hud(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)
        assert window.minimumWidth() >= 1100
        assert window.minimumHeight() >= 700
        assert window.capture_hud is not None
        assert window.status_group is None
        window.close()


def test_volume_is_hidden_outside_recording(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)
        window._set_capture_state("ready", "Ready")
        window._render_volume(0.9)
        assert window.volume_bar.value() == 0
        window._set_capture_state("recording")
        window._render_volume(0.9)
        assert window.volume_bar.value() > 0
        window.close()


def test_record_button_clicks_start_and_finish_capture(tmp_path):
    app = QApplication.instance() or QApplication([])

    class RunningWorker:
        def __init__(self):
            self.started = 0
            self.ended = 0

        def isRunning(self):
            return True

        def begin_ptt(self):
            self.started += 1

        def end_ptt(self):
            self.ended += 1

    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)
        worker = RunningWorker()
        window.worker = worker
        window._on_waiting_for_ptt()
        assert worker.started == 0

        window.record_button.click()
        assert worker.started == 1

        window._on_recording_started()
        assert window.record_button.text() == "Finish recording"
        window.record_button.click()
        assert worker.ended == 1
        window.close()


def test_ptt_wait_clears_old_events_before_announcing_ready():
    app = QApplication.instance() or QApplication([])
    worker = ConversationWorker(AppConfig(), ConversationContext(), "mistral")
    worker._ptt_start_event.set()
    worker._ptt_stop_event.set()
    worker.waiting_for_ptt.connect(worker.begin_ptt)

    worker._prepare_ptt_wait()

    assert worker._ptt_start_event.is_set()
    assert not worker._ptt_stop_event.is_set()


def test_loading_message_uses_meter_region_until_worker_is_ready(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)

        window._set_status("Loading local speech models...")
        assert window.capture_stack.currentWidget() is window.loading_status
        assert window.loading_status.text() == "Loading local speech models..."

        window._on_waiting_for_ptt()
        assert window.capture_stack.currentWidget() is window.loading_status
        window.close()


def test_file_menu_owns_secondary_actions(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)
        file_menu = window.file_menu
        labels = {action.text() for action in file_menu.actions()}

        assert {
            "New session", "Vocabulary", "Practice progress", "Replay response",
            "Stop audio", "Settings", "Export session", "Exit",
        } <= labels
        window.close()


def test_file_menu_owns_model_and_scenario_selection(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)
        window._on_models_ready(["llama3", "mistral"])
        file_menu = window.menuBar().actions()[0].menu()
        menus = {action.text(): action.menu() for action in file_menu.actions() if action.menu()}

        assert {"Model", "Scenario"} <= menus.keys()
        next(action for action in menus["Model"].actions() if action.text() == "llama3").trigger()
        next(
            action for action in menus["Scenario"].actions()
            if action.text() == "Job interview"
        ).trigger()

        assert window._selected_model() == "llama3"
        assert window._selected_scenario == "Job interview"
        assert not hasattr(window, "model_combo")
        assert not hasattr(window, "scenario_combo")
        window.close()


def test_configuration_actions_are_locked_while_worker_runs(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)

        with patch.object(ConversationWorker, "start", return_value=None):
            window.start()

        assert not window.flow_action.isEnabled()
        assert not window.model_menu.isEnabled()
        assert not window.scenario_menu.isEnabled()
        assert not window.settings_action.isEnabled()

        window._on_finished()
        assert window.flow_action.isEnabled()
        assert window.model_menu.isEnabled()
        assert window.scenario_menu.isEnabled()
        assert window.settings_action.isEnabled()
        window.close()


def test_only_female_voice_is_available(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        cfg = AppConfig(tts_model="tts_models/en/sam/tacotron-DDC")
        window = _make_window(db, cfg)

        assert cfg.tts_model == "tts_models/en/ljspeech/tacotron2-DDC"
        assert not hasattr(window, "voice_combo")
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
        assert window.record_button.text() == "Unavailable"
        assert not window.record_button.isEnabled()
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


def test_on_models_ready_populates_menu(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)
        window._on_models_ready(["llama3", "mistral", "phi3"])
        texts = [action.text() for action in window.model_menu.actions()]
        assert texts == ["llama3", "mistral", "phi3"]
        assert window.model_menu.isEnabled()
        window.close()


def test_on_models_ready_empty_falls_back_to_config(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        cfg = AppConfig(ollama_model="mistral")
        window = _make_window(db, cfg)
        window._on_models_ready([])
        assert window._selected_model() == "mistral"
        assert window.model_menu.isEnabled()
        window.close()


def test_recording_finished_shows_capture_diagnostics(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)

        window._on_recording_finished("silence", 6.24)

        assert window.status.text() == "Captured 6.2s · silence"
        window.close()


def test_settings_persists_click_controlled_recording(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = AppConfig(input_mode="vad", silence_duration_sec=1.3)
    dialog = SettingsDialog(config, tmp_path / "settings.json")

    assert dialog.findChild(type(dialog._review), "transcriptReviewCheck") is dialog._review
    dialog._save()

    assert config.input_mode == "ptt"
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


def test_quiet_speech_has_visible_meter_without_changing_vad(tmp_path):
    app = QApplication.instance() or QApplication([])
    config = AppConfig(vad_threshold=0.02)
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db, config)
        window._set_capture_state("recording")
        window._on_volume(0.08)
        assert window.volume_bar.value() > 40
        assert config.vad_threshold == 0.02
        window._set_capture_state("processing")
        assert window.volume_bar.value() == 0
        window.close()


def test_next_worker_reuses_completed_pipeline(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)
        pipeline = object()
        window.worker = SimpleNamespace(built_pipeline=pipeline, isRunning=lambda: False)
        window._on_finished()
        with patch.object(ConversationWorker, "start", return_value=None):
            window.start()
        assert window.worker._prebuilt_pipeline is pipeline
        window.close()


def test_file_menu_actions_call_existing_handlers(tmp_path):
    app = QApplication.instance() or QApplication([])
    handlers = {
        "New session": "_end_session",
        "Export session": "_export_session",
        "Practice progress": "_show_progress",
        "Vocabulary": "_show_vocab",
        "Settings": "_open_settings",
    }
    with Database(tmp_path / "conversation.db") as db:
        with (
            patch.object(MainWindow, "_fetch_models", return_value=None),
            patch.object(MainWindow, "_end_session") as new_session,
            patch.object(MainWindow, "_export_session") as export,
            patch.object(MainWindow, "_show_progress") as progress,
            patch.object(MainWindow, "_show_vocab") as vocabulary,
            patch.object(MainWindow, "_open_settings") as settings,
        ):
            window = MainWindow(
                AppConfig(), db, ConversationContext(), "session",
                auto_start=False, start_maximized=False,
            )
            mocks = dict(zip(handlers, (new_session, export, progress, vocabulary, settings)))
            for action in window.file_menu.actions():
                if action.text() in mocks:
                    action.trigger()
                    mocks[action.text()].assert_called_once()
            window.close()


def test_export_session_contains_only_current_session(tmp_path):
    app = QApplication.instance() or QApplication([])
    target = tmp_path / "session.txt"
    with Database(tmp_path / "conversation.db") as db:
        db.add_message("older", "user", "Do not export this", "mistral", 0)
        db.add_message("session", "user", "Export this", "mistral", 0)
        window = _make_window(db)
        with patch("ui.main_window.QFileDialog.getSaveFileName", return_value=(str(target), "")):
            window._export_session()
        assert "Export this" in target.read_text(encoding="utf-8")
        assert "Do not export this" not in target.read_text(encoding="utf-8")
        window.close()


def test_export_session_includes_messages_beyond_recent_history_limit(tmp_path):
    app = QApplication.instance() or QApplication([])
    target = tmp_path / "long-session.txt"
    with Database(tmp_path / "conversation.db") as db:
        with db.connection:
            db.connection.executemany(
                "INSERT INTO conversations(session_id,role,content,model_used,latency_ms) "
                "VALUES(?,?,?,?,?)",
                (("session", "user", f"Message {index}", "mistral", 0)
                 for index in range(10001)),
            )
        window = _make_window(db)
        with patch("ui.main_window.QFileDialog.getSaveFileName", return_value=(str(target), "")):
            window._export_session()
        exported = target.read_text(encoding="utf-8")
        assert exported.count("You: Message ") == 10001
        assert "You: Message 0\n" in exported
        assert "You: Message 10000\n" in exported
        assert exported.index("You: Message 0\n") < exported.index("You: Message 10000\n")
        window.close()


def test_replay_completion_returns_capture_hud_to_ready(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)
        window._last_assistant_text = "Replay this response"
        window._pipeline = object()

        window._on_audio_playing()
        assert window._capture_state == "processing"
        assert window.status.text() == "Playing audio..."

        window._on_replay_finished()
        assert window._capture_state == "ready"
        assert window.status.text() == "Ready — click Start recording to speak"
        assert window.capture_stack.currentWidget() is window.loading_status

        window._on_recording_started()
        assert window._capture_state == "recording"
        assert window.record_button.text() == "Finish recording"
        window.close()


def test_replay_error_keeps_start_recording_operational(tmp_path):
    app = QApplication.instance() or QApplication([])

    class RunningWorker:
        def __init__(self):
            self.started = 0

        def isRunning(self):
            return True

        def begin_ptt(self):
            self.started += 1

    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)
        window._last_assistant_text = "Replay this response"
        window._pipeline = object()
        worker = RunningWorker()
        window.worker = worker
        window._on_waiting_for_ptt()

        window._on_audio_playing()
        window._on_replay_error("speaker unavailable")
        window._on_replay_finished()

        assert window._capture_state == "ready"
        assert window.status.text() == "Could not play this response: speaker unavailable"
        assert window.record_button.isEnabled()
        assert window.record_button.text() == "Start recording"
        window.record_button.click()
        assert worker.started == 1
        assert window.record_button.text() == "Starting…"
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

        conversation = window.history.toPlainText()
        fixes = window.fixes.toPlainText()
        assert "What did you do there?" in conversation
        assert "Coach feedback" not in conversation
        assert "I goed home → I went home" not in conversation
        assert "I goed home → I went home" in fixes
        assert "I headed home." in fixes
        assert "Category: verb tense" in fixes
        assert window.fixes_group.title() == "Fixes"
        assert window.status_group is None
        assert db.feedback_for_session("session") == [result.feedback]
        assert db.recent_messages("session", 2)[1].content == "What did you do there?"
        window.close()


def test_today_shows_passive_activity_metrics_without_action_buttons(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        db.add_completed_turn(
            "session",
            "I goed home",
            "What did you do there?",
            "mistral",
            100,
            CoachFeedback(
                correction="I goed home → I went home",
                category="verb_tense",
            ),
            TurnMetrics(50, 2, False, "verb_tense"),
        )
        window = _make_window(db)

        summary = window.today.text().lower()
        assert not window.today.findChildren(QPushButton)
        assert "active minutes" in summary
        assert "words spoken" in summary
        assert "completed turns" in summary
        assert "fillers / 100 words" in summary
        assert "corrections" in summary
        assert "streak" in summary
        assert "words spoken: 50" in summary
        assert "completed turns: 1" in summary
        assert "fillers / 100 words: 4.0" in summary
        assert "corrections: 1" in summary
        window.close()


def test_today_includes_turns_after_21_local_when_utc_date_has_advanced(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    local_day = date(2026, 9, 28)
    sao_paulo_timezone = timezone(-timedelta(hours=3))

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(local_day.year, local_day.month, local_day.day)

    class SaoPauloDateTime(datetime):
        @classmethod
        def combine(cls, date_value, time_value, tzinfo=None):
            return datetime.combine(
                date_value,
                time_value,
                tzinfo=tzinfo or sao_paulo_timezone,
            )

    utc_created_at = datetime.combine(
        local_day, time(21, 30), tzinfo=sao_paulo_timezone
    ).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    assert utc_created_at.startswith("2026-09-29 ")

    with Database(tmp_path / "conversation.db") as db:
        db.add_completed_turn(
            "session",
            "I went home",
            "What did you do there?",
            "mistral",
            100,
            CoachFeedback(correction="I go → I went", category="verb_tense"),
            TurnMetrics(4, 0, False, "verb_tense"),
        )
        for table in ("conversations", "turn_metrics", "feedback", "vocab"):
            db.connection.execute(
                f"UPDATE {table} SET created_at=? WHERE session_id=?",
                (utc_created_at, "session"),
            )
        monkeypatch.setattr("ui.main_window.date", FixedDate)
        monkeypatch.setattr("ui.main_window.datetime", SaoPauloDateTime)
        window = _make_window(db)

        summary = window.today.text().lower()
        assert "completed turns: 1" in summary
        assert "words spoken: 4" in summary
        assert "corrections: 1" in summary
        assert "streak: 1" in summary
        window.close()


def test_today_counts_feedback_correction_without_arrow_or_vocabulary(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        db.add_completed_turn(
            "session",
            "I went home",
            "What did you do there?",
            "mistral",
            100,
            CoachFeedback(correction="Use the past tense here", category="verb_tense"),
            TurnMetrics(4, 0, False, "verb_tense"),
        )
        db.clear_vocab()
        assert db.get_vocab_for_session("session") == []
        window = _make_window(db)

        assert "corrections: 1" in window.today.text().lower()
        window.close()


def test_fixes_is_read_only_without_correction_input(tmp_path):
    app = QApplication.instance() or QApplication([])
    with Database(tmp_path / "conversation.db") as db:
        window = _make_window(db)

        assert window.fixes.isReadOnly()
        assert not hasattr(window, "correction_input")
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
        assert window.progress_action.text() == "Practice progress"
        window.close()
