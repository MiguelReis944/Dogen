from dataclasses import dataclass


@dataclass(frozen=True)
class Message:
    role: str
    content: str
    created_at: str
    model_used: str | None = None
    latency_ms: int | None = None
