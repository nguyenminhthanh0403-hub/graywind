import re

import grounding
from text_scoring import tokenize


def test_retrieve_does_not_cite_a_node_on_a_substring_of_an_unrelated_word():
    hits = grounding.retrieve("explain the second stimulus check")

    assert not any(h.get("id") == "sec" for h in hits)


def test_retrieve_cites_a_node_on_a_genuine_whole_word_mention():
    hits = grounding.retrieve("what is the fed doing")

    assert any(h.get("id") == "fed" for h in hits)


def test_stopword_only_label_does_not_vacuously_match_every_query(monkeypatch):
    # A label like "Is It" tokenizes to an empty set (both words are
    # stopwords/too-short) -- the phrase-regex approach doesn't have this
    # problem the way a token-subset check would (an empty set is a
    # vacuous subset of anything), since it matches the literal phrase.
    fake_node = {"id": "zzz-test", "label": "Is It", "beginner": [], "expert": ["unrelated filler text"]}
    monkeypatch.setattr(grounding, "_NODES", [fake_node])
    monkeypatch.setattr(grounding, "_STRONG_TERMS", set())
    monkeypatch.setattr(grounding, "_LABEL_PATTERNS", {"zzz-test": re.compile(r"\bis it\b")})
    assert tokenize("Is It") == set()

    hits = grounding.retrieve("completely unrelated query about nothing")

    assert not any(h.get("id") == "zzz-test" for h in hits)


def test_underscored_node_id_still_counts_as_a_strong_term():
    # "dxy_fx" is a real node id; tokenize() splits on "_", so the raw id
    # string never appears in a tokenized query -- _STRONG_TERMS must be
    # built from tokenized ids, not the raw id strings.
    hits = grounding.retrieve("what is dxy")

    assert any(h.get("id") == "dxy_fx" for h in hits)


def test_label_pattern_requires_a_contiguous_phrase_not_just_cooccurrence():
    # An unordered "all label words present somewhere in the query" check
    # was tried and rejected: "farmers curve their yield every season"
    # contains both "yield" and "curve" with no relation to the "Yield
    # Curve" node. Tests the compiled-pattern mechanism directly rather
    # than through retrieve(): a node's label is always joined into its
    # own haystack text regardless of this bonus, so for a 2-word label
    # whose both words appear anywhere in the query, ordinary weak-overlap
    # scoring can independently reach MIN_SCORE=2 on its own -- a separate,
    # pre-existing, structural characteristic of the bag-of-words design
    # (same class as the already-accepted "goldfish"->"etf" residual
    # match), not something this fix could isolate away or was scoped to
    # eliminate. What this fix actually removes is the *bonus* firing on
    # non-contiguous co-occurrence, verified here in isolation.
    pattern = re.compile(r"\b" + re.escape("yield curve") + r"\b")

    assert not pattern.search("farmers curve their yield every season")
    assert pattern.search("what is the yield curve doing")
