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


def check_fold_thresholds(result, fold_index):
    if result.sharpe < FOLD_MIN_SHARPE:
        raise GuardrailViolation(
            f"fold {fold_index}: sharpe {result.sharpe:.3f} below minimum {FOLD_MIN_SHARPE}"
        )
    if result.max_drawdown > FOLD_MAX_DRAWDOWN:
        raise GuardrailViolation(
            f"fold {fold_index}: max drawdown {result.max_drawdown:.1%} exceeds cap "
            f"{FOLD_MAX_DRAWDOWN:.0%}"
        )
    if result.win_rate < FOLD_MIN_WIN_RATE:
        raise GuardrailViolation(
            f"fold {fold_index}: win rate {result.win_rate:.1%} below minimum "
            f"{FOLD_MIN_WIN_RATE:.0%}"
        )
    if len(result.trades) < FOLD_MIN_TRADES:
        raise GuardrailViolation(
            f"fold {fold_index}: only {len(result.trades)} trades, need at least "
            f"{FOLD_MIN_TRADES}"
        )


def _period_returns(equity_curve):
    return [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        for i in range(1, len(equity_curve))
    ]


def _skewness(returns):
    n = len(returns)
    mean = statistics.mean(returns)
    stdev = statistics.pstdev(returns)
    if stdev == 0:
        return 0.0
    return sum(((r - mean) / stdev) ** 3 for r in returns) / n


def _kurtosis(returns):
    n = len(returns)
    mean = statistics.mean(returns)
    stdev = statistics.pstdev(returns)
    if stdev == 0:
        return 3.0  # neutral (normal-distribution) default for a degenerate zero-variance series
    return sum(((r - mean) / stdev) ** 4 for r in returns) / n


def expected_max_z(n_trials):
    """Expected value of the max of n_trials draws from a standard normal
    (extreme-value-theory approximation, Bailey & Lopez de Prado 2014)."""
    if n_trials < 2:
        return 0.0
    return (
        (1 - _EULER_MASCHERONI) * _STANDARD_NORMAL.inv_cdf(1 - 1.0 / n_trials)
        + _EULER_MASCHERONI * _STANDARD_NORMAL.inv_cdf(1 - 1.0 / (n_trials * math.e))
    )


def probabilistic_sharpe_ratio(sharpe, benchmark_sharpe, n_returns, skew, kurtosis):
    if n_returns < 2:
        return 0.0
    denom = math.sqrt(max(1 - skew * sharpe + ((kurtosis - 1) / 4) * sharpe ** 2, 1e-12))
    z = (sharpe - benchmark_sharpe) * math.sqrt(n_returns - 1) / denom
    return _STANDARD_NORMAL.cdf(z)


def deflated_sharpe_ratio(sharpe, n_trials, n_returns, skew, kurtosis):
    if n_returns < 2:
        return 0.0
    denom = math.sqrt(max(1 - skew * sharpe + ((kurtosis - 1) / 4) * sharpe ** 2, 1e-12))
    sr_std = denom / math.sqrt(n_returns - 1)
    sr0 = sr_std * expected_max_z(n_trials)
    return probabilistic_sharpe_ratio(sharpe, sr0, n_returns, skew, kurtosis)


def _load_trial_log(path=TRIAL_LOG_PATH):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def _trial_count(path=TRIAL_LOG_PATH):
    return len(_load_trial_log(path))


def _append_trial(symbol, tier, passed, sharpe, path=TRIAL_LOG_PATH):
    trials = _load_trial_log(path)
    trials.append({
        "symbol": symbol,
        "tier": tier,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "sharpe": sharpe,
    })
    with open(path, "w") as f:
        json.dump(trials, f, indent=2)
        f.write("\n")


def validate_symbol_backtest(symbol, tier, data_client, trial_log_path=TRIAL_LOG_PATH):
    n_trials = _trial_count(trial_log_path) + 1
    sharpe_for_log = None
    try:
        df = fetch_backtest_bars(data_client, symbol)

        full_result = run_backtest({symbol: df}, starting_equity=10000.0, gates_always_pass=True)
        if len(full_result.trades) < MIN_TOTAL_TRADES:
            raise GuardrailViolation(
                f"{symbol}: only {len(full_result.trades)} total trades, need at least "
                f"{MIN_TOTAL_TRADES}"
            )

        full_returns = _period_returns(full_result.equity_curve)
        stdev = statistics.pstdev(full_returns) if len(full_returns) >= 2 else 0.0
        raw_sharpe = (statistics.mean(full_returns) / stdev) if stdev else 0.0
        sharpe_for_log = raw_sharpe

        for i, fold_df in enumerate(split_into_folds(df)):
            fold_result = run_backtest(
                {symbol: fold_df}, starting_equity=10000.0, gates_always_pass=True
            )
            check_fold_thresholds(fold_result, i)

        skew = _skewness(full_returns)
        kurtosis = _kurtosis(full_returns)
        dsr = deflated_sharpe_ratio(raw_sharpe, n_trials, len(full_returns), skew, kurtosis)
        if dsr < DSR_THRESHOLD:
            raise GuardrailViolation(
                f"{symbol}: deflated Sharpe ratio {dsr:.3f} below {DSR_THRESHOLD} threshold "
                f"with {n_trials} trials counted"
            )
    except GuardrailViolation:
        _append_trial(symbol, tier, passed=False, sharpe=sharpe_for_log, path=trial_log_path)
        raise
    else:
        _append_trial(symbol, tier, passed=True, sharpe=sharpe_for_log, path=trial_log_path)
