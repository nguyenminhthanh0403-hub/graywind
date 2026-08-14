from datetime import date
from unittest.mock import patch

from graywind_strategy.gates.earnings_gate import EarningsDataUnavailable
from graywind_strategy.gates.sentiment_gate import SentimentDataUnavailable
from graywind_strategy.gates.vix_gate import VixDataUnavailable
from graywind_strategy.pipeline import (
    evaluate_earnings_gate,
    evaluate_sentiment_gate,
    evaluate_vix_gate,
    decide_trade,
)
from graywind_strategy.risk.drawdown_breaker import DrawdownBreaker
from graywind_strategy.risk.pdt_throttle import PDTThrottle
from graywind_strategy.risk.position_sizing import PositionSizer


def test_evaluate_vix_gate_fails_closed_on_fetch_error():
    with patch("graywind_strategy.pipeline.fetch_latest_vix", side_effect=VixDataUnavailable("boom")):
        assert evaluate_vix_gate(fred_api_key="k") is False


def test_evaluate_vix_gate_passes_through_on_success():
    with patch("graywind_strategy.pipeline.fetch_latest_vix", return_value=15.0):
        assert evaluate_vix_gate(fred_api_key="k") is True


def test_evaluate_sentiment_gate_fails_closed_on_fetch_error():
    with patch(
        "graywind_strategy.pipeline.fetch_recent_headlines",
        side_effect=SentimentDataUnavailable("boom"),
    ):
        assert evaluate_sentiment_gate(news_client=object(), symbol="AAPL") is False


def test_evaluate_earnings_gate_fails_closed_on_fetch_error():
    with patch(
        "graywind_strategy.pipeline.fetch_next_earnings_date",
        side_effect=EarningsDataUnavailable("boom"),
    ):
        assert evaluate_earnings_gate(
            symbol="AAPL", finnhub_api_key="k", as_of_date=date(2024, 1, 8)
        ) is False


def _passing_gates():
    return patch.multiple(
        "graywind_strategy.pipeline",
        evaluate_vix_gate=lambda **kw: True,
        evaluate_sentiment_gate=lambda **kw: True,
        evaluate_earnings_gate=lambda **kw: True,
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
    assert decision.action == "buy"
    assert decision.shares > 0
    assert decision.stop_price < 100.0
    assert decision.target_price > 100.0


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
