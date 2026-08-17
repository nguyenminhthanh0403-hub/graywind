from datetime import date
from unittest.mock import MagicMock, patch

import requests

from graywind_strategy.gates.earnings_gate import EarningsDataUnavailable
from graywind_strategy.gates.macro_gate import MacroDataUnavailable
from graywind_strategy.gates.sector_gates import evaluate_sector_gates
from graywind_strategy.gates.sentiment_gate import SentimentDataUnavailable
from graywind_strategy.gates.vix_gate import VixDataUnavailable
from graywind_strategy.pipeline import (
    evaluate_earnings_gate,
    evaluate_macro_gate,
    evaluate_sentiment_gate,
    evaluate_vix_gate,
    decide_trade,
)
from graywind_strategy.risk.pdt_throttle import PDTThrottle
from graywind_strategy.risk.position_sizing import PositionSizer


def test_evaluate_vix_gate_fails_closed_on_fetch_error():
    with patch("graywind_strategy.pipeline.fetch_latest_vix", side_effect=VixDataUnavailable("boom")):
        assert evaluate_vix_gate(fred_api_key="k", as_of_date=date(2024, 1, 8)) is False


def test_evaluate_vix_gate_passes_through_on_success():
    with patch("graywind_strategy.pipeline.fetch_latest_vix", return_value=15.0) as mock_fetch:
        assert evaluate_vix_gate(fred_api_key="k", as_of_date=date(2024, 1, 8)) is True
    mock_fetch.assert_called_once_with("k", today=date(2024, 1, 8))


def test_evaluate_sentiment_gate_fails_closed_on_fetch_error():
    with patch(
        "graywind_strategy.pipeline.fetch_recent_headlines",
        side_effect=SentimentDataUnavailable("boom"),
    ):
        assert evaluate_sentiment_gate(
            news_client=object(), symbol="AAPL", as_of_date=date(2024, 1, 8)
        ) is False


def test_evaluate_sentiment_gate_forwards_as_of_date_to_fetch():
    news_client = object()
    with patch("graywind_strategy.pipeline.fetch_recent_headlines", return_value=[]) as mock_fetch:
        assert evaluate_sentiment_gate(
            news_client=news_client, symbol="AAPL", as_of_date=date(2024, 1, 8)
        ) is True
    mock_fetch.assert_called_once_with(news_client, "AAPL", as_of=date(2024, 1, 8))


def test_evaluate_earnings_gate_fails_closed_on_fetch_error():
    with patch(
        "graywind_strategy.pipeline.fetch_next_earnings_date",
        side_effect=EarningsDataUnavailable("boom"),
    ):
        assert evaluate_earnings_gate(
            symbol="AAPL", finnhub_api_key="k", as_of_date=date(2024, 1, 8)
        ) is False


def test_evaluate_macro_gate_fails_closed_on_fetch_error():
    with patch(
        "graywind_strategy.pipeline.fetch_bullion_macro_snapshot",
        side_effect=MacroDataUnavailable("boom"),
    ):
        assert evaluate_macro_gate(as_of_date=date(2024, 1, 8)) is False


def test_evaluate_macro_gate_passes_through_on_success():
    snapshot = {"vix": 14.6, "nfci": -0.55, "hy_oas": 2.71, "curve_slope": 0.48}
    with patch(
        "graywind_strategy.pipeline.fetch_bullion_macro_snapshot", return_value=snapshot
    ) as mock_fetch:
        assert evaluate_macro_gate(as_of_date=date(2024, 1, 8)) is True
    mock_fetch.assert_called_once_with(date(2024, 1, 8), session=requests)


def _passing_gates():
    return patch.multiple(
        "graywind_strategy.pipeline",
        evaluate_vix_gate=lambda **kw: True,
        evaluate_sentiment_gate=lambda **kw: True,
        evaluate_earnings_gate=lambda **kw: True,
        evaluate_macro_gate=lambda **kw: True,
        evaluate_sector_gates=lambda **kw: True,
    )


