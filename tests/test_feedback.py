import pytest

from nlp.feedback import CoachFeedback, parse_reply


def test_parse_reply_without_feedback():
    parsed = parse_reply("That sounds like a fun project!")

    assert parsed.message == "That sounds like a fun project!"
    assert parsed.feedback == CoachFeedback()


def test_parse_reply_extracts_correction_and_keeps_category_internal():
    parsed = parse_reply(
        "What did you buy?\n"
        "[Correction: I go yesterday → I went yesterday]\n"
        "[Better phrasing: I stopped by yesterday.]\n"
        "[Category: verb_tense]"
    )

    assert parsed.message == "What did you buy?"
    assert parsed.feedback == CoachFeedback(
        correction="I go yesterday → I went yesterday",
        category="verb_tense",
    )


@pytest.mark.parametrize(
    ("suffix", "field", "value"),
    [
        ("[Correction: a → b]", "correction", "a → b"),
        ("[Better phrasing: Try this instead.]", "better_phrasing", None),
    ],
)
def test_parse_reply_accepts_individual_feedback_blocks(suffix, field, value):
    parsed = parse_reply(f"Reply.\n{suffix}")

    assert getattr(parsed.feedback, field) == value


def test_parse_reply_ignores_unknown_category_without_crashing():
    parsed = parse_reply("Reply.\n[Correction: a → b]\n[Category: impossible_score]")

    assert parsed.message == "Reply."
    assert parsed.feedback.category is None


def test_parse_reply_hides_malformed_coaching_block():
    parsed = parse_reply("Reply. [Correction missing colon]")

    assert parsed.message == "Reply."
    assert parsed.feedback == CoachFeedback()


def test_parse_reply_discards_multiline_better_phrasing():
    parsed = parse_reply("Reply.\n[Better phrasing: This is a more\nnatural sentence.]")

    assert parsed.message == "Reply."
    assert parsed.feedback.better_phrasing is None
