import os
from unittest.mock import patch

import pytest
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.lifecycle import CaptureState
from ui.main_window import MainWindow
from utils.config import AppConfig


def _make_window(db, context):
    with patch.object(MainWindow, "_fetch_models", return_value=None):
        return MainWindow(
            AppConfig(), db, context, "session",
            auto_start=False, start_maximized=False,
        )


def test_window_tracks_only_validated_capture_states(tmp_path):
    app = QApplication.instance() or QApplication([])
    from nlp.llm import ConversationContext
    from storage.db import Database

    with Database(tmp_path / "conversations.db") as db:
        window = _make_window(db, ConversationContext())

        assert window._capture_state is CaptureState.READY
        window._set_capture_state(CaptureState.RECORDING)
        assert window._capture_state is CaptureState.RECORDING
        window._set_capture_state("processing")
        window._set_capture_state(CaptureState.READY)

        event = QCloseEvent()
        window.closeEvent(event)
        assert event.isAccepted()
        assert window._capture_state is CaptureState.SHUTDOWN
        with pytest.raises(ValueError, match="shutdown"):
            window._set_capture_state(CaptureState.READY)


def test_close_during_capture_requests_stop_before_shutdown(tmp_path):
    app = QApplication.instance() or QApplication([])

    class RunningWorker:
        def __init__(self):
            self.running = True
            self.interruptions = 0
            self.ends = 0
            self.starts = 0

        def isRunning(self):
            return self.running

        def requestInterruption(self):
            self.interruptions += 1

        def end_ptt(self):
            self.ends += 1

        def begin_ptt(self):
            self.starts += 1

    from nlp.llm import ConversationContext
    from storage.db import Database

    with Database(tmp_path / "conversations.db") as db:
        window = _make_window(db, ConversationContext())
        worker = RunningWorker()
        window.worker = worker
        window._set_capture_state(CaptureState.RECORDING)

        in_progress = QCloseEvent()
        window.closeEvent(in_progress)

        assert not in_progress.isAccepted()
        assert worker.interruptions == 1
        assert worker.ends == 1
        assert worker.starts == 1
        assert window._capture_state is CaptureState.RECORDING

        worker.running = False
        finished = QCloseEvent()
        window.closeEvent(finished)
        assert finished.isAccepted()
        assert window._capture_state is CaptureState.SHUTDOWN
