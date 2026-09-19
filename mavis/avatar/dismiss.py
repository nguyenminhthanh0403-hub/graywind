"""Does this transcript mean 'go away'?

Dismissal is spoken-phrase-only by design -- there is no idle timeout -- so
this has to tolerate the small errors Whisper makes on short utterances, while
never firing on a question. Those two pressures point in opposite directions
and the naive approach cannot satisfy both.

**Why not whole-string fuzzy matching.** Comparing the entire transcript to
each phrase with SequenceMatcher was measured against realistic utterances and
ranks them in the wrong order:

    "that's a lot"        0.818   <- a question, must NOT dismiss
    "that's all thanks"   0.765   <- a dismissal, must dismiss

No threshold separates those, so loosening it to catch real dismissals starts
vanishing the avatar mid-question. Whole-string similarity is dominated by
length rather than by meaning: "go away johnny" scored only 0.714 against the
phrase "go away" purely because the extra name diluted the ratio.

**What this does instead.** Strip filler words, then require what remains to
match a phrase *word for word*, each word pair compared fuzzily. Length stops
being noise: "go away johnny" strips to "go away" and matches exactly, while
"that's a lot" keeps three words and cannot match a two-word phrase at all.
The per-word comparison is what absorbs Whisper's errors -- "thats" against
"that's" is 0.909 -- and it is also what rejects "that's a", where "a" against
"all" is 0.5.

A raw word cap still runs first, so "before you go away I wanted to ask..."
is a question no matter what it contains.
"""
import re
from difflib import SequenceMatcher

PHRASES = (
    "that's all",
    "that's it",
    "that's enough",
    "that'll be all",
    "go away",
    "shut up",
    "leave me alone",
    "goodbye",
    "bye",
    "stop",
    "you can go",
    "we're done",
)

# Removed before matching so a phrase still resolves when it is wrapped in
# politeness or his name. Deliberately excludes "you", which "you can go"
# needs -- "thank you" is handled as a phrase, before single words.
FILLER_PHRASES = ("thank you",)
FILLERS = frozenset({
    "johnny", "ok", "okay", "alright", "please", "hey", "now",
    "um", "uh", "yeah", "thanks", "cheers", "man", "dude",
})

# Applied to the raw transcript, before stripping, so that a long sentence
# cannot be whittled down into a dismissal by discarding enough words.
MAX_WORDS = 8


def _normalise(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z\s']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_fillers(said: str) -> list:
    for phrase in FILLER_PHRASES:
        said = said.replace(phrase, " ")
    return [word for word in said.split() if word not in FILLERS]


def _words_match(said_words, phrase_words, threshold: float) -> bool:
    if len(said_words) != len(phrase_words):
        return False
    return all(
        SequenceMatcher(None, said, phrase).ratio() >= threshold
        for said, phrase in zip(said_words, phrase_words)
    )


def is_dismissal(transcript: str, threshold: float = 0.82) -> bool:
    said = _normalise(transcript)
    if not said or len(said.split()) > MAX_WORDS:
        return False

    words = _strip_fillers(said)
    if not words:
        return False

    return any(
        _words_match(words, _normalise(phrase).split(), threshold)
        for phrase in PHRASES
    )
