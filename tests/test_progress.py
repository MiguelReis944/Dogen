from datetime import date

from storage.db import Database
from storage.progress import ProgressService


def _insert_turn(db, session_id, day, words=None, fillers=0, edited=0, category=None):
    timestamp = f"{day} 12:00:00"
    db.connection.executemany(
        "INSERT INTO conversations(session_id,created_at,role,content) VALUES(?,?,?,?)",
        [
            (session_id, timestamp, "user", "hello"),
            (session_id, timestamp, "assistant", "hi"),
        ],
    )
    if words is not None:
        db.connection.execute(
            "INSERT INTO turn_metrics(session_id,created_at,word_count,filler_count,"
            "transcript_edited,correction_category) VALUES(?,?,?,?,?,?)",
            (session_id, timestamp, words, fillers, edited, category),
        )
    db.connection.commit()


def test_progress_empty_database_has_unknown_rates(tmp_path):
    with Database(tmp_path / "db.sqlite") as db:
        stats = ProgressService(db).stats(7, date(2026, 9, 26))

    assert stats.practiced_days == 0
    assert stats.completed_turns == 0
    assert stats.fillers_per_100_words is None
    assert stats.transcript_edit_rate is None


def test_progress_counts_activity_and_objective_rates(tmp_path):
    with Database(tmp_path / "db.sqlite") as db:
        _insert_turn(db, "s1", "2026-09-26", words=10, fillers=2, edited=1, category="grammar")
        _insert_turn(db, "s1", "2026-09-26", words=10, fillers=0, edited=0)
        stats = ProgressService(db).stats(7, date(2026, 9, 26))

    assert stats.practiced_days == 1
    assert stats.current_streak == 1
    assert stats.completed_turns == 2
    assert stats.words_transcribed == 20
    assert stats.fillers_per_100_words == 10.0
    assert stats.transcript_edit_rate == 0.5
    assert stats.corrections_by_category == {"grammar": 1}


def test_progress_streak_crosses_month_boundary(tmp_path):
    with Database(tmp_path / "db.sqlite") as db:
        _insert_turn(db, "s1", "2026-08-31", words=1)
        _insert_turn(db, "s2", "2026-09-01", words=1)
        _insert_turn(db, "s3", "2026-09-02", words=1)
        stats = ProgressService(db).stats(30, date(2026, 9, 2))

    assert stats.current_streak == 3


def test_progress_legacy_turns_count_without_inventing_rates(tmp_path):
    with Database(tmp_path / "db.sqlite") as db:
        _insert_turn(db, "legacy", "2026-09-25")
        stats = ProgressService(db).stats(7, date(2026, 9, 26))

    assert stats.completed_turns == 1
    assert stats.words_transcribed == 0
    assert stats.fillers_per_100_words is None
    assert stats.transcript_edit_rate is None


def test_interrupted_attempt_counts_as_practice_day_but_not_completed_turn(tmp_path):
    with Database(tmp_path / "db.sqlite") as db:
        db.connection.executemany(
            "INSERT INTO conversations(session_id,created_at,role,content,is_complete) "
            "VALUES(?,?,?,?,0)",
            [
                ("partial", "2026-09-26 12:00:00", "user", "Hello"),
                ("partial", "2026-09-26 12:00:00", "assistant", "Hi"),
            ],
        )
        stats = ProgressService(db).stats(7, date(2026, 9, 26))

    assert stats.practiced_days == 1
    assert stats.current_streak == 1
    assert stats.completed_turns == 0
    assert stats.words_transcribed == 0


def test_progress_period_excludes_older_activity(tmp_path):
    with Database(tmp_path / "db.sqlite") as db:
        _insert_turn(db, "recent", "2026-09-26", words=3)
        _insert_turn(db, "old", "2026-09-10", words=9)
        weekly = ProgressService(db).stats(7, date(2026, 9, 26))
        monthly = ProgressService(db).stats(30, date(2026, 9, 26))

    assert weekly.completed_turns == 1
    assert weekly.words_transcribed == 3
    assert monthly.completed_turns == 2
    assert monthly.words_transcribed == 12
