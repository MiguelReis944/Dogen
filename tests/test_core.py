import sqlite3
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from audio.recorder import Recorder, RecordingResult
from nlp.llm import ConversationContext, OllamaClient
from nlp.feedback import CoachFeedback
from nlp.transcriber import _looks_like_silence
from storage.db import Database
from storage.models import TurnMetrics
from utils.config import AppConfig, load_config, save_config
from audio.vad import VoiceDetector


def _fake_sounddevice(monkeypatch, chunks):
    class FakeInputStream:
        def __init__(self, callback, **kwargs):
            self.callback = callback

        def __enter__(self):
            for samples in chunks:
                block = np.asarray(samples, dtype=np.float32).reshape(-1, 1)
                self.callback(block, len(block), None, None)
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(InputStream=FakeInputStream))


def test_recorder_reports_ptt_release(monkeypatch):
    _fake_sounddevice(monkeypatch, [np.ones(3200, dtype=np.float32)])
    monkeypatch.setattr("audio.recorder._denoise", lambda samples, rate: samples)

    result = Recorder().record(lambda: False, stop_fn=lambda: True)

    assert result.stop_reason == "ptt_release"
    assert result.samples.dtype == np.float32
    assert result.samples.ndim == 1
    assert result.duration_sec >= 0


def test_recorder_applies_noise_reduction_when_enabled(monkeypatch):
    _fake_sounddevice(monkeypatch, [np.ones(3200, dtype=np.float32)])
    calls = []

    def denoise(samples, rate):
        calls.append((samples.copy(), rate))
        return samples

    monkeypatch.setattr("audio.recorder._denoise", denoise)

    Recorder(noise_reduction=True).record(lambda: False, stop_fn=lambda: True)

    assert len(calls) == 1
    assert calls[0][1] == 16000


def test_recorder_skips_noise_reduction_when_disabled(monkeypatch):
    _fake_sounddevice(monkeypatch, [np.ones(3200, dtype=np.float32)])

    def unexpected_denoise(samples, rate):
        raise AssertionError("denoise must not run")

    monkeypatch.setattr("audio.recorder._denoise", unexpected_denoise)

    result = Recorder(noise_reduction=False).record(lambda: False, stop_fn=lambda: True)

    assert result.samples.dtype == np.float32
    assert result.samples.size == 3200


def test_recorder_reports_silence(monkeypatch):
    _fake_sounddevice(
        monkeypatch,
        [np.full(1600, 0.1, dtype=np.float32), np.zeros(1600, dtype=np.float32)],
    )
    monkeypatch.setattr("audio.recorder._denoise", lambda samples, rate: samples)

    result = Recorder(threshold=0.02, silence_duration_sec=0.1).record(lambda: False)

    assert result.stop_reason == "silence"
    assert result.samples.size == 3200


def test_recorder_reports_timeout(monkeypatch):
    _fake_sounddevice(monkeypatch, [])
    times = iter([0.0, 61.0, 61.0])
    monkeypatch.setattr("audio.recorder.monotonic", lambda: next(times))

    result = Recorder().record(lambda: False)

    assert isinstance(result, RecordingResult)
    assert result.stop_reason == "timeout"
    assert result.samples.size == 0
    assert result.duration_sec == 61.0


def test_recorder_reports_cancellation(monkeypatch):
    _fake_sounddevice(monkeypatch, [])

    result = Recorder().record(lambda: True)

    assert result.stop_reason == "cancelled"
    assert result.samples.size == 0


def test_recorder_reuses_learned_noise_floor(monkeypatch):
    initial_floors = []

    class SpyVoiceDetector(VoiceDetector):
        def __init__(self, threshold, silence_duration_sec, sample_rate, initial_noise_floor=0.0):
            initial_floors.append(initial_noise_floor)
            super().__init__(threshold, silence_duration_sec, sample_rate, initial_noise_floor)

    monkeypatch.setattr("audio.recorder.VoiceDetector", SpyVoiceDetector)
    _fake_sounddevice(
        monkeypatch,
        [
            np.full(1600, 0.01, dtype=np.float32),
            np.full(1600, 0.1, dtype=np.float32),
            np.zeros(1600, dtype=np.float32),
        ],
    )
    monkeypatch.setattr("audio.recorder._denoise", lambda samples, rate: samples)
    recorder = Recorder(threshold=0.02, silence_duration_sec=0.1)

    recorder.record(lambda: False)
    learned_floor = recorder._noise_floor
    recorder.record(lambda: True)

    assert learned_floor > 0
    assert initial_floors == [0.0, learned_floor]


