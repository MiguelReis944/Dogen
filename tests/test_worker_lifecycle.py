import sys
from types import SimpleNamespace

import numpy as np
import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from nlp.llm import ConversationContext
from ui.conversation_worker import ConversationWorker
from utils.config import AppConfig


def _run_worker(monkeypatch, playback_action):
    app = QApplication.instance() or QApplication([])
    input_stream_attempts = []

    class ForbiddenInputStream:
        def __init__(self, **_kwargs):
            input_stream_attempts.append(True)
            raise AssertionError("playback must not open a microphone monitor")

    monkeypatch.setitem(
        sys.modules, "sounddevice", SimpleNamespace(InputStream=ForbiddenInputStream)
    )

    class FakeRecorder:
        def __init__(self, *_args, **_kwargs):
            pass

        def record(self, *_args, **_kwargs):
            return SimpleNamespace(
                samples=np.ones(3200, dtype=np.float32),
                stop_reason="ptt_release",
                duration_sec=0.2,
            )

    class FakePipeline:
        llm = SimpleNamespace(model="mistral")

        def __init__(self):
            self.cancelled_during_playback = None
            self.playback_stop_requested = None
            self.calls = 0

        def run(self, _audio, _context, emit, cancelled, playback_stop_requested=None, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                emit("audio_playing", "")
                self.cancelled_during_playback = cancelled()
                playback_action(worker, cancelled)
                self.playback_stop_requested = (
                    playback_stop_requested() if playback_stop_requested else False
                )
            return None

    pipeline = FakePipeline()
    monkeypatch.setattr(ConversationWorker, "_warm_up_llm", lambda _self, _pipeline: True)
    monkeypatch.setattr("ui.conversation_worker.Recorder", FakeRecorder)
    worker = ConversationWorker(
        AppConfig(input_mode="ptt"), ConversationContext(), "mistral", pipeline=pipeline,
        active_model="mistral",
    )

    wait_count = 0

    def handle_waiting_for_ptt():
        nonlocal wait_count
        wait_count += 1
        if wait_count == 1:
            worker.begin_ptt()
        else:
            worker.requestInterruption()

    worker.waiting_for_ptt.connect(handle_waiting_for_ptt, Qt.DirectConnection)
    return app, worker, pipeline, input_stream_attempts


def _user_speaks_during_playback(_worker, _cancelled):
    # Recording speech is no longer monitored as a playback cancellation signal.
    return None


def test_user_speech_does_not_cancel_playback_or_open_a_second_mic_stream(monkeypatch):
    app, worker, pipeline, input_stream_attempts = _run_worker(
        monkeypatch, _user_speaks_during_playback
    )
    try:
        worker.start()
        assert worker.wait(2500)

        assert pipeline.cancelled_during_playback is False
        assert pipeline.calls == 1
        assert input_stream_attempts == []
    finally:
        if worker.isRunning():
            worker.requestInterruption()
            worker.wait(1000)


def test_manual_stop_audio_still_cancels_playback(monkeypatch):
    def stop_audio(worker, cancelled):
        worker.stop_playback()
        assert not cancelled()

    app, worker, pipeline, input_stream_attempts = _run_worker(monkeypatch, stop_audio)
    ready_count = []
    worker.ready.connect(lambda: ready_count.append(True), Qt.DirectConnection)
    try:
        worker.start()
        assert worker.wait(2500)

        assert pipeline.cancelled_during_playback is False
        assert pipeline.playback_stop_requested is True
        assert pipeline.calls == 1
        assert ready_count == [True]
        assert input_stream_attempts == []
    finally:
        if worker.isRunning():
            worker.requestInterruption()
            worker.wait(1000)
