from dataclasses import dataclass


@dataclass(frozen=True)
class Message:
    role: str
    content: str
    created_at: str
    model_used: str | None = None
    latency_ms: int | None = None


@dataclass(frozen=True)
class VocabItem:
    original: str
    corrected: str
    created_at: str


@dataclass(frozen=True)
class TurnMetrics:
    word_count: int
    filler_count: int
    transcript_edited: bool
    correction_category: str | None
