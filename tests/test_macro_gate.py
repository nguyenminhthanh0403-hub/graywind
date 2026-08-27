from datetime import date
from unittest.mock import MagicMock

import pytest
import requests

from graywind_strategy.gates.macro_gate import (
    MacroDataUnavailable,
    count_macro_breaches,
    fetch_bullion_macro_snapshot,
    macro_gate,
)


def _fake_session(payload):
    fake_response = MagicMock()
    fake_response.json.return_value = payload
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    return fake_session


def test_macro_gate_allows_when_no_fields_breach():
    snapshot = {"vix": 14.6, "nfci": -0.55, "hy_oas": 2.71, "curve_slope": 0.48}
    assert macro_gate(snapshot) is True


def test_macro_gate_ignores_vix_even_when_it_would_tip_the_old_vote():
    # vix is still present in every real snapshot (fetch_bullion_macro_snapshot always
    # includes it) but is no longer part of the vote: evaluate_vix_gate already blocks
    # outright on the identical FRED VIXCLS series/threshold earlier in decide_trade, so
    # counting it here too could only ever fire when it's wrong (Bullion's forward-filled
    # value stale-high while live FRED is actually fine). Here vix and hy_oas both breach --
    # under the old 4-field vote that was 2 of 4 (blocks); with vix excluded it's 1 of 3
    # (allows). Pins the regression, not just a case both old and new code already agreed on.
    snapshot = {"vix": 999.0, "nfci": -0.55, "hy_oas": 6.0, "curve_slope": 0.48}
    assert macro_gate(snapshot) is True


def test_macro_gate_allows_when_breaches_below_required_count():
    # Only hy_oas breaches; default required_breaches=2, so 1 breach still allows.
    snapshot = {"vix": 14.6, "nfci": -0.55, "hy_oas": 6.0, "curve_slope": 0.48}
    assert macro_gate(snapshot) is True


def test_macro_gate_blocks_when_breaches_meet_required_count():
    # nfci and hy_oas both breach -- 2 of 3, meets default required_breaches=2.
    snapshot = {"vix": 14.6, "nfci": 0.0, "hy_oas": 6.0, "curve_slope": 0.48}
    assert macro_gate(snapshot) is False


def test_macro_gate_blocks_when_all_three_fields_breach():
    snapshot = {"vix": 14.6, "nfci": 0.5, "hy_oas": 6.0, "curve_slope": -0.5}
    assert macro_gate(snapshot) is False


def test_macro_gate_curve_slope_breach_is_less_than_not_greater_than():
    # curve_slope is the one inverted-direction field: breach is < 0.0, not >= 0.0. A
    # deeply positive curve_slope must never count as a breach.
    snapshot = {"vix": 14.6, "nfci": -0.55, "hy_oas": 2.71, "curve_slope": 2.0}
    assert macro_gate(snapshot) is True


def test_macro_gate_respects_custom_required_breaches():
    # nfci and hy_oas breach (2 of 3), but required_breaches=3 means it takes all 3 to block.
    snapshot = {"vix": 14.6, "nfci": 0.5, "hy_oas": 6.0, "curve_slope": 0.48}
    assert macro_gate(snapshot, required_breaches=3) is True


def test_count_macro_breaches_counts_each_breaching_field():
    snapshot = {"vix": 999.0, "nfci": 0.1, "hy_oas": 6.0, "curve_slope": -0.1}
    assert count_macro_breaches(snapshot) == 3  # nfci, hy_oas, curve_slope all breach; vix excluded from the vote


def test_count_macro_breaches_is_zero_when_nothing_breaches():
    snapshot = {"vix": 14.6, "nfci": -0.55, "hy_oas": 2.71, "curve_slope": 0.48}
    assert count_macro_breaches(snapshot) == 0


