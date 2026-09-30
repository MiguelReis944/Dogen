"""SQLite persistence for Dogen sessions."""

import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from nlp.feedback import CoachFeedback, correction_pair, parse_reply
from storage.models import Message, TurnMetrics, VocabItem


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.connection: sqlite3.Connection | None = None

    def __enter__(self):
        self.connection = sqlite3.connect(self.path)
        try:
            self.connection.execute("PRAGMA quick_check").fetchone()
            self.init_schema()
        except sqlite3.DatabaseError as exc:
            self.connection.close()
            self.connection = None
            if isinstance(exc, sqlite3.OperationalError) or not self.path.exists():
                raise
            backup = self.path.with_name(
                self.path.name + ".corrupt-" + datetime.now().strftime("%Y%m%d%H%M%S%f")
            )
            self.path.rename(backup)
            self.connection = sqlite3.connect(self.path)
            self.init_schema()
        return self

    def __exit__(self, *_):
        if self.connection:
            self.connection.close()
            self.connection = None

    def init_schema(self):
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            model_used TEXT,
            latency_ms INTEGER,
            is_complete INTEGER NOT NULL DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS conversations_session ON conversations(session_id, id);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS vocab (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            original TEXT NOT NULL,
            corrected TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS vocab_session ON vocab(session_id, id);
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            correction TEXT,
            better_phrasing TEXT,
            category TEXT
        );
        CREATE INDEX IF NOT EXISTS feedback_session ON feedback(session_id, id);
        CREATE TABLE IF NOT EXISTS turn_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            word_count INTEGER NOT NULL,
            filler_count INTEGER NOT NULL,
            transcript_edited INTEGER NOT NULL,
            correction_category TEXT
        );
        CREATE INDEX IF NOT EXISTS turn_metrics_session ON turn_metrics(session_id, id);
        CREATE TABLE IF NOT EXISTS recordings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            duration_sec REAL NOT NULL CHECK(duration_sec >= 0)
        );
        CREATE INDEX IF NOT EXISTS recordings_session ON recordings(session_id, id);
        """)

        conversation_columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(conversations)")
        }
        if "is_complete" not in conversation_columns:
            self.connection.execute(
                "ALTER TABLE conversations ADD COLUMN is_complete INTEGER NOT NULL DEFAULT 1"
            )

    # ── conversations ──────────────────────────────────────────────────────────

    def add_message(self, session_id: str, role: str, content: str, model_used: str, latency_ms: int):
        with self.connection:
            self.connection.execute(
                "INSERT INTO conversations(session_id,role,content,model_used,latency_ms) VALUES(?,?,?,?,?)",
                (session_id, role, content, model_used, latency_ms),
            )

    def add_turn(self, session_id: str, user_text: str, assistant_text: str,
                 model_used: str, latency_ms: int):
        with self.connection:
            self.connection.executemany(
                "INSERT INTO conversations(session_id,role,content,model_used,latency_ms) VALUES(?,?,?,?,?)",
                [
                    (session_id, "user", user_text, model_used, latency_ms),
                    (session_id, "assistant", assistant_text, model_used, latency_ms),
                ],
            )
            self._insert_feedback(session_id, parse_reply(assistant_text).feedback)

    def add_interrupted_turn(self, session_id: str, user_text: str, assistant_text: str,
                             model_used: str, latency_ms: int) -> None:
        """Keep a failed streamed answer visible without treating it as context or a completed turn."""
        with self.connection:
            self.connection.executemany(
                "INSERT INTO conversations(session_id,role,content,model_used,latency_ms,is_complete) "
                "VALUES(?,?,?,?,?,0)",
                [
                    (session_id, "user", user_text, model_used, latency_ms),
                    (session_id, "assistant", assistant_text, model_used, latency_ms),
                ],
            )

    def add_completed_turn(self, session_id: str, user_text: str, assistant_text: str,
                           model_used: str, latency_ms: int, feedback: CoachFeedback,
                           metrics: TurnMetrics) -> None:
        with self.connection:
            self.connection.executemany(
                "INSERT INTO conversations(session_id,role,content,model_used,latency_ms) "
                "VALUES(?,?,?,?,?)",
                [
                    (session_id, "user", user_text, model_used, latency_ms),
                    (session_id, "assistant", assistant_text, model_used, latency_ms),
                ],
            )
            self._insert_feedback(session_id, feedback)
            self.connection.execute(
                "INSERT INTO turn_metrics(session_id,word_count,filler_count,"
                "transcript_edited,correction_category) VALUES(?,?,?,?,?)",
                (
                    session_id,
                    metrics.word_count,
                    metrics.filler_count,
                    int(metrics.transcript_edited),
                    metrics.correction_category,
                ),
            )

    def recent_messages(self, session_id: str, count: int) -> list[Message]:
        rows = self.connection.execute(
            "SELECT role,content,created_at,model_used,latency_ms,is_complete FROM "
            "(SELECT id,role,content,created_at,model_used,latency_ms,is_complete FROM conversations "
            "WHERE session_id=? ORDER BY id DESC LIMIT ?) ORDER BY id",
            (session_id, count),
        ).fetchall()
        return [_message_from_row(row) for row in rows]

    def recent_context_messages(self, session_id: str, count: int) -> list[Message]:
        """Return only complete turns for restoring LLM context after restart."""
        rows = self.connection.execute(
            "SELECT role,content,created_at,model_used,latency_ms,is_complete FROM "
            "(SELECT id,role,content,created_at,model_used,latency_ms,is_complete FROM conversations "
            "WHERE session_id=? AND is_complete=1 ORDER BY id DESC LIMIT ?) ORDER BY id",
            (session_id, count),
        ).fetchall()
        return [_message_from_row(row) for row in rows]

    def session_messages(self, session_id: str):
        """Iterate every message in one session in conversation order."""
        rows = self.connection.execute(
            "SELECT role,content,created_at,model_used,latency_ms,is_complete "
            "FROM conversations WHERE session_id=? ORDER BY id",
            (session_id,),
        )
        for row in rows:
            yield _message_from_row(row)

    def recent_all_messages(self, count: int) -> list[Message]:
        """Load the most recent messages across all sessions (for cross-day history display)."""
        rows = self.connection.execute(
            "SELECT role,content,created_at,model_used,latency_ms,is_complete FROM "
            "(SELECT id,role,content,created_at,model_used,latency_ms,is_complete FROM conversations "
            "ORDER BY id DESC LIMIT ?) ORDER BY id",
            (count,),
        ).fetchall()
        return [_message_from_row(row) for row in rows]

    def session_stats(self, session_id: str) -> dict:
        row = self.connection.execute(
            "SELECT COUNT(*), AVG(latency_ms) FROM conversations "
            "WHERE session_id=? AND role='user' AND is_complete=1",
            (session_id,),
        ).fetchone()
        return {"turns": row[0] or 0, "avg_latency_ms": int(row[1]) if row[1] else 0}

    def latest_session_id(self) -> str | None:
        row = self.connection.execute(
            "SELECT session_id FROM conversations ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None

    def add_recording_duration(self, session_id: str, duration_sec: float) -> None:
        """Persist the actual captured audio duration, independent of response latency."""
        duration = float(duration_sec)
        if not (duration >= 0 and duration < float("inf")):
            raise ValueError("Recording duration must be a finite non-negative number")
        with self.connection:
            self.connection.execute(
                "INSERT INTO recordings(session_id,duration_sec) VALUES(?,?)",
                (session_id, duration),
            )

    def recording_seconds_for_session(self, session_id: str) -> float:
        row = self.connection.execute(
            "SELECT COALESCE(SUM(duration_sec),0) FROM recordings WHERE session_id=?",
            (session_id,),
        ).fetchone()
        return float(row[0] or 0)

    def correction_count_between(self, start: str, end: str) -> int:
        """Count explicit coach corrections, including legacy annotated replies once."""
        structured_rows = self.connection.execute(
            "SELECT correction FROM feedback WHERE correction IS NOT NULL "
            "AND TRIM(correction)<>'' AND created_at>=? AND created_at<?",
            (start, end),
        ).fetchall()
        persisted = Counter(row[0].strip() for row in structured_rows)
        count = sum(persisted.values())

        legacy_rows = self.connection.execute(
            "SELECT content FROM conversations WHERE role='assistant' "
            "AND created_at>=? AND created_at<?",
            (start, end),
        ).fetchall()
        for (content,) in legacy_rows:
            correction = parse_reply(content).feedback.correction
            if not correction:
                continue
            correction = correction.strip()
            if persisted[correction]:
                persisted[correction] -= 1
            else:
                count += 1
        return count

    # ── settings ───────────────────────────────────────────────────────────────

    def set_setting(self, key: str, value: str):
        with self.connection:
            self.connection.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_setting(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    # ── vocab ──────────────────────────────────────────────────────────────────

    def save_feedback(self, session_id: str, feedback: CoachFeedback) -> None:
        if feedback.is_empty:
            return
        with self.connection:
            self._insert_feedback(session_id, feedback)

    def _insert_feedback(self, session_id: str, feedback: CoachFeedback) -> None:
        if feedback.is_empty:
            return
        self.connection.execute(
            "INSERT INTO feedback(session_id,correction,better_phrasing,category) "
            "VALUES(?,?,?,?)",
            (
                session_id,
                feedback.correction,
                feedback.better_phrasing,
                feedback.category,
            ),
        )
        pair = correction_pair(feedback)
        if pair:
            self.connection.execute(
                "INSERT INTO vocab(session_id,original,corrected) VALUES(?,?,?)",
                (session_id, pair[0], pair[1]),
            )

    def feedback_for_session(self, session_id: str) -> list[CoachFeedback]:
        rows = self.connection.execute(
            "SELECT correction,better_phrasing,category FROM feedback "
            "WHERE session_id=? ORDER BY id",
            (session_id,),
        ).fetchall()
        feedback = [CoachFeedback(*row) for row in rows]
        persisted = Counter(_feedback_key(item) for item in feedback)
        legacy = self.connection.execute(
            "SELECT content FROM conversations WHERE session_id=? AND role='assistant' "
            "ORDER BY id",
            (session_id,),
        ).fetchall()
        for (content,) in legacy:
            parsed = parse_reply(content).feedback
            if parsed.is_empty:
                continue
            key = _feedback_key(parsed)
            if persisted[key]:
                persisted[key] -= 1
            else:
                feedback.append(parsed)
        return feedback

    def session_full_stats(self, session_id: str) -> dict:
        row = self.connection.execute(
            "SELECT COUNT(*) FROM conversations "
            "WHERE session_id=? AND role='user' AND is_complete=1",
            (session_id,),
        ).fetchone()
        corrections = self.connection.execute(
            "SELECT COUNT(*) FROM vocab WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        fillers = self.connection.execute(
            "SELECT COALESCE(SUM(filler_count), 0) FROM turn_metrics WHERE session_id=?",
            (session_id,),
        ).fetchone()[0]
        vocab = self.get_vocab_for_session(session_id, limit=20)

        turns   = row[0] or 0
        minutes = self.recording_seconds_for_session(session_id) / 60

        return {
            "turns": turns,
            "corrections": corrections,
            "minutes": minutes,
            "vocab": vocab,
            "fillers": fillers,
        }

    def get_vocab_for_session(self, session_id: str, limit: int = 20) -> list[VocabItem]:
        rows = self.connection.execute(
            "SELECT original,corrected,created_at FROM vocab WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [VocabItem(*row) for row in rows]

    def get_vocab(self, limit: int = 200) -> list[VocabItem]:
        rows = self.connection.execute(
            "SELECT original,corrected,created_at FROM vocab ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [VocabItem(*row) for row in rows]

    def clear_vocab(self):
        with self.connection:
            self.connection.execute("DELETE FROM vocab")


def _message_from_row(row) -> Message:
    return Message(*row[:5], bool(row[5]))


def _feedback_key(feedback: CoachFeedback) -> tuple:
    return feedback.correction, feedback.better_phrasing, feedback.category
