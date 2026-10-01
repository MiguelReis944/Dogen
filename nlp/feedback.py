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

_COACHING_LABELS = (
    "Correction", "Better phrasing", "Category", "Grammar", "Agreement", "Note",
    "Explanation", "Vocabulary", "Word order", "Verb tense", "Preposition",
    "Natural phrasing", "Fluency tip",
)
_ANNOTATION_START_RE = re.compile(
    r"\[(?:[a-z][a-z _/-]{0,60}\s*:|"
    rf"(?:{'|'.join(map(re.escape, _COACHING_LABELS))})\b)",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"\w+(?:'\w+)*", re.UNICODE)
_CONTRACTIONS = {"can't": "can not", "won't": "will not", "shan't": "shall not"}
_OPTIONAL_WORDS = {"really", "just", "actually", "basically", "simply", "please"}


def strip_coaching_markup(text: str) -> str:
    """Remove labelled coaching blocks, including unfinished/nested annotations."""
    parts = []
    cursor = 0
    for match in _ANNOTATION_START_RE.finditer(text):
        if match.start() < cursor:
            continue
        parts.append(text[cursor:match.start()])
        depth = 1
        cursor = match.end()
        while cursor < len(text) and depth:
            depth += (text[cursor] == "[") - (text[cursor] == "]")
            cursor += 1
    parts.append(text[cursor:])
    message = "".join(parts)
    partial = re.search(r"\[([a-z ]*)$", message, re.IGNORECASE)
    if partial and any(
        label.casefold().startswith(partial.group(1).strip().casefold())
        for label in _COACHING_LABELS
    ):
        message = message[:partial.start()]
    message = re.sub(r"[ \t]+\n", "\n", message)
    message = re.sub(r"\n{3,}", "\n\n", message)
    return message.strip()


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text.replace("’", "'").casefold())


def _phrase_signature(text: str) -> list[str]:
    """Recognize a few presentation-only edits; this is not a grammar checker."""
    text = text.replace("’", "'").casefold()
    for contracted, expanded in _CONTRACTIONS.items():
        text = re.sub(rf"\b{re.escape(contracted)}\b", expanded, text)
    text = re.sub(r"\bcannot\b", "can not", text)
    text = re.sub(r"\b(\w+)n't\b", r"\1 not", text)
    for suffix, expanded in {"m": "am", "re": "are", "ve": "have", "ll": "will"}.items():
        text = re.sub(rf"\b(\w+)'{suffix}\b", rf"\1 {expanded}", text)
    # Limit 's to pronouns/question words: a noun's 's may be possessive.
    text = re.sub(r"\b(it|he|she|that|there|what|who|where|how)'s\b", r"\1 is", text)
    text = re.sub(r"\betc\.?\b", "and so on", text)
    return _words(text)


def _style_only(original: str, corrected: str) -> bool:
    before, after = _phrase_signature(original), _phrase_signature(corrected)
    if before == after:
        return True
    # Appending a vocative or follow-up clause does not fix the quoted English.
    if any(
        _phrase_signature(corrected[:separator.start()]) == before
        for separator in re.finditer(r"[,;]|\b(?:and|but|because|so)\b", corrected, re.IGNORECASE)
    ):
        return True
    # Optional discourse words and complementizer 'that' are not English errors.
    def without_optional(words: list[str]) -> list[str]:
        return [
            word for index, word in enumerate(words)
            if word not in _OPTIONAL_WORDS
            and not (
                word == "that" and 0 < index < len(words) - 1
                and words[index - 1] in {"think", "know", "believe", "hope", "said"}
                and words[index + 1] in {"i", "you", "he", "she", "we", "they", "it"}
            )
        ]

    return without_optional(before) == without_optional(after)


def _source_contains(user_text: str, phrase: str) -> bool:
    source, quoted = _words(user_text), _words(phrase)
    return bool(quoted) and any(
        source[index:index + len(quoted)] == quoted
        for index in range(len(source) - len(quoted) + 1)
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


def parse_reply(text: str, *, user_text: str | None = None) -> ParsedReply:
    """Keep real correction pairs separate from dialogue; optionally ground the quote.

    The small equivalence filter rejects known style-only edits. Whether a different
    phrase is a genuine English error remains the local model's responsibility.
    """
    correction = None
    category = None

    for match in _BLOCK_RE.finditer(text):
        label = match.group(1).casefold()
        value = match.group(2).strip()
        if label == "correction":
            value = strip_coaching_markup(value)
            pair = correction_pair(CoachFeedback(correction=value))
            inline_category = None
            if pair:
                original, corrected = pair
                suffix = re.search(r"\s+\(([^()]+)\)\s*$", corrected)
                if suffix:
                    normalized = re.sub(r"[\s-]+", "_", suffix.group(1).casefold())
                    if normalized in FEEDBACK_CATEGORIES:
                        inline_category = normalized
                        corrected = corrected[:suffix.start()].rstrip()
                        pair = (original, corrected)
                        value = f"{original} → {corrected}"
            if pair and not _style_only(*pair):
                if user_text is None or _source_contains(user_text, pair[0]):
                    correction = value
                    category = inline_category or category
        elif label == "category":
            normalized = re.sub(r"[\s-]+", "_", value.casefold())
            category = normalized if normalized in FEEDBACK_CATEGORIES else None

    message = strip_coaching_markup(text)
    return ParsedReply(message, CoachFeedback(correction=correction, category=category if correction else None))


def correction_pair(feedback: CoachFeedback) -> tuple[str, str] | None:
    if not feedback.correction or feedback.correction.count("→") != 1:
        return None
    original, corrected = feedback.correction.split("→", 1)
    original = original.strip()
    corrected = corrected.strip()
    return (original, corrected) if original and corrected else None
