import pytest

from avatar import lines


def test_every_moment_has_lines():
    assert set(lines.LINES) == set(lines.MOMENTS)
    for moment in lines.MOMENTS:
        assert len(lines.LINES[moment]) >= 5, f"{moment} is too thin to avoid repeats"


def test_catalogue_has_no_duplicate_text():
    """A duplicate would collide on slug and silently share one wav."""
    texts = [text for _, text in lines.all_lines()]
    assert len(texts) == len(set(texts))


def test_slug_is_stable_and_short():
    assert lines.slug("Hang on. Pulling the numbers.") == \
        lines.slug("Hang on. Pulling the numbers.")
    assert len(lines.slug("anything")) == 12
    assert lines.slug("a") != lines.slug("b")


def test_slug_changes_when_text_changes():
    """The whole incremental-regeneration property rests on this."""
    assert lines.slug("Hold on.") != lines.slug("Hold on!")


def test_pick_returns_a_line_from_that_moment():
    for moment in lines.MOMENTS:
        for _ in range(20):
            assert lines.pick(moment) in lines.LINES[moment]


def test_pick_never_returns_the_excluded_line():
    """Prevents the same greeting twice in a row."""
    first = lines.LINES["greeting"][0]
    for _ in range(50):
        assert lines.pick("greeting", exclude=first) != first


def test_pick_returns_the_only_line_even_if_excluded(monkeypatch):
    """A single line repeating beats silence."""
    monkeypatch.setitem(lines.LINES, "greeting", ("only one",))
    assert lines.pick("greeting", exclude="only one") == "only one"


def test_pick_rejects_an_unknown_moment():
    with pytest.raises(KeyError):
        lines.pick("nonsense")


def test_all_lines_covers_the_whole_catalogue():
    pairs = lines.all_lines()
    assert len(pairs) == sum(len(v) for v in lines.LINES.values())
    assert ("idle", "Are we just idling then?") in pairs


def test_catalogue_shape_is_pinned():
    """Counts the spec fixes, asserted against literals rather than against
    the catalogue itself.

    The check above it compares all_lines() to LINES, but all_lines() is built
    from LINES -- that equality is a tautology and holds however many lines
    the catalogue has. Audio for these lines costs ~2 minutes each to generate
    offline, so a silent shrink is expensive to notice and expensive to undo.
    """
    assert {m: len(t) for m, t in lines.LINES.items()} == {
        "greeting": 7, "idle": 8, "dismissal": 5, "filler": 8,
    }
    assert len(lines.all_lines()) == 28
