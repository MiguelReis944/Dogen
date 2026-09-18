import sqlite3
import pytest

from nlp.llm import ConversationContext
from storage.db import Database
from utils.config import AppConfig, load_config, save_config
from audio.vad import VoiceDetector


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


def test_external_ollama_host_is_rejected():
    with pytest.raises(ValueError, match="localhost"):
        AppConfig(ollama_host="https://remote.example.com")


def test_vad_stops_after_silence_but_not_before_speech():
    detector = VoiceDetector(threshold=0.02, silence_duration_sec=0.5, sample_rate=10)
    assert not detector.feed([0.0] * 5)
    assert not detector.feed([0.2] * 5)
    assert detector.feed([0.0] * 5)
