"""Fixed-fractional position sizing: risk a fixed percentage of account
equity per trade, sized off the distance to the stop-loss. Below
low_capital_threshold, low_capital_risk_fraction applies instead of
standard_risk_fraction -- a small account's risk-based size would
otherwise round toward nothing once fractional-share output is floored
by MIN_NOTIONAL below. Below small_account_threshold, position value is
additionally capped to a fraction of equity, since risk-based sizing
alone can exceed the whole account when equity is small relative to
share price. Both thresholds are evaluated fresh on every call against
whatever account_equity the caller passes in, so behavior tracks the
account's actual size cycle-to-cycle rather than a value fixed at
construction time. Output is fractional (rounded to QTY_DECIMALS places)
to support Alpaca fractional-share orders; a position worth less than
MIN_NOTIONAL is floored to 0.
"""

QTY_DECIMALS = 4
MIN_NOTIONAL = 1.0


class PositionSizer:
    def __init__(self, standard_risk_fraction=0.01, low_capital_risk_fraction=0.03,
                 low_capital_threshold=5000.0, small_account_threshold=2000.0,
                 small_account_cap_fraction=0.50):
        if not 0 < standard_risk_fraction < 1:
            raise ValueError("standard_risk_fraction must be between 0 and 1")
        if not 0 < low_capital_risk_fraction < 1:
            raise ValueError("low_capital_risk_fraction must be between 0 and 1")
        if low_capital_threshold < 0:
            raise ValueError("low_capital_threshold must be >= 0")
        if small_account_threshold < 0:
            raise ValueError("small_account_threshold must be >= 0")
        if not 0 < small_account_cap_fraction <= 1:
            raise ValueError("small_account_cap_fraction must be between 0 and 1 (inclusive)")
        self.standard_risk_fraction = standard_risk_fraction
        self.low_capital_risk_fraction = low_capital_risk_fraction
        self.low_capital_threshold = low_capital_threshold
        self.small_account_threshold = small_account_threshold
        self.small_account_cap_fraction = small_account_cap_fraction

    def shares_to_buy(self, account_equity, entry_price, stop_price):
        if stop_price >= entry_price:
            raise ValueError("stop_price must be below entry_price for a long position")
        risk_per_share = entry_price - stop_price
        risk_fraction = (
            self.low_capital_risk_fraction if account_equity < self.low_capital_threshold
            else self.standard_risk_fraction
        )
        dollars_at_risk = account_equity * risk_fraction
        shares = dollars_at_risk / risk_per_share
        if account_equity < self.small_account_threshold:
            cap_shares = (account_equity * self.small_account_cap_fraction) / entry_price
            shares = min(shares, cap_shares)
        shares = round(shares, QTY_DECIMALS)
        if shares * entry_price < MIN_NOTIONAL:
            return 0.0
        return shares

    @staticmethod
    def stop_loss_price(entry_price, stop_pct):
        return round(entry_price * (1 - stop_pct), 2)

    @staticmethod
    def take_profit_price(entry_price, take_profit_pct):
        return round(entry_price * (1 + take_profit_pct), 2)
