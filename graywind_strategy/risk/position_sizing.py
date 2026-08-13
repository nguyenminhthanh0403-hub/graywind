"""Fixed-fractional position sizing: risk a fixed percentage of account
equity per trade, sized off the distance to the stop-loss.
"""


class PositionSizer:
    def __init__(self, risk_fraction=0.01):
        if not 0 < risk_fraction < 1:
            raise ValueError("risk_fraction must be between 0 and 1")
        self.risk_fraction = risk_fraction

    def shares_to_buy(self, account_equity, entry_price, stop_price):
        if stop_price >= entry_price:
            raise ValueError("stop_price must be below entry_price for a long position")
        risk_per_share = entry_price - stop_price
        dollars_at_risk = account_equity * self.risk_fraction
        return int(dollars_at_risk // risk_per_share)

    @staticmethod
    def stop_loss_price(entry_price, stop_pct):
        return round(entry_price * (1 - stop_pct), 2)

    @staticmethod
    def take_profit_price(entry_price, take_profit_pct):
        return round(entry_price * (1 + take_profit_pct), 2)
