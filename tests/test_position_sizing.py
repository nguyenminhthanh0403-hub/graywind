import pytest

from graywind_strategy.risk.position_sizing import PositionSizer


def test_shares_to_buy_risks_exactly_the_configured_fraction_of_equity():
    sizer = PositionSizer(risk_fraction=0.01)
    shares = sizer.shares_to_buy(account_equity=10000, entry_price=50, stop_price=49)
    assert shares == 100  # $100 at risk / $1 risk-per-share


def test_shares_to_buy_rounds_down_to_whole_shares():
    sizer = PositionSizer(risk_fraction=0.01)
    shares = sizer.shares_to_buy(account_equity=10000, entry_price=50, stop_price=49.7)
    assert shares == 333  # $100 / $0.30 = 333.33 -> floor to 333


def test_shares_to_buy_raises_when_stop_not_below_entry():
    sizer = PositionSizer(risk_fraction=0.01)
    with pytest.raises(ValueError):
        sizer.shares_to_buy(account_equity=10000, entry_price=50, stop_price=50)


def test_init_raises_on_invalid_risk_fraction():
    with pytest.raises(ValueError):
        PositionSizer(risk_fraction=1.5)


def test_stop_loss_price():
    assert PositionSizer.stop_loss_price(entry_price=100, stop_pct=0.02) == 98.0


def test_take_profit_price():
    assert PositionSizer.take_profit_price(entry_price=100, take_profit_pct=0.03) == 103.0
