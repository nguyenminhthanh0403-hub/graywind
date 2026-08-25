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


def test_shares_to_buy_caps_position_value_below_small_account_threshold():
    sizer = PositionSizer(risk_fraction=0.01)
    # Risk-based sizing alone would buy 200 shares ($1,000 = 100% of equity).
    # Below the $2,000 threshold, the 50% cap should bring it down to 100 shares ($500).
    shares = sizer.shares_to_buy(account_equity=1000, entry_price=5, stop_price=4.95)
    assert shares == 100


def test_shares_to_buy_leaves_risk_based_sizing_unchanged_when_under_cap():
    sizer = PositionSizer(risk_fraction=0.01)
    # Risk-based sizing alone buys 5 shares ($250 = 25% of equity) -- already
    # under the 50% cap ($500 / $50 = 10 shares), so the cap must not bind.
    shares = sizer.shares_to_buy(account_equity=1000, entry_price=50, stop_price=48)
    assert shares == 5


def test_shares_to_buy_cap_does_not_apply_exactly_at_threshold():
    sizer = PositionSizer(risk_fraction=0.01)
    # Equity exactly at the $2,000 threshold is NOT small-account mode (strict <).
    # Risk-based sizing alone buys 400 shares ($2,000 = 100% of equity); if the
    # cap wrongly applied here it would reduce this to 200 shares.
    shares = sizer.shares_to_buy(account_equity=2000, entry_price=5, stop_price=4.95)
    assert shares == 400


def test_shares_to_buy_unaffected_far_above_threshold():
    sizer = PositionSizer(risk_fraction=0.01)
    # Equity far above the $2,000 threshold never enters small-account mode,
    # regardless of what fraction of equity the resulting position is worth.
    shares = sizer.shares_to_buy(account_equity=50000, entry_price=100, stop_price=99)
    assert shares == 500


def test_init_raises_on_negative_small_account_threshold():
    with pytest.raises(ValueError):
        PositionSizer(small_account_threshold=-100)


def test_init_raises_on_zero_small_account_cap_fraction():
    with pytest.raises(ValueError):
        PositionSizer(small_account_cap_fraction=0.0)


def test_init_raises_on_invalid_small_account_cap_fraction_above_one():
    with pytest.raises(ValueError):
        PositionSizer(small_account_cap_fraction=1.5)