def test_fetch_bullion_macro_snapshot_parses_most_recent_value_per_field():
    # Mirrors the real observed gap: the newest date before as_of_date (2026-08-14) is
    # missing vix/hy_oas/us10y/us2y entirely (only slower-cadence fields were fresh that
    # day) -- the walk must skip it and land on 2026-08-10 for those fields, while nfci
    # (weekly) is found on 2026-08-11.
    history = {
        "2026-08-10": {"vix": 15.0, "hy_oas": 2.5, "us10y": 4.5, "us2y": 4.0},
        "2026-08-11": {"nfci": -0.3},
        "2026-08-14": {"spx": 5000},
    }
    session = _fake_session({"history": history})

    snapshot = fetch_bullion_macro_snapshot(date(2026, 8, 15), session=session)

    assert snapshot == {"vix": 15.0, "nfci": -0.3, "hy_oas": 2.5, "curve_slope": 0.5}


def test_fetch_bullion_macro_snapshot_never_uses_a_value_dated_on_as_of_date():
    # Lookahead-bias regression: a record dated exactly on as_of_date must never be used,
    # even though it's the "most recent" entry by date, mirroring vix_gate.py's own
    # same-day exclusion.
    history = {
        "2026-08-10": {"vix": 15.0, "hy_oas": 2.5, "us10y": 4.5, "us2y": 4.0, "nfci": -0.3},
        "2026-08-15": {"vix": 999.0, "hy_oas": 999.0, "us10y": 999.0, "us2y": 999.0, "nfci": 999.0},
    }
    session = _fake_session({"history": history})

    snapshot = fetch_bullion_macro_snapshot(date(2026, 8, 15), session=session)

    assert snapshot == {"vix": 15.0, "nfci": -0.3, "hy_oas": 2.5, "curve_slope": 0.5}


def test_fetch_bullion_macro_snapshot_raises_when_field_stale_beyond_daily_ceiling():
    # Only candidate for vix is 8 days before as_of_date -- daily ceiling is 7 days.
    history = {
        "2026-08-07": {"vix": 15.0, "hy_oas": 2.5, "us10y": 4.5, "us2y": 4.0, "nfci": -0.3},
    }
    session = _fake_session({"history": history})

    with pytest.raises(MacroDataUnavailable, match="vix"):
        fetch_bullion_macro_snapshot(date(2026, 8, 15), session=session)


def test_fetch_bullion_macro_snapshot_accepts_field_within_daily_ceiling():
    # Exactly 7 days before as_of_date -- boundary is inclusive (not stale).
    history = {
        "2026-08-08": {"vix": 15.0, "hy_oas": 2.5, "us10y": 4.5, "us2y": 4.0, "nfci": -0.3},
    }
    session = _fake_session({"history": history})

    snapshot = fetch_bullion_macro_snapshot(date(2026, 8, 15), session=session)

    assert snapshot["vix"] == 15.0


def test_fetch_bullion_macro_snapshot_accepts_weekly_field_within_wider_ceiling():
    # nfci found 9 days before as_of_date -- would fail a 7-day daily ceiling but passes
    # its own 14-day weekly ceiling. Other fields found close-in so only nfci's ceiling is
    # exercised.
    history = {
        "2026-08-06": {"nfci": -0.3},
        "2026-08-10": {"vix": 15.0, "hy_oas": 2.5, "us10y": 4.5, "us2y": 4.0},
    }
    session = _fake_session({"history": history})

    snapshot = fetch_bullion_macro_snapshot(date(2026, 8, 15), session=session)

    assert snapshot["nfci"] == -0.3


def test_fetch_bullion_macro_snapshot_accepts_weekly_field_at_exact_ceiling_boundary():
    # nfci found exactly 14 days before as_of_date -- weekly ceiling boundary is inclusive
    # (not stale). Other fields found close-in so only nfci's ceiling is exercised.
    history = {
        "2026-08-01": {"nfci": -0.3},
        "2026-08-10": {"vix": 15.0, "hy_oas": 2.5, "us10y": 4.5, "us2y": 4.0},
    }
    session = _fake_session({"history": history})

    snapshot = fetch_bullion_macro_snapshot(date(2026, 8, 15), session=session)

    assert snapshot["nfci"] == -0.3


