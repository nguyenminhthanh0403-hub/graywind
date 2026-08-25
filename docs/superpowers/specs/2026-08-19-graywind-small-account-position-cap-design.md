# Graywind Small-Account Position-Value Cap — Design

**Date:** 2026-08-19
**Status:** approved, not yet implemented
**Prior art:** `graywind_strategy/risk/position_sizing.py` (`PositionSizer`), the class this
design extends directly. `graywind_strategy/risk/pdt_throttle.py` (`PDTThrottle`) for context —
PDT is a separate, already-implemented risk control and is explicitly out of scope here.

## Goal

`PositionSizer.shares_to_buy` sizes purely off risk-to-stop (`account_equity * risk_fraction /
risk_per_share`), with no cap tying the resulting position's dollar value back to
`account_equity`. Under this pipeline's standard config (`stop_pct=0.02`, `risk_fraction=0.01`),
position value is independent of account size — it stabilizes at ~50% of equity across accounts
from $500 to $500,000 (worst case ~69% on sub-$1 stocks due to `stop_loss_price`'s 2-decimal
rounding). However, the formula can still produce positions worth more than the entire account
when `stop_pct < risk_fraction` (e.g., a tighter stop like 0.5%) or on very cheap stocks ($0.20–$0.50)
— failure modes that can occur at **any** equity level, not just low equity.

Add a **small-account mode**: below a configured equity threshold, cap a position's value to a
configured fraction of equity, in addition to the existing risk-based sizing. This is a
deliberately narrow, equity-gated safety net that catches these edge cases specifically for
smaller accounts, not a complete fix for the general case (which would require changing
`risk_fraction` or `stop_pct` themselves).

**Out of scope:** PDT (already handled unconditionally by `PDTThrottle`, independent of account
size). Limiting concurrent open positions. Any change to `risk_fraction` itself or to the
existing zero-shares hold path in `pipeline.py`. Any change to `backtester.py`/`live_loop.py`
call sites beyond picking up the new defaults.

## Architecture

Extend `PositionSizer` directly — no new file, no new class. Two new optional constructor
params:

```python
def __init__(self, risk_fraction=0.01, small_account_threshold=2000.0,
             small_account_cap_fraction=0.50):
```

`live_loop.py` and `backtester.py` keep constructing `PositionSizer(risk_fraction=0.01)`
unchanged and pick up the new defaults automatically. A caller that wants different values
(e.g. a backtest deliberately simulating a $500 account with a different cap) can override them
explicitly.

## Sizing math

```python
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
```

- Threshold check is strict `<` — exactly `$2,000` equity is **not** small-account mode.
- The cap only ever lowers `shares`, never raises it — it cannot undo the existing "rounds to
  0 shares → hold" path in `pipeline.py`'s `decide_trade`.
- `$2,000` / `50%` were chosen over the alternatives considered (PDT's `$25,000` line — a
  different failure mode, day-trade count, not position-value-vs-equity; and a `90%` cap —
  leaves too little headroom below an all-in bet) as a threshold specific to where the
  value-exceeds-equity failure actually shows up, and a cap that forces real headroom rather
  than a near-full-account single position.

## Known interaction, accepted as-is

`decide_trade` (`pipeline.py:182-186`) applies the Yahoo analyst-consensus multiplier
*after* `shares_to_buy`, and that multiplier can scale shares up to `1.15x`
(`docs/superpowers/specs/2026-08-18-graywind-yahoo-analyst-consensus-design.md`). A position
capped at exactly 50% of equity can end up at up to ~62.5% of equity after the multiplier is
applied, because `round()` on small integer share counts can exceed the raw 1.15x multiplier
(e.g., 4 capped shares → `round(4 * 1.15) = round(4.6) = 5`, a 1.25x scale-up). This design
does not re-clamp post-multiplier — the cap is a coarse safety rail against the "position
worth more than the whole account" failure mode, not a hard guarantee of an exact percentage,
and re-clamping would add a second cap-application site for overshoot. Noted here explicitly
so it isn't mistaken for an oversight later.

## Testing

New cases in `tests/test_position_sizing.py`:
1. Equity just below `$2,000` with a cheap-stock/tight-stop combo whose risk-based share count
   would otherwise be worth more than 50% of equity — confirms the cap binds and lowers `shares`.
2. Equity just below `$2,000` where risk-based sizing is already under the 50% cap — confirms
   the cap doesn't change anything when it doesn't need to.
3. Equity exactly at `$2,000` — confirms the boundary is exclusive (cap does not apply).
4. Equity far above `$2,000` (mirrors existing tests) — confirms no behavior change for the
   accounts this pipeline has actually been tested against.

No changes needed to `tests/test_pipeline.py` or `tests/test_backtester.py` — both exercise
`account_equity` values of `$10,000` or higher, well above the threshold.

## Deferred, not forgotten

- Limiting concurrent open positions for small accounts (considered, not chosen — see Goal).
- Re-clamping position value after the analyst-consensus multiplier (see "Known interaction"
  above).
- Any small-account-specific change to `risk_fraction` itself.
- A value cap keyed to `risk_fraction/stop_pct` (or an unconditional cap) instead of to
  account equity, which would target the actual failure mode identified in the corrected Goal
  section above, rather than gating on account size.