def test_decide_trade_buys_when_signal_and_all_gates_and_risk_checks_pass():
    with _passing_gates():
        decision = decide_trade(
            symbol="AAPL",
            signal="buy",
            as_of_date=date(2024, 1, 8),
            current_price=100.0,
            account_equity=10000.0,
            pdt_throttle=PDTThrottle(),
            position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True,
            fred_api_key="k",
            news_client=object(),
            finnhub_api_key="k",
        )
    # Pinned to the actual PositionSizer math for these inputs (stop_pct=0.02,
    # take_profit_pct=0.03, risk_fraction=0.01) rather than just direction
    # checks, so a swapped stop/target percentage would fail this test.
    assert decision.action == "buy"
    assert decision.stop_price == PositionSizer.stop_loss_price(100.0, 0.02) == 98.0
    assert decision.target_price == PositionSizer.take_profit_price(100.0, 0.03) == 103.0
    assert decision.shares == PositionSizer(risk_fraction=0.01).shares_to_buy(10000.0, 100.0, 98.0) == 50


def test_decide_trade_holds_on_non_buy_signal():
    with _passing_gates():
        decision = decide_trade(
            symbol="AAPL",
            signal="hold",
            as_of_date=date(2024, 1, 8),
            current_price=100.0,
            account_equity=10000.0,
            pdt_throttle=PDTThrottle(),
            position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True,
            fred_api_key="k",
            news_client=object(),
            finnhub_api_key="k",
        )
    assert decision.action == "hold"


def test_decide_trade_blocks_when_drawdown_breaker_tripped():
    with _passing_gates():
        decision = decide_trade(
            symbol="AAPL",
            signal="buy",
            as_of_date=date(2024, 1, 8),
            current_price=100.0,
            account_equity=10000.0,
            pdt_throttle=PDTThrottle(),
            position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=False,
            fred_api_key="k",
            news_client=object(),
            finnhub_api_key="k",
        )
    assert decision.action == "blocked"
    assert decision.reason == "drawdown_breaker"


def test_decide_trade_blocks_when_drawdown_breaker_state_unknown():
    # None means "caller couldn't determine the breaker's state" -- must
    # fail closed exactly like a confirmed-tripped breaker, never guess-allow.
    with _passing_gates():
        decision = decide_trade(
            symbol="AAPL",
            signal="buy",
            as_of_date=date(2024, 1, 8),
            current_price=100.0,
            account_equity=10000.0,
            pdt_throttle=PDTThrottle(),
            position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=None,
            fred_api_key="k",
            news_client=object(),
            finnhub_api_key="k",
        )
    assert decision.action == "blocked"
    assert decision.reason == "drawdown_breaker"


def test_decide_trade_blocks_when_pdt_throttle_exhausted():
    throttle = PDTThrottle()
    for d in [date(2024, 1, 8), date(2024, 1, 9), date(2024, 1, 10)]:
        throttle.record_day_trade(d)
    with _passing_gates():
        decision = decide_trade(
            symbol="AAPL",
            signal="buy",
            as_of_date=date(2024, 1, 11),
            current_price=100.0,
            account_equity=10000.0,
            pdt_throttle=throttle,
            position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True,
            fred_api_key="k",
            news_client=object(),
            finnhub_api_key="k",
        )
    assert decision.action == "blocked"
    assert decision.reason == "pdt_throttle"


