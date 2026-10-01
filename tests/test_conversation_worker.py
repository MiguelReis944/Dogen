import os
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from ui.conversation_worker import ConversationWorker
from utils.config import AppConfig


def test_conversation_worker_preserves_recording_and_turn_signal_contract(monkeypatch):
    recording = SimpleNamespace(
        samples=np.array([0.1, 0.2], dtype=np.float32),
        stop_reason="ptt_release",
        duration_sec=0.25,
    )

    class FakeRecorder:
        def __init__(self, *_args):
            pass

        def record(self, *_args, **_kwargs):
            return recording

    monkeypatch.setattr("ui.conversation_worker.Recorder", FakeRecorder)

    result = object()

    class FakePipeline:
        llm = SimpleNamespace(model="mistral")

        def run(self, _samples, _context, emit, _cancelled, **_kwargs):
            emit("transcribed", "hello there")
            emit("response_chunk", "Hi!")
            return result

    worker = ConversationWorker(
        AppConfig(input_mode="ptt"), object(), "mistral", pipeline=FakePipeline()
    )
    worker._warm_up_llm = lambda _pipeline: True
    events = {name: [] for name in (
        "waiting", "recording_started", "recording_finished", "transcribed",
        "response_chunk", "turn_completed", "ready", "error",
    )}
    worker.waiting_for_ptt.connect(worker.begin_ptt, Qt.DirectConnection)
    worker.ready.connect(worker.requestInterruption, Qt.DirectConnection)
    worker.waiting_for_ptt.connect(
        lambda: events["waiting"].append(True), Qt.DirectConnection
    )
    worker.recording_started.connect(
        lambda: events["recording_started"].append(True), Qt.DirectConnection
    )
    worker.recording_finished.connect(
        lambda reason, seconds: events["recording_finished"].append((reason, seconds)),
        Qt.DirectConnection,
    )
    worker.transcribed.connect(events["transcribed"].append, Qt.DirectConnection)
    worker.response_chunk.connect(events["response_chunk"].append, Qt.DirectConnection)
    worker.turn_completed.connect(
        lambda turn, latency: events["turn_completed"].append((turn, latency)),
        Qt.DirectConnection,
    )
    worker.ready.connect(
        lambda: events["ready"].append(True), Qt.DirectConnection
    )
    worker.error.connect(events["error"].append, Qt.DirectConnection)

    worker.start()
    assert worker.wait(2000)

    assert events["waiting"] == [True]
    assert events["recording_started"] == [True]
    assert events["recording_finished"] == [("ptt_release", 0.25)]
    assert events["transcribed"] == ["hello there"]
    assert events["response_chunk"] == ["Hi!"]
    assert len(events["turn_completed"]) == 1
    assert events["turn_completed"][0][0] is result
    assert isinstance(events["turn_completed"][0][1], int)
    assert events["ready"] == [True]
    assert events["error"] == []


def test_capture_failure_is_diagnosed_as_capture_not_startup(monkeypatch):
    app = QApplication.instance() or QApplication([])

    class BrokenRecorder:
        def __init__(self, *_args, **_kwargs):
            pass

        def record(self, *_args, **_kwargs):
            raise OSError("microphone disconnected")

    monkeypatch.setattr("ui.conversation_worker.Recorder", BrokenRecorder)
    pipeline = SimpleNamespace(llm=SimpleNamespace(model="mistral"))
    worker = ConversationWorker(
        AppConfig(input_mode="ptt"), object(), "mistral", pipeline=pipeline
    )
    worker._warm_up_llm = lambda _pipeline: True
    failures = []
    worker.waiting_for_ptt.connect(worker.begin_ptt, Qt.DirectConnection)
    worker.error.connect(failures.append, Qt.DirectConnection)

    with patch("ui.conversation_worker.log_diagnostic") as diagnostic:
        worker.start()
        assert worker.wait(2000)

    assert failures == ["microphone disconnected"]
    assert any(
        call.args[0] == "turn_failed" and call.kwargs.get("stage") == "capture"
        for call in diagnostic.call_args_list
    )
    assert not any(
        call.args[0] == "turn_failed" and call.kwargs.get("stage") == "startup"
        for call in diagnostic.call_args_list
    )
