import pytest

from avatar import dismiss


@pytest.mark.parametrize("said", [
    "that's all",
    "That's all!",
    "  that's all, Johnny  ",
    "go away",
    "shut up Johnny",
])
def test_recognises_dismissal_phrases(said):
    assert dismiss.is_dismissal(said) is True


@pytest.mark.parametrize("said", [
    "what's the market doing today",
    "tell me about the tier pools",
    "",
    "that's a lot of money",
])
def test_ordinary_questions_are_not_dismissals(said):
    assert dismiss.is_dismissal(said) is False


def test_tolerates_small_transcription_errors():
    """Whisper mishears short phrases; an exact match would make dismissal
    unreliable, and the user chose spoken-only dismissal with no timeout
    fallback."""
    assert dismiss.is_dismissal("thats all johnny") is True


def test_does_not_fire_on_a_phrase_buried_in_a_long_sentence():
    said = "before you go away I wanted to ask about the backtest results"
    assert dismiss.is_dismissal(said) is False


@pytest.mark.parametrize("said", [
    "that's all thanks",
    "okay that's all",
    "that's all thank you",
    "go away johnny",
    "stop johnny",
    "bye johnny",
    "alright that's enough",
    "that's it",
    "that'll be all",
    "you can go",
])
def test_recognises_dismissals_wrapped_in_politeness(said):
    """Whole-string similarity failed every one of these: the extra name or
    thanks diluted the ratio below threshold, so "go away johnny" scored 0.714
    against the phrase "go away" it literally contains."""
    assert dismiss.is_dismissal(said) is True


@pytest.mark.parametrize("said", [
    "what's my stop loss",
    "should I stop the bot",
    "stop loss on tier two",
])
def test_stop_loss_questions_are_not_dismissals(said):
    """'stop' is a dismissal phrase AND half of 'stop loss'. This is a trading
    assistant, so a bare keyword match here would make the avatar vanish
    whenever risk limits came up -- which is exactly when it is wanted."""
    assert dismiss.is_dismissal(said) is False


def test_a_near_miss_question_still_loses_to_a_real_dismissal():
    """The measurement that forced the rewrite. Under whole-string matching
    "that's a lot" scored 0.818 while "that's all thanks" scored 0.765 -- a
    question ranked ABOVE a dismissal, so no threshold could separate them."""
    assert dismiss.is_dismissal("that's a lot") is False
    assert dismiss.is_dismissal("that's all thanks") is True


def test_long_sentences_cannot_be_whittled_into_a_dismissal():
    """Filler stripping runs after the length cap on purpose; otherwise a long
    question padded with names and politeness could shrink into a phrase."""
    assert dismiss.is_dismissal(
        "okay johnny thanks but before you go away tell me about tier one"
    ) is False
