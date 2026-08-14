from graywind_strategy.backtester import max_drawdown, sharpe_ratio, win_rate


def test_sharpe_ratio_of_flat_equity_curve_is_zero():
    # Zero variance in returns -> Sharpe is defined as 0.0, not a division error.
    assert sharpe_ratio([10000, 10000, 10000, 10000], periods_per_year=252) == 0.0


def test_sharpe_ratio_positive_for_a_steadily_rising_equity_curve():
    curve = [10000 * (1.001 ** i) for i in range(50)]
    assert sharpe_ratio(curve, periods_per_year=252) > 0.0


def test_max_drawdown_of_monotonically_rising_curve_is_zero():
    assert max_drawdown([100, 110, 120, 130]) == 0.0


def test_max_drawdown_measures_the_worst_peak_to_trough_drop():
    # Peak 150, trough 120 -> (150-120)/150 = 0.2
    assert max_drawdown([100, 150, 130, 120, 140]) == 0.2


def test_win_rate_of_no_trades_is_zero():
    assert win_rate([]) == 0.0


def test_win_rate_counts_profitable_round_trips():
    trades = [
        {"symbol": "AAPL", "action": "buy", "price": 100.0, "shares": 10},
        {"symbol": "AAPL", "action": "sell", "price": 105.0, "shares": 10},  # +$50, win
        {"symbol": "SPY", "action": "buy", "price": 400.0, "shares": 5},
        {"symbol": "SPY", "action": "sell", "price": 395.0, "shares": 5},   # -$25, loss
    ]
    assert win_rate(trades) == 0.5
