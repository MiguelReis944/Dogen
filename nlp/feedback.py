"""Parse Dogen's compact coaching suffix into explicit domain values."""

import re
from dataclasses import dataclass
from typing import Literal


FeedbackCategory = Literal[
    "grammar",
    "vocabulary",
    "word_order",
    "verb_tense",
    "agreement",
    "preposition",
    "natural_phrasing",
]

FEEDBACK_CATEGORIES = {
    "grammar",
    "vocabulary",
    "word_order",
    "verb_tense",
    "agreement",
    "preposition",
    "natural_phrasing",
}

_BLOCK_RE = re.compile(
    r"\[(Correction|Better phrasing|Category)\s*:\s*(.*?)\]",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class CoachFeedback:
    correction: str | None = None
    better_phrasing: str | None = None
    category: FeedbackCategory | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.correction or self.better_phrasing or self.category)


@dataclass(frozen=True)
class ParsedReply:
    message: str
    feedback: CoachFeedback


def parse_reply(text: str) -> ParsedReply:
    correction = None
    better_phrasing = None
    category = None

    for match in _BLOCK_RE.finditer(text):
        label = match.group(1).casefold()
        value = match.group(2).strip()
        if label == "correction":
            correction = value or None
        elif label == "better phrasing":
            better_phrasing = value or None
        else:
            normalized = re.sub(r"[\s-]+", "_", value.casefold())
            category = normalized if normalized in FEEDBACK_CATEGORIES else None

    message = _BLOCK_RE.sub("", text)
    message = re.sub(r"[ \t]+\n", "\n", message)
    message = re.sub(r"\n{3,}", "\n\n", message).strip()
    return ParsedReply(message, CoachFeedback(correction, better_phrasing, category))


def correction_pair(feedback: CoachFeedback) -> tuple[str, str] | None:
    if not feedback.correction or "→" not in feedback.correction:
        return None
    original, corrected = feedback.correction.split("→", 1)
    original = original.strip()
    corrected = corrected.strip()
    return (original, corrected) if original and corrected else None
