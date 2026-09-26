import pytest

from scripts.evaluate_transcription import normalize_text, summarize, word_error_rate


def test_normalize_text_ignores_case_and_punctuation():
    assert normalize_text("Hello, WORLD! It's me.") == ["hello", "world", "it's", "me"]


def test_word_error_rate_counts_insertions_deletions_and_substitutions():
    assert word_error_rate("I want to upgrade", "I want to pigrade") == pytest.approx(0.25)
    assert word_error_rate("one two", "one two now") == pytest.approx(0.5)
    assert word_error_rate("one two", "one") == pytest.approx(0.5)


def test_word_error_rate_handles_empty_reference():
    assert word_error_rate("", "") == 0.0
    assert word_error_rate("", "unexpected") == 1.0


def test_summarize_reports_medians_and_counts():
    results = [
        {"wer": 0.0, "runtime_sec": 1.0},
        {"wer": 0.5, "runtime_sec": 3.0},
        {"wer": 0.25, "runtime_sec": 2.0},
    ]

    assert summarize(results) == {
        "clips": 3,
        "median_wer": 0.25,
        "mean_wer": 0.25,
        "median_runtime_sec": 2.0,
    }


def test_summarize_handles_empty_results():
    assert summarize([]) == {
        "clips": 0,
        "median_wer": None,
        "mean_wer": None,
        "median_runtime_sec": None,
    }
