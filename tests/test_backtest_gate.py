import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from graywind_strategy.backtest_gate import (
    MIN_HISTORY_DAYS, _append_trial, _kurtosis, _load_trial_log, _period_returns, _skewness,
    _trial_count, check_fold_thresholds, deflated_sharpe_ratio, expected_max_z,
    fetch_backtest_bars, probabilistic_sharpe_ratio, split_into_folds, validate_symbol_backtest,
)
from graywind_strategy.backtester import BacktestResult
from graywind_strategy.guardrails import GuardrailViolation


def _fake_bar(ts, price=100.0, volume=1000):
    bar = MagicMock()
    bar.timestamp = ts
    bar.open = price
    bar.high = price + 1
    bar.low = price - 1
    bar.close = price
    bar.volume = volume
    return bar


def test_fetch_backtest_bars_raises_when_no_bars_returned():
    fake_data_client = MagicMock()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "graywind_strategy.backtest_gate.fetch_bars",
            lambda client, symbol, start, end: [],
        )
        with pytest.raises(GuardrailViolation, match="no historical bars"):
            fetch_backtest_bars(fake_data_client, "SERV")


def test_fetch_backtest_bars_raises_when_span_below_minimum_history():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = [_fake_bar(start + timedelta(days=d)) for d in range(0, 100, 10)]  # ~90 days span
    fake_data_client = MagicMock()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "graywind_strategy.backtest_gate.fetch_bars",
            lambda client, symbol, start, end: bars,
        )
        with pytest.raises(GuardrailViolation, match=f"at least {MIN_HISTORY_DAYS}"):
            fetch_backtest_bars(fake_data_client, "SERV")


def test_fetch_backtest_bars_returns_dataframe_when_span_clears_minimum():
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    bars = [_fake_bar(start + timedelta(days=d), price=100.0 + d) for d in range(0, 900, 5)]
    fake_data_client = MagicMock()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "graywind_strategy.backtest_gate.fetch_bars",
            lambda client, symbol, start, end: bars,
        )
        df = fetch_backtest_bars(fake_data_client, "SERV")

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["time", "open", "high", "low", "close", "volume"]
    assert len(df) == len(bars)
    assert df["close"].iloc[-1] == bars[-1].close


def test_split_into_folds_divides_evenly_when_divisible():
    df = pd.DataFrame({"time": pd.date_range("2020-01-01", periods=100, freq="15min")})
    folds = split_into_folds(df, n_folds=4)
    assert [len(f) for f in folds] == [25, 25, 25, 25]


def test_split_into_folds_gives_remainder_to_last_fold():
    df = pd.DataFrame({"time": pd.date_range("2020-01-01", periods=101, freq="15min")})
    folds = split_into_folds(df, n_folds=4)
    assert [len(f) for f in folds] == [25, 25, 25, 26]


def test_split_into_folds_covers_every_row_exactly_once_in_order():
    df = pd.DataFrame({"value": range(37)})
    folds = split_into_folds(df, n_folds=4)
    reassembled = pd.concat(folds, ignore_index=True)
    assert reassembled["value"].tolist() == list(range(37))


def _passing_result(**overrides):
    defaults = dict(
        equity_curve=[10000.0, 10100.0], trades=[{"x": 1}] * 30,
        sharpe=1.5, max_drawdown=0.10, win_rate=0.50, pdt_compliant=True,
    )
    defaults.update(overrides)
    return BacktestResult(**defaults)


def test_check_fold_thresholds_passes_when_every_metric_clears():
    check_fold_thresholds(_passing_result(), fold_index=0)  # no exception == pass


def test_check_fold_thresholds_rejects_low_sharpe():
    with pytest.raises(GuardrailViolation, match="fold 2.*sharpe"):
        check_fold_thresholds(_passing_result(sharpe=0.5), fold_index=2)


def test_check_fold_thresholds_rejects_excessive_drawdown():
    with pytest.raises(GuardrailViolation, match="fold 1.*drawdown"):
        check_fold_thresholds(_passing_result(max_drawdown=0.30), fold_index=1)


def test_check_fold_thresholds_rejects_low_win_rate():
    with pytest.raises(GuardrailViolation, match="fold 0.*win rate"):
        check_fold_thresholds(_passing_result(win_rate=0.30), fold_index=0)


def test_check_fold_thresholds_rejects_too_few_trades():
    with pytest.raises(GuardrailViolation, match="fold 3.*trades"):
        check_fold_thresholds(_passing_result(trades=[{"x": 1}] * 10), fold_index=3)


def test_period_returns_computes_simple_percent_changes():
    assert _period_returns([100.0, 110.0, 99.0]) == pytest.approx([0.10, -0.10])


