"""Fixed-fractional position sizing: risk a fixed percentage of account
equity per trade, sized off the distance to the stop-loss. Below
small_account_threshold, also caps position value to a fraction of
equity, since risk-based sizing alone can exceed the whole account when
equity is small relative to share price.
"""


class PositionSizer:
    def __init__(self, risk_fraction=0.01, small_account_threshold=2000.0,
                 small_account_cap_fraction=0.50):
        if not 0 < risk_fraction < 1:
            raise ValueError("risk_fraction must be between 0 and 1")
        self.risk_fraction = risk_fraction
        self.small_account_threshold = small_account_threshold
        self.small_account_cap_fraction = small_account_cap_fraction

    def shares_to_buy(self, account_equity, entry_price, stop_price):
        if stop_price >= entry_price:
            raise ValueError("stop_price must be below entry_price for a long position")
        risk_per_share = entry_price - stop_price
        dollars_at_risk = account_equity * self.risk_fraction
        shares = int(dollars_at_risk // risk_per_share)
        if account_equity < self.small_account_threshold:
            cap_shares = int((account_equity * self.small_account_cap_fraction) // entry_price)
            shares = min(shares, cap_shares)
        return shares

    @staticmethod
    def stop_loss_price(entry_price, stop_pct):
        return round(entry_price * (1 - stop_pct), 2)

    @staticmethod
    def take_profit_price(entry_price, take_profit_pct):
        return round(entry_price * (1 + take_profit_pct), 2)
