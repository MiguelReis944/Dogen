"""Filler-word detection for spoken transcripts."""

import re

# Ordered longest-first so multi-word fillers match before their components.
_FILLERS = [
    "you know", "i mean", "sort of", "kind of",
    "um", "uh", "uhh", "umm", "er", "err",
    "like", "basically", "literally", "actually",
]

_PAT = re.compile(
    r'\b(' + '|'.join(re.escape(f) for f in _FILLERS) + r')\b',
    re.IGNORECASE,
)


def count_fillers(text: str) -> int:
    return len(_PAT.findall(text))


def highlight_fillers_html(escaped_text: str) -> str:
    """Wrap filler words in a coloured span. Input must already be HTML-escaped."""
    def _wrap(m):
        return f'<span style="color:#f59e0b;font-style:italic">{m.group(0)}</span>'
    return _PAT.sub(_wrap, escaped_text)