def test_skewness_of_symmetric_returns_is_zero():
    assert _skewness([0.01, -0.01, 0.02, -0.02, 0.0]) == pytest.approx(0.0, abs=1e-9)


def test_kurtosis_of_symmetric_returns():
    assert _kurtosis([0.01, -0.01, 0.02, -0.02, 0.0]) == pytest.approx(1.7)


def test_skewness_of_left_skewed_returns_is_negative():
    assert _skewness([0.01, 0.01, 0.01, 0.01, -0.10]) == pytest.approx(-1.5)


def test_kurtosis_of_flat_returns_is_normal_default():
    assert _kurtosis([0.0, 0.0, 0.0]) == pytest.approx(3.0)


def test_expected_max_z_is_zero_for_a_single_trial():
    assert expected_max_z(1) == 0.0


def test_expected_max_z_increases_with_more_trials():
    z2 = expected_max_z(2)
    z10 = expected_max_z(10)
    z100 = expected_max_z(100)
    assert z2 == pytest.approx(0.5197553442805939)
    assert z2 < z10 < z100


def test_deflated_sharpe_ratio_decreases_as_trial_count_grows():
    sharpe, n_returns, skew, kurt = 0.06, 500, 0.0, 3.0
    values = [
        deflated_sharpe_ratio(sharpe, nt, n_returns, skew, kurt)
        for nt in (1, 2, 10, 50, 100, 500, 1000)
    ]
    assert values == sorted(values, reverse=True)  # strictly non-increasing in n_trials
    assert values[0] == pytest.approx(0.909729935836157)


def test_deflated_sharpe_ratio_crosses_below_threshold_as_trials_pile_up():
    # Verified by hand during planning: a strategy that clears DSR>=0.95 comfortably
    # as the very first trial can fail it once enough other candidates have been tried.
    sharpe, n_returns, skew, kurt = 0.15, 1000, 0.0, 3.0
    assert deflated_sharpe_ratio(sharpe, 1, n_returns, skew, kurt) == pytest.approx(
        0.9999987890623048
    )
    assert deflated_sharpe_ratio(sharpe, 1000, n_returns, skew, kurt) == pytest.approx(
        0.927783097961449
    )


def test_trial_count_is_zero_for_a_fresh_log(tmp_path):
    path = tmp_path / "trials.json"
    assert _trial_count(path=path) == 0


def test_append_trial_creates_the_file_if_missing(tmp_path):
    path = tmp_path / "trials.json"
    _append_trial("SERV", tier=3, passed=True, sharpe=0.08, path=path)
    rows = json.loads(path.read_text())
    assert len(rows) == 1
    assert rows[0]["symbol"] == "SERV"
    assert rows[0]["tier"] == 3
    assert rows[0]["passed"] is True
    assert rows[0]["sharpe"] == 0.08
    assert "timestamp" in rows[0]


def test_append_trial_preserves_prior_rows_and_increments_count(tmp_path):
    path = tmp_path / "trials.json"
    _append_trial("AAPL", tier=2, passed=True, sharpe=0.10, path=path)
    _append_trial("SERV", tier=3, passed=False, sharpe=None, path=path)

    rows = json.loads(path.read_text())
    assert [r["symbol"] for r in rows] == ["AAPL", "SERV"]
    assert rows[1]["passed"] is False
    assert rows[1]["sharpe"] is None
    assert _trial_count(path=path) == 2


def _fake_history_df(n_rows=8):
    return pd.DataFrame({
        "time": pd.date_range("2020-01-01", periods=n_rows, freq="6h"),
        "open": [100.0] * n_rows, "high": [101.0] * n_rows,
        "low": [99.0] * n_rows, "close": [100.0] * n_rows, "volume": [1000] * n_rows,
    })


def _result(**overrides):
    defaults = dict(
        equity_curve=[10000.0] + [10000.0 + i for i in range(1, 400)],
        trades=[{"x": 1}] * 300,
        sharpe=1.5, max_drawdown=0.10, win_rate=0.50, pdt_compliant=True,
    )
    defaults.update(overrides)
    return BacktestResult(**defaults)


def test_validate_symbol_backtest_passes_and_logs_when_every_check_clears(tmp_path):
    log_path = tmp_path / "trials.json"
    full_result = _result()
    fold_result = _result(trades=[{"x": 1}] * 30)

    with patch("graywind_strategy.backtest_gate.fetch_backtest_bars", return_value=_fake_history_df()), \
         patch("graywind_strategy.backtest_gate.run_backtest",
               side_effect=[full_result, fold_result, fold_result, fold_result, fold_result]), \
         patch("graywind_strategy.backtest_gate.deflated_sharpe_ratio", return_value=0.99):
        validate_symbol_backtest("SERV", tier=3, data_client=MagicMock(), trial_log_path=log_path)

    rows = json.loads(log_path.read_text())
    assert len(rows) == 1
    assert rows[0]["symbol"] == "SERV"
    assert rows[0]["tier"] == 3
    assert rows[0]["passed"] is True
    assert rows[0]["sharpe"] is not None