def test_context_keeps_complete_recent_turns():
    context = ConversationContext(max_history=2)
    for number in range(3):
        context.add_message("user", f"question {number}")
        context.add_message("assistant", f"answer {number}")
    assert [m["content"] for m in context.messages] == [
        "question 1", "answer 1", "question 2", "answer 2"
    ]
    assert context.get_messages_for_ollama()[0]["role"] == "system"


def test_database_persists_and_reloads_session(tmp_path):
    path = tmp_path / "conversations.db"
    with Database(path) as db:
        db.add_message("session-1", "user", "Hello", "mistral", 123)
        db.add_message("session-1", "assistant", "Hi", "mistral", 456)
        assert [m.content for m in db.recent_messages("session-1", 10)] == ["Hello", "Hi"]
        db.set_setting("speaker_device", "2")
        assert db.get_setting("speaker_device") == "2"
    with sqlite3.connect(path) as connection:
        assert connection.execute("select count(*) from conversations").fetchone()[0] == 2


def test_turn_insert_is_atomic(tmp_path):
    path = tmp_path / "conversations.db"
    with Database(path) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.add_turn("session", "Hello", None, "mistral", 10)
        assert db.recent_messages("session", 10) == []


def test_corrupt_database_is_backed_up_and_recreated(tmp_path):
    path = tmp_path / "conversations.db"
    path.write_bytes(b"not a SQLite database")
    with Database(path) as db:
        assert db.recent_messages("new", 10) == []
    backups = list(tmp_path.glob("conversations.db.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"not a SQLite database"


def test_config_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    save_config(AppConfig(ollama_model="custom"), path)
    assert load_config(path).ollama_model == "custom"


def test_fresh_config_uses_safe_push_to_talk_defaults():
    config = AppConfig()

    assert config.input_mode == "ptt"
    assert config.silence_duration_sec == 2.0
    assert config.noise_reduction is True


def test_existing_turn_settings_are_preserved(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"input_mode": "vad", "silence_duration_sec": 1.3}')

    config = load_config(path)

    assert config.input_mode == "vad"
    assert config.silence_duration_sec == 1.3


def test_external_ollama_host_is_rejected():
    with pytest.raises(ValueError, match="localhost"):
        AppConfig(ollama_host="https://remote.example.com")


def test_vad_stops_after_silence_but_not_before_speech():
    detector = VoiceDetector(threshold=0.02, silence_duration_sec=0.5, sample_rate=10)
    assert not detector.feed([0.0] * 5)
    assert not detector.feed([0.2] * 5)
    assert detector.feed([0.0] * 5)


def test_vad_noise_floor_only_updated_during_pre_speech_silence():
    """Speech samples must not contaminate the noise floor estimate."""
    detector = VoiceDetector(threshold=0.001, silence_duration_sec=1.0, sample_rate=100)
    # Pre-speech silence with known RMS ≈ 0.01
    for _ in range(10):
        detector.feed([0.01] * 10)
    floor_after_silence = detector._noise_floor
    # Feed loud speech samples
    detector.feed([1.0] * 10)
    # Noise floor must not have moved up from the speech block
    assert detector._noise_floor == floor_after_silence


def test_vad_noise_floor_adapts_to_quiet_background():
    """Over many silent blocks the noise floor converges toward the actual RMS."""
    detector = VoiceDetector(threshold=100.0, silence_duration_sec=1.0, sample_rate=100)
    rms = 0.05
    for _ in range(200):
        detector.feed([rms] * 10)
    assert abs(detector._noise_floor - rms) < 0.01


def test_config_unknown_keys_are_silently_ignored(tmp_path):
    import json
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"ollama_model": "llama3", "unknown_future_key": 42}))
    cfg = load_config(path)
    assert cfg.ollama_model == "llama3"