def test_decide_trade_blocks_on_pdt_throttle_when_pending_same_day_trades_would_hit_cap():
    # 2 realized day trades on record; the throttle alone (pending_count=0)
    # would allow a 3rd. But 2 OTHER same-day-opened positions are still
    # open right now (e.g. a different symbol reopened before closing) --
    # if either or both of those close later today, that's up to 4 realized
    # day trades, a real PDT violation. pending_same_day_trades must make
    # decide_trade block here even though the throttle's realized count
    # alone would not have.
    throttle = PDTThrottle()
    throttle.record_day_trade(date(2024, 1, 8))
    throttle.record_day_trade(date(2024, 1, 8))
    with _passing_gates():
        decision = decide_trade(
            symbol="AAPL",
            signal="buy",
            as_of_date=date(2024, 1, 8),
            current_price=100.0,
            account_equity=10000.0,
            pdt_throttle=throttle,
            position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True,
            fred_api_key="k",
            news_client=object(),
            finnhub_api_key="k",
            pending_same_day_trades=1,
        )
    assert decision.action == "blocked"
    assert decision.reason == "pdt_throttle"


def test_decide_trade_blocks_on_vix_gate_failure():
    with patch.multiple(
        "graywind_strategy.pipeline",
        evaluate_vix_gate=MagicMock(return_value=False),
        evaluate_sentiment_gate=MagicMock(return_value=True),
        evaluate_earnings_gate=MagicMock(return_value=True),
    ):
        decision = decide_trade(
            symbol="AAPL", signal="buy", as_of_date=date(2024, 1, 8),
            current_price=100.0, account_equity=10000.0,
            pdt_throttle=PDTThrottle(), position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        )
    assert decision.action == "blocked"
    assert decision.reason == "vix_gate"


def test_decide_trade_blocks_on_sentiment_gate_failure():
    earnings_mock = MagicMock(return_value=True)
    with patch.multiple(
        "graywind_strategy.pipeline",
        evaluate_vix_gate=MagicMock(return_value=True),
        evaluate_sentiment_gate=MagicMock(return_value=False),
        evaluate_earnings_gate=earnings_mock,
    ):
        decision = decide_trade(
            symbol="AAPL", signal="buy", as_of_date=date(2024, 1, 8),
            current_price=100.0, account_equity=10000.0,
            pdt_throttle=PDTThrottle(), position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        )
    assert decision.action == "blocked"
    assert decision.reason == "sentiment_gate"
    earnings_mock.assert_not_called()


def test_decide_trade_blocks_on_earnings_gate_failure():
    with patch.multiple(
        "graywind_strategy.pipeline",
        evaluate_vix_gate=MagicMock(return_value=True),
        evaluate_sentiment_gate=MagicMock(return_value=True),
        evaluate_earnings_gate=MagicMock(return_value=False),
    ):
        decision = decide_trade(
            symbol="AAPL", signal="buy", as_of_date=date(2024, 1, 8),
            current_price=100.0, account_equity=10000.0,
            pdt_throttle=PDTThrottle(), position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        )
    assert decision.action == "blocked"
    assert decision.reason == "earnings_gate"


def test_decide_trade_blocks_on_macro_gate_failure():
    with patch.multiple(
        "graywind_strategy.pipeline",
        evaluate_vix_gate=MagicMock(return_value=True),
        evaluate_sentiment_gate=MagicMock(return_value=True),
        evaluate_earnings_gate=MagicMock(return_value=True),
        evaluate_macro_gate=MagicMock(return_value=False),
    ):
        decision = decide_trade(
            symbol="AAPL", signal="buy", as_of_date=date(2024, 1, 8),
            current_price=100.0, account_equity=10000.0,
            pdt_throttle=PDTThrottle(), position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        )
    assert decision.action == "blocked"
    assert decision.reason == "macro_gate"


def test_decide_trade_blocks_on_sector_gate_failure():
    with patch.multiple(
        "graywind_strategy.pipeline",
        evaluate_vix_gate=MagicMock(return_value=True),
        evaluate_sentiment_gate=MagicMock(return_value=True),
        evaluate_earnings_gate=MagicMock(return_value=True),
        evaluate_macro_gate=MagicMock(return_value=True),
        evaluate_sector_gates=MagicMock(return_value=False),
    ):
        decision = decide_trade(
            symbol="XOM", signal="buy", as_of_date=date(2024, 1, 8),
            current_price=100.0, account_equity=10000.0,
            pdt_throttle=PDTThrottle(), position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        )
    assert decision.action == "blocked"
    assert decision.reason == "sector_gate"


