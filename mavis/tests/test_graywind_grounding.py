import graywind_grounding


def test_retrieve_matches_watchlist_query():
    hits = graywind_grounding.retrieve("what is graywind's watchlist")

    assert any(h["id"] == "watchlist" for h in hits)


def test_retrieve_returns_empty_for_unrelated_query():
    hits = graywind_grounding.retrieve("!!! ??? ...")

    assert hits == []


def test_format_context_returns_none_for_no_hits():
    assert graywind_grounding.format_context([]) is None


def test_format_context_includes_hit_text():
    hits = [{"type": "graywind_fact", "id": "watchlist", "text": "Graywind's active trading watchlist is AAPL, SERV."}]

    context = graywind_grounding.format_context(hits)

    assert "AAPL, SERV" in context
