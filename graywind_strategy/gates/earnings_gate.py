"""Earnings blackout gate: blocks new trades within a configured number of
calendar days before a scheduled earnings date. Fails closed on fetch
failure (EarningsDataUnavailable); a successful fetch that finds no
earnings in the queried window returns None, which the gate treats as
"allow", not "block" — no earnings scheduled is a legitimate, safe state.
"""
from datetime import date, timedelta

import requests

FINNHUB_CALENDAR_URL = "https://finnhub.io/api/v1/calendar/earnings"
EARNINGS_LOOKAHEAD_DAYS = 30
EARNINGS_BLACKOUT_DAYS = 3


class EarningsDataUnavailable(Exception):
    pass


def fetch_next_earnings_date(symbol, api_key, as_of_date, session=requests):
    params = {
        "symbol": symbol,
        "from": as_of_date.isoformat(),
        "to": (as_of_date + timedelta(days=EARNINGS_LOOKAHEAD_DAYS)).isoformat(),
        "token": api_key,
    }
    try:
        response = session.get(FINNHUB_CALENDAR_URL, params=params, timeout=10)
        response.raise_for_status()
        entries = response.json()["earningsCalendar"]
        dates = [date.fromisoformat(entry["date"]) for entry in entries]
        return min(dates) if dates else None
    except Exception as exc:
        raise EarningsDataUnavailable(str(exc)) from exc


def earnings_gate(next_earnings_date, as_of_date, blackout_days=EARNINGS_BLACKOUT_DAYS):
    if next_earnings_date is None:
        return True
    days_until = (next_earnings_date - as_of_date).days
    if days_until < 0:
        # fetch_next_earnings_date only queries forward from as_of_date, so this
        # branch is unreachable via the normal fetch path — kept for defensive
        # correctness since earnings_gate is a public pure function callers may
        # invoke directly with an already-passed date.
        return True
    return days_until > blackout_days