def test_validate_symbol_backtest_rejects_and_logs_on_full_period_trade_count_floor(tmp_path):
    log_path = tmp_path / "trials.json"
    thin_result = _result(trades=[{"x": 1}] * 5)  # below MIN_TOTAL_TRADES

    with patch("graywind_strategy.backtest_gate.fetch_backtest_bars", return_value=_fake_history_df()), \
         patch("graywind_strategy.backtest_gate.run_backtest", return_value=thin_result):
        with pytest.raises(GuardrailViolation, match="total trades"):
            validate_symbol_backtest("SERV", tier=3, data_client=MagicMock(), trial_log_path=log_path)

    rows = json.loads(log_path.read_text())
    assert len(rows) == 1
    assert rows[0]["passed"] is False
    assert rows[0]["sharpe"] is None  # rejected before a raw sharpe was ever computed


def test_validate_symbol_backtest_rejects_on_a_failing_fold(tmp_path):
    log_path = tmp_path / "trials.json"
    full_result = _result()
    bad_fold = _result(sharpe=0.2)

    with patch("graywind_strategy.backtest_gate.fetch_backtest_bars", return_value=_fake_history_df()), \
         patch("graywind_strategy.backtest_gate.run_backtest",
               side_effect=[full_result, bad_fold]):
        with pytest.raises(GuardrailViolation, match="fold 0.*sharpe"):
            validate_symbol_backtest("SERV", tier=3, data_client=MagicMock(), trial_log_path=log_path)

    rows = json.loads(log_path.read_text())
    assert len(rows) == 1
    assert rows[0]["passed"] is False
    assert rows[0]["sharpe"] is not None  # full-period sharpe was already computed by this point


def test_validate_symbol_backtest_rejects_on_low_deflated_sharpe(tmp_path):
    log_path = tmp_path / "trials.json"
    full_result = _result()
    fold_result = _result(trades=[{"x": 1}] * 30)

    with patch("graywind_strategy.backtest_gate.fetch_backtest_bars", return_value=_fake_history_df()), \
         patch("graywind_strategy.backtest_gate.run_backtest",
               side_effect=[full_result, fold_result, fold_result, fold_result, fold_result]), \
         patch("graywind_strategy.backtest_gate.deflated_sharpe_ratio", return_value=0.40):
        with pytest.raises(GuardrailViolation, match="deflated Sharpe"):
            validate_symbol_backtest("SERV", tier=3, data_client=MagicMock(), trial_log_path=log_path)

    rows = json.loads(log_path.read_text())
    assert rows[0]["passed"] is False


def test_validate_symbol_backtest_rejects_before_any_backtest_when_history_too_short(tmp_path):
    log_path = tmp_path / "trials.json"

    with patch("graywind_strategy.backtest_gate.fetch_backtest_bars",
               side_effect=GuardrailViolation("SERV has only 90 days of history, "
                                               "backtest gate requires at least 730")), \
         patch("graywind_strategy.backtest_gate.run_backtest") as mock_run_backtest:
        with pytest.raises(GuardrailViolation, match="90 days"):
            validate_symbol_backtest("SERV", tier=3, data_client=MagicMock(), trial_log_path=log_path)

    mock_run_backtest.assert_not_called()
    rows = json.loads(log_path.read_text())
    assert len(rows) == 1
    assert rows[0]["passed"] is False
    assert rows[0]["sharpe"] is None


def test_validate_symbol_backtest_passes_growing_n_trials_into_deflated_sharpe_ratio(tmp_path):
    log_path = tmp_path / "trials.json"
    log_path.write_text(json.dumps([
        {"symbol": f"SYM{i}", "tier": 2, "timestamp": "2020-01-01T00:00:00+00:00",
         "passed": True, "sharpe": 0.05}
        for i in range(4)
    ]))
    full_result = _result()
    fold_result = _result(trades=[{"x": 1}] * 30)

    with patch("graywind_strategy.backtest_gate.fetch_backtest_bars", return_value=_fake_history_df()), \
         patch("graywind_strategy.backtest_gate.run_backtest",
               side_effect=[full_result, fold_result, fold_result, fold_result, fold_result]), \
         patch("graywind_strategy.backtest_gate.deflated_sharpe_ratio", return_value=0.99) as mock_dsr:
        validate_symbol_backtest("SERV", tier=3, data_client=MagicMock(), trial_log_path=log_path)

    # 4 prior rows + this candidate itself == 5
    assert mock_dsr.call_args.args[1] == 5
