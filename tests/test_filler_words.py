import html

from nlp.filler_words import count_fillers, highlight_fillers_html


def test_count_fillers_detects_common_fillers():
    assert count_fillers("Um, I think, like, this is basically fine") == 3


def test_count_fillers_is_case_insensitive():
    assert count_fillers("UH, are we there yet?") == 1


def test_count_fillers_returns_zero_for_clean_text():
    assert count_fillers("I went to the store yesterday") == 0


def test_highlight_fillers_wraps_matches_in_span():
    escaped = html.escape("I mean, this is like really good")
    out = highlight_fillers_html(escaped)
    assert out.count("<span") == 2
