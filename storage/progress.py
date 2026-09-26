"""Read-only progress aggregates derived from local Dogen data."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from storage.db import Database


@dataclass(frozen=True)
class ProgressStats:
    period_days: int
    practiced_days: int
    current_streak: int
    minutes_practiced: float
    completed_turns: int
    words_spoken: int
    fillers_per_100_words: float | None
    transcript_edit_rate: float | None
    corrections_by_category: dict[str, int]
    vocabulary_count: int


class ProgressService:
    def __init__(self, database: Database):
        self.database = database

    def stats(self, period_days: int, today: date) -> ProgressStats:
        if period_days not in {7, 30}:
            raise ValueError("period_days must be 7 or 30")
        cutoff = (today - timedelta(days=period_days - 1)).isoformat()
        connection = self.database.connection

        activity = connection.execute(
            "SELECT COUNT(DISTINCT date(created_at)), COUNT(*) FROM conversations "
            "WHERE role='user' AND date(created_at) BETWEEN ? AND ?",
            (cutoff, today.isoformat()),
        ).fetchone()
        metric_totals = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(word_count),0), COALESCE(SUM(filler_count),0), "
            "COALESCE(SUM(transcript_edited),0) FROM turn_metrics "
            "WHERE date(created_at) BETWEEN ? AND ?",
            (cutoff, today.isoformat()),
        ).fetchone()
        category_rows = connection.execute(
            "SELECT correction_category, COUNT(*) FROM turn_metrics "
            "WHERE correction_category IS NOT NULL "
            "AND date(created_at) BETWEEN ? AND ? GROUP BY correction_category",
            (cutoff, today.isoformat()),
        ).fetchall()
        vocabulary_count = connection.execute(
            "SELECT COUNT(*) FROM vocab WHERE date(created_at) BETWEEN ? AND ?",
            (cutoff, today.isoformat()),
        ).fetchone()[0]

        words = int(metric_totals[1] or 0)
        metric_turns = int(metric_totals[0] or 0)
        fillers_per_100 = (float(metric_totals[2]) * 100 / words) if words else None
        edit_rate = (float(metric_totals[3]) / metric_turns) if metric_turns else None

        return ProgressStats(
            period_days=period_days,
            practiced_days=int(activity[0] or 0),
            current_streak=self._current_streak(today),
            minutes_practiced=self._practice_minutes(cutoff, today.isoformat()),
            completed_turns=int(activity[1] or 0),
            words_spoken=words,
            fillers_per_100_words=fillers_per_100,
            transcript_edit_rate=edit_rate,
            corrections_by_category={category: count for category, count in category_rows},
            vocabulary_count=int(vocabulary_count or 0),
        )

    def _current_streak(self, today: date) -> int:
        rows = self.database.connection.execute(
            "SELECT DISTINCT date(created_at) FROM conversations "
            "WHERE role='user' AND date(created_at) <= ? ORDER BY date(created_at) DESC",
            (today.isoformat(),),
        ).fetchall()
        days = [date.fromisoformat(row[0]) for row in rows]
        if not days or days[0] < today - timedelta(days=1):
            return 0
        expected = days[0]
        streak = 0
        for practiced_day in days:
            if practiced_day != expected:
                break
            streak += 1
            expected -= timedelta(days=1)
        return streak

    def _practice_minutes(self, cutoff: str, through: str) -> float:
        rows = self.database.connection.execute(
            "SELECT session_id, MIN(created_at), MAX(created_at) FROM conversations "
            "WHERE role='user' AND date(created_at) BETWEEN ? AND ? GROUP BY session_id",
            (cutoff, through),
        ).fetchall()
        seconds = 0.0
        for _, first, last in rows:
            if first and last:
                seconds += max(
                    0.0,
                    (datetime.fromisoformat(last) - datetime.fromisoformat(first)).total_seconds(),
                )
        return seconds / 60
