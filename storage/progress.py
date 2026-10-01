"""Read-only progress aggregates derived from local Dogen data."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from storage.db import Database


@dataclass(frozen=True)
class ProgressStats:
    period_days: int
    practiced_days: int
    current_streak: int
    minutes_practiced: float
    completed_turns: int
    words_transcribed: int
    fillers_per_100_words: float | None
    transcript_edit_rate: float | None
    corrections_by_category: dict[str, int]
    vocabulary_count: int
    correction_count: int = 0


class ProgressService:
    def __init__(self, database: Database):
        self.database = database

    def stats(self, period_days: int, today: date) -> ProgressStats:
        if period_days not in {1, 7, 30}:
            raise ValueError("period_days must be 1, 7, or 30")
        cutoff_day = today - timedelta(days=period_days - 1)
        cutoff = cutoff_day.isoformat()
        start, end = _utc_bounds(cutoff_day, today + timedelta(days=1))
        connection = self.database.connection

        activity = connection.execute(
            "SELECT created_at FROM conversations "
            "WHERE role='user' AND created_at>=? AND created_at<?",
            (start, end),
        ).fetchall()
        completed_turns = connection.execute(
            "SELECT COUNT(*) FROM conversations "
            "WHERE role='user' AND is_complete=1 AND created_at>=? AND created_at<?",
            (start, end),
        ).fetchone()[0]
        practiced_days = len({_local_date(row[0]) for row in activity if row[0]})
        metric_totals = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(word_count),0), COALESCE(SUM(filler_count),0), "
            "COALESCE(SUM(transcript_edited),0) FROM turn_metrics "
            "WHERE created_at>=? AND created_at<?",
            (start, end),
        ).fetchone()
        category_rows = connection.execute(
            "SELECT correction_category, COUNT(*) FROM turn_metrics "
            "WHERE correction_category IS NOT NULL "
            "AND created_at>=? AND created_at<? GROUP BY correction_category",
            (start, end),
        ).fetchall()
        vocabulary_count = connection.execute(
            "SELECT COUNT(*) FROM vocab WHERE created_at>=? AND created_at<?",
            (start, end),
        ).fetchone()[0]

        words = int(metric_totals[1] or 0)
        metric_turns = int(metric_totals[0] or 0)
        fillers_per_100 = (float(metric_totals[2]) * 100 / words) if words else None
        edit_rate = (float(metric_totals[3]) / metric_turns) if metric_turns else None

        return ProgressStats(
            period_days=period_days,
            practiced_days=practiced_days,
            current_streak=self._current_streak(today),
            minutes_practiced=self._practice_minutes(cutoff, today.isoformat()),
            completed_turns=int(completed_turns or 0),
            words_transcribed=words,
            fillers_per_100_words=fillers_per_100,
            transcript_edit_rate=edit_rate,
            corrections_by_category={category: count for category, count in category_rows},
            vocabulary_count=int(vocabulary_count or 0),
            correction_count=self.database.correction_count_between(start, end),
        )

    def _current_streak(self, today: date) -> int:
        rows = self.database.connection.execute(
            "SELECT DISTINCT created_at FROM conversations "
            "WHERE role='user'",
        ).fetchall()
        days = sorted({_local_date(row[0]) for row in rows if row[0]}, reverse=True)
        days = [day for day in days if day <= today]
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
        start, end = _utc_bounds(
            date.fromisoformat(cutoff),
            date.fromisoformat(through) + timedelta(days=1),
        )
        seconds = self.database.connection.execute(
            "SELECT COALESCE(SUM(duration_sec),0) FROM recordings "
            "WHERE created_at>=? AND created_at<?",
            (start, end),
        ).fetchone()[0]
        return float(seconds or 0) / 60


def _utc_bounds(first_day: date, end_day: date) -> tuple[str, str]:
    start = datetime.combine(first_day, time.min).astimezone(timezone.utc)
    end = datetime.combine(end_day, time.min).astimezone(timezone.utc)
    return tuple(
        value.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
        for value in (start, end)
    )


def _local_date(created_at: str) -> date:
    value = datetime.fromisoformat(created_at)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().date()
