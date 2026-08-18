"""Yahoo analyst-consensus position-size multiplier: scales a trade's share
count up or down based on analyst recommendation trend and price-target
consensus. Unlike the five boolean gates in this package, this never blocks
a trade -- it fails open (multiplier of 1.0, no adjustment) on any fetch
failure, and returns 1.0 unconditionally for any non-live as_of_date, since
yfinance has no historical point-in-time query and decide_trade is the
single path both live_loop.py and backtester.py call (see pipeline.py's
evaluate_analyst_consensus_multiplier for that guard).
"""
import csv
import os

import yfinance as yf

from graywind_strategy.state_store import DEFAULT_STATE_DIR

CACHE_FILENAME = "analyst_consensus.csv"
CACHE_FIELDS = ["symbol", "date", "recommendation_mean", "target_mean", "multiplier"]

REC_MIN, REC_MAX = 1.0, 5.0
MULTIPLIER_MIN, MULTIPLIER_MAX = 0.85, 1.15
TARGET_UPSIDE_CLAMP = 0.15


class AnalystDataUnavailable(Exception):
    pass


def _clamp(value, low, high):
    return max(low, min(high, value))


def analyst_consensus_multiplier(recommendation_mean, target_mean, current_price):
    rec_clamped = _clamp(recommendation_mean, REC_MIN, REC_MAX)
    # Strong Buy (REC_MIN) maps to MULTIPLIER_MAX, Strong Sell (REC_MAX) maps to MULTIPLIER_MIN.
    rec_fraction = (rec_clamped - REC_MIN) / (REC_MAX - REC_MIN)
    multiplier_rec = MULTIPLIER_MAX - rec_fraction * (MULTIPLIER_MAX - MULTIPLIER_MIN)

    pct_upside = (target_mean - current_price) / current_price
    multiplier_target = 1.0 + _clamp(pct_upside, -TARGET_UPSIDE_CLAMP, TARGET_UPSIDE_CLAMP)

    return (multiplier_rec + multiplier_target) / 2


def fetch_analyst_consensus(symbol, ticker_factory=yf.Ticker):
    try:
        info = ticker_factory(symbol).info
        recommendation_mean = info.get("recommendationMean")
        target_mean = info.get("targetMeanPrice")
    except Exception as exc:
        raise AnalystDataUnavailable(str(exc)) from exc
    if recommendation_mean is None or target_mean is None:
        raise AnalystDataUnavailable(f"missing analyst consensus fields for {symbol}")
    return float(recommendation_mean), float(target_mean)


def load_cached_multiplier(symbol, as_of_date, state_dir=DEFAULT_STATE_DIR):
    path = os.path.join(state_dir, CACHE_FILENAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("symbol") == symbol and row.get("date") == as_of_date.isoformat():
                    try:
                        return float(row["multiplier"])
                    except Exception:
                        # Malformed row for this key; skip and keep scanning
                        continue
    except Exception:
        # File-level error (open, decode, or csv.DictReader parsing)
        return None
    return None


def save_cached_multiplier(symbol, as_of_date, recommendation_mean, target_mean, multiplier,
                            state_dir=DEFAULT_STATE_DIR):
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, CACHE_FILENAME)
    write_header = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CACHE_FIELDS, lineterminator="\n")
        if write_header:
            writer.writeheader()
        writer.writerow({
            "symbol": symbol,
            "date": as_of_date.isoformat(),
            "recommendation_mean": recommendation_mean,
            "target_mean": target_mean,
            "multiplier": multiplier,
        })
