"""SQLite persistence for Dogen sessions."""

import re
import sqlite3
from datetime import datetime
from pathlib import Path

from storage.models import Message, VocabItem

_CORRECTION_RE = re.compile(r'\[Correction:\s*(.+?)\s*→\s*(.+?)\]')


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
            latency_ms INTEGER
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
        """)

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
        # Extract and persist any corrections from the assistant reply
        self._save_corrections(session_id, assistant_text)

    def recent_messages(self, session_id: str, count: int) -> list[Message]:
        rows = self.connection.execute(
            "SELECT role,content,created_at,model_used,latency_ms FROM "
            "(SELECT id,role,content,created_at,model_used,latency_ms FROM conversations "
            "WHERE session_id=? ORDER BY id DESC LIMIT ?) ORDER BY id",
            (session_id, count),
        ).fetchall()
        return [Message(*row) for row in rows]

    def recent_all_messages(self, count: int) -> list[Message]:
        """Load the most recent messages across all sessions (for cross-day history display)."""
        rows = self.connection.execute(
            "SELECT role,content,created_at,model_used,latency_ms FROM "
            "(SELECT id,role,content,created_at,model_used,latency_ms FROM conversations "
            "ORDER BY id DESC LIMIT ?) ORDER BY id",
            (count,),
        ).fetchall()
        return [Message(*row) for row in rows]

    def session_stats(self, session_id: str) -> dict:
        row = self.connection.execute(
            "SELECT COUNT(*), AVG(latency_ms) FROM conversations WHERE session_id=? AND role='user'",
            (session_id,),
        ).fetchone()
        return {"turns": row[0] or 0, "avg_latency_ms": int(row[1]) if row[1] else 0}

    def latest_session_id(self) -> str | None:
        row = self.connection.execute(
            "SELECT session_id FROM conversations ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None

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

    def _save_corrections(self, session_id: str, assistant_text: str):
        pairs = _CORRECTION_RE.findall(assistant_text)
        if not pairs:
            return
        with self.connection:
            self.connection.executemany(
                "INSERT INTO vocab(session_id,original,corrected) VALUES(?,?,?)",
                [(session_id, orig.strip(), corr.strip()) for orig, corr in pairs],
            )

    def get_vocab(self, limit: int = 200) -> list[VocabItem]:
        rows = self.connection.execute(
            "SELECT original,corrected,created_at FROM vocab ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [VocabItem(*row) for row in rows]

    def clear_vocab(self):
        with self.connection:
            self.connection.execute("DELETE FROM vocab")
