import sys
import threading
from types import SimpleNamespace

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from nlp.llm import ConversationContext
from pipeline import TurnCancelled
from ui.main_window import ConversationWorker
from utils.config import AppConfig


def _make_worker(monkeypatch, after_first_playback):
    app = QApplication.instance() or QApplication([])
    detector_stop = threading.Event()
    detector_opened = threading.Event()
    detector_closed = threading.Event()
    active_streams = set()
    streams_lock = threading.Lock()
    active_at_recording_start = []

    class FakeInputStream:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            with streams_lock:
                active_streams.add(self)
            detector_opened.set()
            return self

        def read(self, frames):
            detector_stop.wait(timeout=3)
            return np.zeros((frames, 1), dtype=np.float32), None

        def __exit__(self, _exc_type, _exc, _traceback):
            with streams_lock:
                active_streams.discard(self)
            detector_closed.set()
            return False

    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(InputStream=FakeInputStream))

    class FakeRecorder:
        def __init__(self, *_args, **_kwargs):
            pass

        def record(self, *_args, **_kwargs):
            with streams_lock:
                active_at_recording_start.append(len(active_streams))
            return SimpleNamespace(
                samples=np.ones(3200, dtype=np.float32),
                stop_reason="ptt_release",
                duration_sec=0.2,
            )

    class FakePipeline:
        llm = SimpleNamespace(model="mistral")

        def __init__(self):
            self.calls = 0
            self.after_first_playback = after_first_playback

        def run(self, _audio, _context, emit, _cancelled, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                emit("audio_playing", "")
                assert detector_opened.wait(timeout=1)
                self.after_first_playback()
            return None

    pipeline = FakePipeline()
    monkeypatch.setattr(ConversationWorker, "_warm_up_llm", lambda _self, _pipeline: True)
    monkeypatch.setattr("ui.conversation_worker.Recorder", FakeRecorder)
    worker = ConversationWorker(
        AppConfig(input_mode="ptt"), ConversationContext(), "mistral", pipeline=pipeline
    )
    # The fake blocking read is released only when production lifecycle cleanup
    # signals the detector to stop.
    worker._barge_in_stop_event = detector_stop

    waiting_count = 0

    def start_next_recording():
        nonlocal waiting_count
        waiting_count += 1
        if waiting_count <= 2:
            worker.begin_ptt()
        else:
            worker.requestInterruption()

    worker.waiting_for_ptt.connect(start_next_recording, Qt.DirectConnection)
    return (
        app,
        worker,
        pipeline,
        active_at_recording_start,
        active_streams,
        detector_closed,
        detector_stop,
    )


def test_barge_in_stream_closes_before_next_recording(monkeypatch):
    app, worker, _pipeline, active_at_recording_start, active_streams, detector_closed, detector_stop = (
        _make_worker(monkeypatch, lambda: None)
    )
    try:
        worker.start()
        assert worker.wait(2500)

        assert active_at_recording_start == [0, 0]
        assert detector_closed.is_set()
        assert not active_streams
    finally:
        detector_stop.set()
        if worker.isRunning():
            worker.wait(1000)


def test_barge_in_stream_closes_when_worker_is_interrupted(monkeypatch):
    app, worker, pipeline, _recording_starts, active_streams, detector_closed, detector_stop = (
        _make_worker(monkeypatch, lambda: None)
    )

    def interrupt_worker():
        worker.requestInterruption()
        raise TurnCancelled()

    pipeline.after_first_playback = interrupt_worker
    try:
        worker.start()
        assert worker.wait(2500)

        assert detector_closed.is_set()
        assert not active_streams
    finally:
        detector_stop.set()
        if worker.isRunning():
            worker.wait(1000)
