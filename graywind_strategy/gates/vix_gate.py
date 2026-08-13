"""VIX circuit-breaker gate: blocks new trades when FRED's VIXCLS daily
close is at or above a configured threshold. Fails closed — any fetch or
parse failure raises VixDataUnavailable, which the caller (pipeline.py)
must treat as a blocked trade, never as a skipped gate.
"""
import requests

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
VIX_THRESHOLD = 25.0


class VixDataUnavailable(Exception):
    pass


def fetch_latest_vix(api_key, session=requests):
    params = {
        "series_id": "VIXCLS",
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 1,
    }
    try:
        response = session.get(FRED_OBSERVATIONS_URL, params=params, timeout=10)
        response.raise_for_status()
        observations = response.json()["observations"]
        raw_value = observations[0]["value"]
        if raw_value == ".":
            raise VixDataUnavailable("FRED returned no observation for the latest date")
        return float(raw_value)
    except VixDataUnavailable:
        raise
    except Exception as exc:
        raise VixDataUnavailable(str(exc)) from exc


def vix_gate(vix_value, threshold=VIX_THRESHOLD):
    return vix_value < threshold
