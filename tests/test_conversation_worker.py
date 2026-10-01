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
        AppConfig(input_mode="ptt"), object(), "mistral", pipeline=FakePipeline(),
        active_model="mistral",
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
        AppConfig(input_mode="ptt"), object(), "mistral", pipeline=pipeline,
        active_model="mistral",
    )
    worker._warm_up_llm = lambda _pipeline: True
    failures = []
    worker.waiting_for_ptt.connect(worker.begin_ptt, Qt.DirectConnection)
    worker.error.connect(failures.append, Qt.DirectConnection)

    with patch("ui.conversation_worker.log_diagnostic") as diagnostic:
        worker.start()
        assert worker.wait(2000)

    assert len(failures) == 1
    assert failures[0].startswith(
        "Microphone recording failed: microphone disconnected."
    )
    assert any(
        call.args[0] == "turn_failed" and call.kwargs.get("stage") == "capture"
        for call in diagnostic.call_args_list
    )
    assert not any(
        call.args[0] == "turn_failed" and call.kwargs.get("stage") == "startup"
        for call in diagnostic.call_args_list
    )


def test_tts_initialization_failure_explains_setup_and_retry(monkeypatch):
    app = QApplication.instance() or QApplication([])

    class FakeTranscriber:
        def __init__(self, *_args):
            pass

    class BrokenSynthesizer:
        def __init__(self, *_args):
            raise OSError("could not get source code")

    monkeypatch.setattr("ui.conversation_worker.Transcriber", FakeTranscriber)
    monkeypatch.setattr("ui.conversation_worker.Synthesizer", BrokenSynthesizer)
    worker = ConversationWorker(AppConfig(), object(), "mistral")
    failures = []
    worker.error.connect(failures.append, Qt.DirectConnection)

    worker.start()
    assert worker.wait(2000)

    assert failures == [
        "Could not load the local voice: could not get source code. "
        "Open File → Setup guide to install or repair the speech models, "
        "then choose Retry loading."
    ]


def test_whisper_initialization_failure_explains_setup_and_retry(monkeypatch):
    app = QApplication.instance() or QApplication([])

    class BrokenTranscriber:
        def __init__(self, *_args):
            raise FileNotFoundError("Whisper model 'small.en' is not cached")

    monkeypatch.setattr("ui.conversation_worker.Transcriber", BrokenTranscriber)
    worker = ConversationWorker(AppConfig(), object(), "mistral")
    failures = []
    worker.error.connect(failures.append, Qt.DirectConnection)

    worker.start()
    assert worker.wait(2000)

    assert failures == [
        "Could not load speech recognition: Whisper model 'small.en' is not cached. "
        "Open File → Setup guide to install or repair the speech models, "
        "then choose Retry loading."
    ]


def test_microphone_initialization_failure_explains_device_recovery(monkeypatch):
    app = QApplication.instance() or QApplication([])

    class FakeTranscriber:
        def __init__(self, *_args):
            pass

    class FakeSynthesizer:
        def __init__(self, *_args):
            pass

    class BrokenRecorder:
        def __init__(self, *_args, **_kwargs):
            raise OSError("No input device")

    monkeypatch.setattr("ui.conversation_worker.Transcriber", FakeTranscriber)
    monkeypatch.setattr("ui.conversation_worker.Synthesizer", FakeSynthesizer)
    monkeypatch.setattr("ui.conversation_worker.Recorder", BrokenRecorder)
    worker = ConversationWorker(AppConfig(), object(), "mistral")
    failures = []
    worker.error.connect(failures.append, Qt.DirectConnection)

    worker.start()
    assert worker.wait(2000)

    assert failures == [
        "Could not prepare the microphone: No input device. "
        "Check Windows microphone permissions and the selected input device, "
        "then choose Retry loading."
    ]


def test_turn_exception_explains_that_another_recording_can_be_tried(monkeypatch):
    app = QApplication.instance() or QApplication([])
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

    class BrokenPipeline:
        llm = SimpleNamespace(model="mistral")

        def run(self, *_args, **_kwargs):
            raise RuntimeError("temporary transcription failure")

    monkeypatch.setattr("ui.conversation_worker.Recorder", FakeRecorder)
    worker = ConversationWorker(
        AppConfig(input_mode="ptt"), object(), "mistral", pipeline=BrokenPipeline(),
        active_model="mistral",
    )
    worker._warm_up_llm = lambda _pipeline: True
    failures = []
    wait_count = []
    worker.error.connect(failures.append, Qt.DirectConnection)

    def advance_or_stop():
        wait_count.append(True)
        if len(wait_count) == 1:
            worker.begin_ptt()
        else:
            worker.requestInterruption()

    worker.waiting_for_ptt.connect(advance_or_stop, Qt.DirectConnection)
    worker.start()
    assert worker.wait(2000)

    assert failures == [
        "Turn failed: temporary transcription failure. "
        "The microphone is ready for another recording."
    ]