def test_decide_trade_short_circuits_before_later_gates_on_vix_block():
    vix_mock = MagicMock(return_value=False)
    sentiment_mock = MagicMock(return_value=True)
    earnings_mock = MagicMock(return_value=True)
    with patch.multiple(
        "graywind_strategy.pipeline",
        evaluate_vix_gate=vix_mock, evaluate_sentiment_gate=sentiment_mock, evaluate_earnings_gate=earnings_mock,
    ):
        decide_trade(
            symbol="AAPL", signal="buy", as_of_date=date(2024, 1, 8),
            current_price=100.0, account_equity=10000.0,
            pdt_throttle=PDTThrottle(), position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        )
    vix_mock.assert_called_once()
    sentiment_mock.assert_not_called()
    earnings_mock.assert_not_called()


def test_decide_trade_holds_when_position_size_rounds_to_zero():
    with _passing_gates():
        decision = decide_trade(
            symbol="AAPL", signal="buy", as_of_date=date(2024, 1, 8),
            current_price=100.0, account_equity=1.0,  # tiny equity -> 0 shares
            pdt_throttle=PDTThrottle(), position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        )
    assert decision.action == "hold"
    assert decision.reason == "position size rounds to zero shares"


def test_decide_trade_gates_always_pass_bypasses_gates_and_reaches_risk_checks():
    # Final-review Fix 4: gates_always_pass=True is the plan-specified,
    # supported bypass for testing/synthetic-data runs (replacing the
    # monkeypatch scripts/task11_integration_run.py used to need). Even with
    # evaluate_vix_gate mocked to return False (which would normally block
    # the trade), gates_always_pass=True must skip all three gate checks
    # entirely and let the decision reach the PDT/drawdown/sizing checks --
    # proving the bypass is real, not just accepted-but-ignored.
    vix_mock = MagicMock(return_value=False)
    sentiment_mock = MagicMock(return_value=False)
    earnings_mock = MagicMock(return_value=False)
    macro_mock = MagicMock(return_value=False)
    sector_mock = MagicMock(return_value=False)
    with patch.multiple(
        "graywind_strategy.pipeline",
        evaluate_vix_gate=vix_mock,
        evaluate_sentiment_gate=sentiment_mock,
        evaluate_earnings_gate=earnings_mock,
        evaluate_macro_gate=macro_mock,
        evaluate_sector_gates=sector_mock,
    ):
        decision = decide_trade(
            symbol="AAPL",
            signal="buy",
            as_of_date=date(2024, 1, 8),
            current_price=100.0,
            account_equity=10000.0,
            pdt_throttle=PDTThrottle(),
            position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True,
            fred_api_key="k",
            news_client=object(),
            finnhub_api_key="k",
            gates_always_pass=True,
        )
    assert decision.action == "buy"
    vix_mock.assert_not_called()
    sentiment_mock.assert_not_called()
    earnings_mock.assert_not_called()
    macro_mock.assert_not_called()
    sector_mock.assert_not_called()


def test_decide_trade_holds_on_degenerate_low_price_instead_of_raising():
    # At current_price=0.10, stop_loss_price rounds the 2% stop back onto the
    # entry price (round(0.10 * 0.98, 2) == 0.10), which would make
    # PositionSizer.shares_to_buy raise ValueError. decide_trade must guard
    # this and fail to "hold", never propagate an exception.
    with _passing_gates():
        decision = decide_trade(
            symbol="AAPL", signal="buy", as_of_date=date(2024, 1, 8),
            current_price=0.10, account_equity=10000.0,
            pdt_throttle=PDTThrottle(), position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        )
    assert decision.action == "hold"
    assert decision.reason == "invalid price for sizing"
