"""Bullion macro-gate: blocks new trades when a vote-count of macro stress
signals (VIX, NFCI, HY OAS, yield curve slope), sourced from Bullion's
public daily-cron data.json, meets a configured breach threshold. Fails
closed -- any fetch, parse, or staleness failure raises
MacroDataUnavailable, which the caller (pipeline.py) must treat as a
blocked trade, never as a skipped gate. Additive alongside vix_gate.py,
which keeps its own direct FRED call unchanged.
"""
from datetime import datetime

import requests

VIX_THRESHOLD = 25.0
NFCI_THRESHOLD = 0.0
HY_OAS_THRESHOLD = 5.0
CURVE_SLOPE_THRESHOLD = 0.0


class MacroDataUnavailable(Exception):
    pass


BULLION_DATA_URL = "https://nguyenminhthanh0403-hub.github.io/claudekit/bullion-live-map/data.json"
DAILY_STALENESS_CEILING_DAYS = 5
WEEKLY_STALENESS_CEILING_DAYS = 10

_FIELD_CEILINGS = {
    "vix": DAILY_STALENESS_CEILING_DAYS,
    "hy_oas": DAILY_STALENESS_CEILING_DAYS,
    "us10y": DAILY_STALENESS_CEILING_DAYS,
    "us2y": DAILY_STALENESS_CEILING_DAYS,
    "nfci": WEEKLY_STALENESS_CEILING_DAYS,
}


def macro_gate(snapshot, required_breaches=2):
    breaches = 0
    if snapshot["vix"] >= VIX_THRESHOLD:
        breaches += 1
    if snapshot["nfci"] >= NFCI_THRESHOLD:
        breaches += 1
    if snapshot["hy_oas"] >= HY_OAS_THRESHOLD:
        breaches += 1
    if snapshot["curve_slope"] < CURVE_SLOPE_THRESHOLD:
        breaches += 1
    return breaches < required_breaches


def _most_recent_value_before(history, field, as_of_date, ceiling_days):
    for date_str in sorted(history.keys(), reverse=True):
        record_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        if record_date >= as_of_date:
            continue
        record = history[date_str]
        if field not in record:
            continue
        if (as_of_date - record_date).days > ceiling_days:
            raise MacroDataUnavailable(
                f"no fresh value for '{field}': most recent is {record_date}, "
                f"older than the {ceiling_days}-day staleness ceiling"
            )
        return record[field]
    raise MacroDataUnavailable(f"no value found for '{field}' in history before {as_of_date}")


def fetch_bullion_macro_snapshot(as_of_date, session=requests):
    try:
        response = session.get(BULLION_DATA_URL, timeout=10)
        response.raise_for_status()
        history = response.json()["history"]
    except MacroDataUnavailable:
        raise
    except Exception as exc:
        raise MacroDataUnavailable(str(exc)) from exc

    values = {
        field: _most_recent_value_before(history, field, as_of_date, ceiling)
        for field, ceiling in _FIELD_CEILINGS.items()
    }

    return {
        "vix": values["vix"],
        "nfci": values["nfci"],
        "hy_oas": values["hy_oas"],
        "curve_slope": values["us10y"] - values["us2y"],
    }
