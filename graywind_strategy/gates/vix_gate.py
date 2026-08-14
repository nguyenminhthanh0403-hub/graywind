"""VIX circuit-breaker gate: blocks new trades when FRED's VIXCLS daily
close is at or above a configured threshold. Fails closed — any fetch or
parse failure raises VixDataUnavailable, which the caller (pipeline.py)
must treat as a blocked trade, never as a skipped gate.
"""
from datetime import date, datetime, timedelta

import requests

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
VIX_THRESHOLD = 25.0
MAX_STALENESS_DAYS = 5


class VixDataUnavailable(Exception):
    pass


def fetch_latest_vix(api_key, session=requests, today=None):
    today = today if today is not None else date.today()
    # observation_end is the day BEFORE `today`, not `today` itself: FRED's
    # VIXCLS observation for a given date is that day's 4:15pm close, which
    # a bar earlier that same day (live intraday, or a backtest bar at
    # 9:30am) cannot legitimately see yet. Querying `today.isoformat()`
    # leaks same-day, not-yet-published data into backtests -- real
    # lookahead bias -- and contradicts the plan's own Global Constraint of
    # gating on *yesterday's* FRED VIXCLS close. For a live call this
    # shifts nothing observable (FRED never has today's close published
    # before market close anyway), so this only changes backtest behavior,
    # which is exactly where the bug was.
    observation_end_date = today - timedelta(days=1)
    params = {
        "series_id": "VIXCLS",
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 1,
        "observation_end": observation_end_date.isoformat(),
    }
    try:
        response = session.get(FRED_OBSERVATIONS_URL, params=params, timeout=10)
        response.raise_for_status()
        observations = response.json()["observations"]
        observation = observations[0]
        raw_value = observation["value"]
        if raw_value == ".":
            raise VixDataUnavailable("FRED returned no observation for the latest date")
        observation_date = datetime.strptime(observation["date"], "%Y-%m-%d").date()
        if (today - observation_date).days > MAX_STALENESS_DAYS:
            raise VixDataUnavailable(
                f"FRED's latest VIX observation ({observation_date}) is more than "
                f"{MAX_STALENESS_DAYS} days old"
            )
        return float(raw_value)
    except VixDataUnavailable:
        raise
    except Exception as exc:
        raise VixDataUnavailable(str(exc)) from exc


def vix_gate(vix_value, threshold=VIX_THRESHOLD):
    return vix_value < threshold
