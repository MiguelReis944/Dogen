"""SQLite persistence for Dogen sessions."""

import sqlite3
from pathlib import Path

from storage.models import Message


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.connection: sqlite3.Connection | None = None

    def __enter__(self):
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
        """)

    def add_message(self, session_id: str, role: str, content: str, model_used: str, latency_ms: int):
        with self.connection:
            self.connection.execute(
                "INSERT INTO conversations(session_id,role,content,model_used,latency_ms) VALUES(?,?,?,?,?)",
                (session_id, role, content, model_used, latency_ms),
            )

    def recent_messages(self, session_id: str, count: int) -> list[Message]:
        rows = self.connection.execute(
            "SELECT role,content,created_at,model_used,latency_ms FROM "
            "(SELECT id,role,content,created_at,model_used,latency_ms FROM conversations "
            "WHERE session_id=? ORDER BY id DESC LIMIT ?) ORDER BY id",
            (session_id, count),
        ).fetchall()
        return [Message(*row) for row in rows]

    def latest_session_id(self) -> str | None:
        row = self.connection.execute("SELECT session_id FROM conversations ORDER BY id DESC LIMIT 1").fetchone()
        return row[0] if row else None

    def set_setting(self, key: str, value: str):
        with self.connection:
            self.connection.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_setting(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None
