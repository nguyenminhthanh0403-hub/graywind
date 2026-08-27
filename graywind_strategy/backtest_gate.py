"""Historical-backtest gate a new tier-2/3 symbol must clear before it can be
added to SYMBOL_TIER, on top of tier_config.py's market-cap/volume/sector
guardrail (docs/superpowers/specs/2026-08-26-graywind-backtest-gate-design.md).
"""
import json
import math
import os
import statistics
from datetime import datetime, timedelta, timezone
from statistics import NormalDist

import pandas as pd

from fetch_alpaca_data import fetch_bars
from graywind_strategy.backtester import run_backtest
from graywind_strategy.guardrails import GuardrailViolation

MIN_HISTORY_DAYS = 730
MIN_TOTAL_TRADES = 300
N_FOLDS = 4
FOLD_MIN_SHARPE = 1.0
FOLD_MAX_DRAWDOWN = 0.25
FOLD_MIN_WIN_RATE = 0.45
FOLD_MIN_TRADES = 30
DSR_THRESHOLD = 0.95

TRIAL_LOG_PATH = os.path.join(os.path.dirname(__file__), "backtest_gate_trials.json")

_EULER_MASCHERONI = 0.5772156649015329
_STANDARD_NORMAL = NormalDist()


def _bars_to_dataframe(bars):
    return pd.DataFrame({
        "time": [pd.Timestamp(bar.timestamp) for bar in bars],
        "open": [bar.open for bar in bars],
        "high": [bar.high for bar in bars],
        "low": [bar.low for bar in bars],
        "close": [bar.close for bar in bars],
        "volume": [bar.volume for bar in bars],
    })


def fetch_backtest_bars(data_client, symbol, lookback_years=10):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365 * lookback_years)
    bars = fetch_bars(data_client, symbol, start, end)
    if not bars:
        raise GuardrailViolation(
            f"no historical bars returned for {symbol}, cannot run backtest gate"
        )
    df = _bars_to_dataframe(bars)
    span_days = (df["time"].iloc[-1] - df["time"].iloc[0]).days
    if span_days < MIN_HISTORY_DAYS:
        raise GuardrailViolation(
            f"{symbol} has only {span_days} days of history, backtest gate requires "
            f"at least {MIN_HISTORY_DAYS}"
        )
    return df


def split_into_folds(df, n_folds=N_FOLDS):
    df = df.reset_index(drop=True)
    fold_size = len(df) // n_folds
    folds = []
    start = 0
    for i in range(n_folds):
        end = start + fold_size if i < n_folds - 1 else len(df)
        folds.append(df.iloc[start:end].reset_index(drop=True))
        start = end
    return folds
