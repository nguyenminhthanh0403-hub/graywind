from text_scoring import score_overlap, tokenize


def test_tokenize_keeps_unicode_letters_as_one_token():
    # Unicode-aware (c.isalnum()), not ASCII-only -- both grounding.py and
    # graywind_grounding.py rely on this shared behavior post-refactor.
    assert tokenize("café") == {"café"}


def test_tokenize_drops_stopwords_and_short_tokens():
    assert tokenize("what is the fed doing") == {"fed", "doing"}


def test_score_overlap_weights_strong_terms_double():
    overlap = {"fed", "doing"}
    strong_terms = {"fed"}

    assert score_overlap(overlap, strong_terms) == 3
