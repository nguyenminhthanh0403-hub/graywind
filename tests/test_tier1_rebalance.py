from datetime import date

from graywind_strategy.tier1_rebalance import (
    RebalanceOrder, compute_rebalance_orders, should_rebalance_this_month,
)


def test_no_order_when_within_drift_threshold():
    orders = compute_rebalance_orders(
        tier1_equity=1000.0,
        current_holdings={"VTI": 6.0, "BND": 4.0},
        current_prices={"VTI": 100.0, "BND": 100.0},
        target_weights={"VTI": 0.6, "BND": 0.4},
    )
    assert orders == []


def test_sell_order_when_overweight():
    # target_value = 1000 * 0.6 = 600; current_value = 7.0 * 100 = 700;
    # drift = (700 - 600) / 1000 = 0.10 > 0.05 -> sell the gap: (700-600)/100 = 1.0 shares
    orders = compute_rebalance_orders(
        tier1_equity=1000.0,
        current_holdings={"VTI": 7.0},
        current_prices={"VTI": 100.0},
        target_weights={"VTI": 0.6},
    )
    assert orders == [RebalanceOrder(symbol="VTI", side="sell", qty=1.0)]


def test_buy_order_when_underweight():
    # target_value = 600; current_value = 5.0 * 100 = 500;
    # drift = (500 - 600) / 1000 = -0.10 < -0.05 -> buy (600-500)/100 = 1.0 shares
    orders = compute_rebalance_orders(
        tier1_equity=1000.0,
        current_holdings={"VTI": 5.0},
        current_prices={"VTI": 100.0},
        target_weights={"VTI": 0.6},
    )
    assert orders == [RebalanceOrder(symbol="VTI", side="buy", qty=1.0)]


def test_no_order_exactly_at_drift_threshold_boundary():
    # target_value = 600; current_value = 6.5 * 100 = 650;
    # drift = (650 - 600) / 1000 = 0.05 exactly -> NOT > threshold (strict), no order
    orders = compute_rebalance_orders(
        tier1_equity=1000.0,
        current_holdings={"VTI": 6.5},
        current_prices={"VTI": 100.0},
        target_weights={"VTI": 0.6},
    )
    assert orders == []


def test_skips_symbol_missing_from_current_prices():
    # BND has no price -- must be skipped even though, if computed, its
    # drift (holds 0 against a 0.4 target weight) would clearly exceed
    # the threshold. VTI is exactly at target, so the empty result proves
    # BND was genuinely skipped, not coincidentally in-threshold too.
    orders = compute_rebalance_orders(
        tier1_equity=1000.0,
        current_holdings={"VTI": 6.0, "BND": 0.0},
        current_prices={"VTI": 100.0},  # BND price missing
        target_weights={"VTI": 0.6, "BND": 0.4},
    )
    assert orders == []


def test_multiple_symbols_produce_independent_orders():
    orders = compute_rebalance_orders(
        tier1_equity=1000.0,
        current_holdings={"VTI": 7.0, "BND": 2.0},
        current_prices={"VTI": 100.0, "BND": 100.0},
        target_weights={"VTI": 0.6, "BND": 0.4},
    )
    assert orders == [
        RebalanceOrder(symbol="VTI", side="sell", qty=1.0),
        RebalanceOrder(symbol="BND", side="buy", qty=2.0),
    ]


# --- should_rebalance_this_month

def test_should_rebalance_when_never_rebalanced():
    assert should_rebalance_this_month(None, date(2026, 8, 26)) is True


def test_should_not_rebalance_when_already_done_this_month():
    assert should_rebalance_this_month("2026-08", date(2026, 8, 26)) is False


def test_should_rebalance_when_month_has_changed():
    assert should_rebalance_this_month("2026-07", date(2026, 8, 26)) is True