def test_session_full_stats_counts_turns_and_corrections(tmp_path):
    path = tmp_path / "conversations.db"
    with Database(path) as db:
        db.add_turn("s1", "I goed to school", "Nice! [Correction: I goed → I went]", "mistral", 100)
        db.add_turn("s1", "Hello", "Hi there", "mistral", 100)
        stats = db.session_full_stats("s1")
        assert stats["turns"] == 2
        assert stats["corrections"] == 1
        assert len(stats["vocab"]) == 1
        assert stats["vocab"][0].original == "I goed"
        assert stats["vocab"][0].corrected == "I went"
        assert stats["minutes"] >= 0


def test_database_saves_structured_feedback_only_when_present(tmp_path):
    path = tmp_path / "conversations.db"
    with Database(path) as db:
        db.save_feedback("s1", CoachFeedback())
        db.save_feedback(
            "s1",
            CoachFeedback(
                correction="I goed → I went",
                better_phrasing="I went there.",
                category="verb_tense",
            ),
        )
        rows = db.connection.execute(
            "SELECT correction,better_phrasing,category FROM feedback"
        ).fetchall()

    assert rows == [("I goed → I went", "I went there.", "verb_tense")]


def test_database_persists_completed_turn_metrics(tmp_path):
    path = tmp_path / "conversations.db"
    metrics = TurnMetrics(
        word_count=4,
        filler_count=0,
        transcript_edited=True,
        correction_category="verb_tense",
    )
    feedback = CoachFeedback(correction="I goed → I went", category="verb_tense")
    with Database(path) as db:
        db.add_completed_turn("s1", "I went home", "Tell me more.", "mistral", 120, feedback, metrics)
        row = db.connection.execute(
            "SELECT word_count,filler_count,transcript_edited,correction_category "
            "FROM turn_metrics"
        ).fetchone()
        stats = db.session_full_stats("s1")

    assert row == (4, 0, 1, "verb_tense")
    assert stats["fillers"] == 0


def test_completed_turn_write_is_atomic(tmp_path):
    path = tmp_path / "conversations.db"
    metrics = TurnMetrics(0, 0, False, None)
    with Database(path) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.add_completed_turn(
                "s1", "Hello", None, "mistral", 10, CoachFeedback(), metrics
            )
        assert db.recent_messages("s1", 10) == []
        assert db.connection.execute("SELECT COUNT(*) FROM turn_metrics").fetchone()[0] == 0


def test_vad_seeds_from_initial_noise_floor():
    """Recorder carries the learned noise floor into the next turn's detector."""
    detector = VoiceDetector(threshold=100.0, silence_duration_sec=1.0, sample_rate=100,
                             initial_noise_floor=0.05)
    assert detector._noise_floor == 0.05


def test_transcriber_treats_all_non_speech_segments_as_silence():
    segments = [{"no_speech_prob": 0.9}, {"no_speech_prob": 0.75}]
    assert _looks_like_silence(segments) is True


def test_transcriber_keeps_text_when_any_segment_is_speech():
    segments = [{"no_speech_prob": 0.9}, {"no_speech_prob": 0.1}]
    assert _looks_like_silence(segments) is False


def test_transcriber_empty_segments_is_not_silence():
    assert _looks_like_silence([]) is False


def test_ollama_client_sets_context_window(monkeypatch):
    """Ollama defaults to a 2048-token window; without num_ctx, long conversation
    history silently truncates instead of erroring."""
    calls = []

    class FakeOllamaClient:
        def __init__(self, host, timeout):
            pass

        def chat(self, model, messages, stream, options=None, keep_alive=None):
            calls.append((options, keep_alive))
            return iter([])

    monkeypatch.setattr("ollama.Client", FakeOllamaClient)
    client = OllamaClient("http://localhost:11434", "mistral")
    client.generate([], lambda token: None, lambda: False)
    assert calls == [({"num_ctx": 4096}, -1)]


def test_database_session_per_day(tmp_path):
    """latest_session_id and set_setting enable one session per calendar day."""
    path = tmp_path / "conversations.db"
    with Database(path) as db:
        assert db.get_setting("session_date") is None
        db.set_setting("session_date", "2026-09-18")
        db.add_message("session-today", "user", "hi", "mistral", 100)
        assert db.get_setting("session_date") == "2026-09-18"
        # Simulating a new day: overwrite the date
        db.set_setting("session_date", "2026-09-19")
        assert db.get_setting("session_date") == "2026-09-19"
