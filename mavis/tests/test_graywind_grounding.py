import graywind_grounding


def test_retrieve_matches_watchlist_query():
    hits = graywind_grounding.retrieve("what is graywind's watchlist")

    assert any(h["id"] == "watchlist" for h in hits)


def test_retrieve_returns_empty_for_unrelated_query():
    hits = graywind_grounding.retrieve("!!! ??? ...")

    assert hits == []


def test_retrieve_does_not_match_on_a_single_ordinary_word():
    hits = graywind_grounding.retrieve("approval")

    assert hits == []


def test_retrieve_does_not_flood_on_the_universal_namespace_tag():
    hits = graywind_grounding.retrieve("how is graywind doing lately")

    assert hits == []


def test_a_symbol_tag_stays_strong_even_when_it_is_on_every_fact(monkeypatch):
    # A single-symbol watchlist is a normal, plausible operational state --
    # unlike "graywind" (always on every fact by construction), a symbol
    # tag being on every fact here is just a data coincidence and must not
    # get demoted to a weak term.
    fake_facts = [
        {"id": "watchlist", "tags": ["watchlist", "graywind", "aapl"], "text": "Graywind's active trading watchlist is AAPL."},
        {"id": "pending-100k-13", "tags": ["pending", "graywind", "100k", "aapl"], "text": "Pending trade proposal for AAPL, tier 2, awaiting manual approval."},
    ]
    monkeypatch.setattr(graywind_grounding, "_FACTS", fake_facts)
    monkeypatch.setattr(
        graywind_grounding, "_STRONG_TERMS",
        {tag for fact in fake_facts for tag in fact["tags"]} - {"graywind"},
    )

    hits = graywind_grounding.retrieve("AAPL pending trade")

    assert any(h["id"] == "pending-100k-13" for h in hits)


def test_format_context_returns_none_for_no_hits():
    assert graywind_grounding.format_context([]) is None


def test_format_context_includes_hit_text():
    hits = [{"type": "graywind_fact", "id": "watchlist", "text": "Graywind's active trading watchlist is AAPL, SERV."}]

    context = graywind_grounding.format_context(hits)

    assert "AAPL, SERV" in context