def test_fetch_bullion_macro_snapshot_raises_when_nfci_stale_beyond_weekly_ceiling():
    # Only candidate for nfci is 15 days before as_of_date -- weekly ceiling is 14 days.
    history = {
        "2026-07-31": {"nfci": -0.3},
        "2026-08-10": {"vix": 15.0, "hy_oas": 2.5, "us10y": 4.5, "us2y": 4.0},
    }
    session = _fake_session({"history": history})

    with pytest.raises(MacroDataUnavailable, match="nfci"):
        fetch_bullion_macro_snapshot(date(2026, 8, 15), session=session)


def test_fetch_bullion_macro_snapshot_computes_curve_slope_as_us10y_minus_us2y():
    history = {
        "2026-08-10": {"vix": 15.0, "hy_oas": 2.5, "us10y": 4.63, "us2y": 4.15, "nfci": -0.3},
    }
    session = _fake_session({"history": history})

    snapshot = fetch_bullion_macro_snapshot(date(2026, 8, 15), session=session)

    assert snapshot["curve_slope"] == pytest.approx(0.48)


def test_fetch_bullion_macro_snapshot_raises_on_http_error():
    fake_session = MagicMock()
    fake_session.get.side_effect = Exception("network error")
    with pytest.raises(MacroDataUnavailable):
        fetch_bullion_macro_snapshot(date(2026, 8, 15), session=fake_session)


def test_fetch_bullion_macro_snapshot_raises_on_http_error_status():
    fake_response = MagicMock()
    fake_response.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    with pytest.raises(MacroDataUnavailable):
        fetch_bullion_macro_snapshot(date(2026, 8, 15), session=fake_session)


def test_fetch_bullion_macro_snapshot_raises_on_missing_history_key():
    session = _fake_session({"fields": {}})
    with pytest.raises(MacroDataUnavailable):
        fetch_bullion_macro_snapshot(date(2026, 8, 15), session=session)


def test_fetch_bullion_macro_snapshot_raises_when_no_value_found_for_field_at_all():
    # history exists but never contains hy_oas at all -- walk exhausts with nothing found.
    history = {
        "2026-08-10": {"vix": 15.0, "us10y": 4.5, "us2y": 4.0, "nfci": -0.3},
    }
    session = _fake_session({"history": history})
    with pytest.raises(MacroDataUnavailable, match="hy_oas"):
        fetch_bullion_macro_snapshot(date(2026, 8, 15), session=session)


def test_fetch_bullion_macro_snapshot_raises_when_history_is_malformed_list():
    # history is a list instead of a dict (malformed payload) -- must be wrapped as
    # MacroDataUnavailable, not surfaced as a raw AttributeError from .keys() on a list.
    session = _fake_session({"history": ["not", "a", "dict"]})
    with pytest.raises(MacroDataUnavailable):
        fetch_bullion_macro_snapshot(date(2026, 8, 15), session=session)


def test_fetch_bullion_macro_snapshot_raises_when_field_value_is_null():
    # us10y is present as a key but its value is None (malformed payload). Pre-fix, this
    # value flows unchecked straight into the curve_slope subtraction (None - float),
    # raising a raw TypeError outside the try block. Post-fix, the float() coercion inside
    # the try block turns it into MacroDataUnavailable instead.
    history = {
        "2026-08-10": {"vix": 15.0, "hy_oas": 2.5, "us10y": None, "us2y": 4.0, "nfci": -0.3},
    }
    session = _fake_session({"history": history})
    with pytest.raises(MacroDataUnavailable):
        fetch_bullion_macro_snapshot(date(2026, 8, 15), session=session)
