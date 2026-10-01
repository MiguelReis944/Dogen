"""Regressions for fixes-only feedback and clean conversational context."""

import pytest

from nlp.feedback import CoachFeedback, parse_reply, strip_coaching_markup
from nlp.llm import ConversationContext, OllamaClient


@pytest.mark.parametrize(
    "annotation",
    [
        "[Grammar: Use the past tense.]",
        "[Agreement: The subject is singular.]",
        "[Note: A contraction sounds casual.]",
        "[Fluency tip: Try a more natural sentence.]",
        "[Explanation: This is a grammar rule.]",
        "[Note: A response interrupted before its annotation closes",
        "[Correction: I go → I went",
        "[Correction missing colon]",
        "[Corre",
        "[Agr",
    ],
)
def test_coaching_annotations_never_appear_in_conversation(annotation):
    parsed = parse_reply(f"What happened next? {annotation}")

    assert parsed.message == "What happened next?"
    assert parsed.feedback == CoachFeedback()


@pytest.mark.parametrize(
    "correction",
    [
        "What's your name → What is your name?",
        "I'm ready → I am ready.",
        "I don't know → I do not know",
        "We need books, pencils, etc. → We need books, pencils, and so on.",
        "I like it → I like it!",
        "I really like that movie → I like that movie",
        "I think that you should try it → I think you should try it",
        "What's your name? → What's your name, please?",
        "What's your name? → What's your name, friend?",
        "What's your name? → What's your name, and where are you from?",
        "What's your name? → What's your name and where are you from?",
    ],
)
def test_style_only_corrections_are_discarded(correction):
    parsed = parse_reply(f"Let's keep talking. [Correction: {correction}][Category: grammar]")

    assert parsed.message == "Let's keep talking."
    assert parsed.feedback == CoachFeedback()


def test_category_without_real_correction_is_not_feedback():
    parsed = parse_reply("Nice! [Category: grammar][Correction: None]")

    assert parsed.message == "Nice!"
    assert parsed.feedback == CoachFeedback()


def test_square_brackets_without_coaching_label_remain_conversational():
    parsed = parse_reply("Use [one, two, three] as an example.")

    assert parsed.message == "Use [one, two, three] as an example."


def test_assistant_history_is_cleaned_before_it_can_teach_model_annotations():
    context = ConversationContext()
    context.add_message("user", "Can you explain [Grammar: agreement]?")
    context.add_message("assistant", "Sure. [Grammar: use a singular verb][Note: Remember this.]")

    assert context.get_messages_for_ollama()[1:] == [
        {"role": "user", "content": "Can you explain [Grammar: agreement]?"},
        {"role": "assistant", "content": "Sure."},
    ]


@pytest.mark.parametrize(
    "user_text",
    ["I went to the store yesterday.", "I go to school.", "", "She said I go to store sometimes."],
)
def test_correction_cannot_quote_words_absent_from_actual_transcript(user_text):
    parsed = parse_reply(
        "What did you buy? [Correction: I go to store yesterday → I went to the store yesterday]"
        "[Category: verb_tense]",
        user_text=user_text,
    )

    assert parsed.message == "What did you buy?"
    assert parsed.feedback == CoachFeedback()


@pytest.mark.parametrize(
    ("source", "correction", "category"),
    [
        ("I go to store yesterday.", "I go to store yesterday → I went to the store yesterday", "verb_tense"),
        ("Well, SHE DON'T like it.", "she don't like it → she doesn't like it", "agreement"),
        ("What's you name?", "What’s you name → What’s your name?", "grammar"),
        ("I am agree with you.", "I am agree → I agree", "grammar"),
        ("I borrowed him my book.", "borrowed him my book → lent him my book", "natural_phrasing"),
        ("I go to store yesterday, and she came too.", "I go to store yesterday, and she came too → I went to the store yesterday, and she came too", "verb_tense"),
    ],
)
def test_meaningful_corrections_survive_grounding_and_style_filters(source, correction, category):
    parsed = parse_reply(
        f"Tell me more. [Correction: {correction}][Category: {category}]",
        user_text=source,
    )

    assert parsed.feedback == CoachFeedback(correction=correction, category=category)


def test_nested_annotation_does_not_leave_its_explanation_in_dialogue():
    assert strip_coaching_markup("Tell me more. [Note: Use [the verb] here] Good idea.") == (
        "Tell me more.  Good idea."
    )


def test_known_category_inside_correction_is_metadata_not_a_fix_explanation():
    parsed = parse_reply(
        "Let's chat. [Correction: What you can do? → What can you do? (word_order)]",
        user_text="What you can do?",
    )

    assert parsed.feedback == CoachFeedback(
        correction="What you can do? → What can you do?", category="word_order"
    )


def test_nested_coaching_note_cannot_leak_into_the_fix_text():
    parsed = parse_reply(
        "Tell me more. [Correction: I go yesterday → I went yesterday [Grammar: past tense]]",
        user_text="I go yesterday",
    )

    assert parsed.message == "Tell me more."
    assert parsed.feedback == CoachFeedback(correction="I go yesterday → I went yesterday")


def test_malformed_correction_with_multiple_arrows_is_not_feedback():
    parsed = parse_reply("Tell me more. [Correction: I go → I went → I had gone]")

    assert parsed.feedback == CoachFeedback()


def test_coach_requests_stable_sampling_in_its_single_model_call(monkeypatch):
    requests = []

    class LocalRequestBoundary:
        def __init__(self, host, timeout):
            pass

        def chat(self, **request):
            requests.append(request)
            return iter([{"message": {"content": "What did you buy?"}}])

    monkeypatch.setattr("ollama.Client", LocalRequestBoundary)
    chunks = []
    reply = OllamaClient("http://localhost:11434", "mistral").generate(
        [{"role": "user", "content": "I go to store yesterday."}], chunks.append, lambda: False
    )

    assert reply == "What did you buy?"
    assert chunks == ["What did you buy?"]
    assert len(requests) == 1
    assert requests[0]["options"].get("temperature") == 0
