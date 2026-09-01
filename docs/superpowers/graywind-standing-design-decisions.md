# Graywind — Standing Design Decisions

**Date:** 2026-08-31

Two decisions the real-capital readiness audit
(`graywind-real-capital-readiness-handoff.md`) flagged as undocumented defaults rather
than deliberate choices — items #6 (long-only) and #9 (dual paper accounts). Both are
recorded here so they stop being unexamined momentum. Both are recommendations from the
session that wrote this doc, pending the owner's confirmation.

---

## Decision 1 — Graywind is deliberately long-only (audit item #6)

### The current behavior

`PositionSizer.shares_to_buy` (`graywind_strategy/risk/position_sizing.py:41-43`) raises
`ValueError` whenever `stop_price >= entry_price`. `pipeline.py:200-206` treats that case
as an expected fail-to-hold path rather than an error, and `decide_trade` only ever emits
`"buy"`, `"hold"`, or `"blocked"`. There is no short leg anywhere in the system.

### Recommendation: document as deliberate; do not build shorts

This is a **long-only tactical overlay on a buy-and-hold core**, and that is the right
shape for this project. Reasons, in order of weight:

1. **It matches the edge thesis.** Per `graywind-edge-thesis.md`, returns come from the
   70% SPY core; tiers 2/3 exist to not subtract. Shorting is an alpha-seeking activity,
   and the thesis explicitly does not claim alpha.
2. **The defensive lever is exposure, not shorts.** The thesis's Part 2 upgrade path —
   modulating tier-1 exposure via the existing VIX/macro gates — is the correct way to
   handle expected downside. Reducing exposure achieves the defensive goal without borrow
   costs, unlimited-loss risk, or margin mechanics.
3. **$500 makes shorting impractical anyway.** At the agreed first real tranche
   (`graywind-real-capital-done-criteria.md`), short-selling faces margin minimums and
   borrow availability that make it largely unusable.
4. **The gate stack is already long-biased.** The sentiment gate blocks on negative
   sentiment and the earnings gate blocks around events — both are "don't go long into
   this" filters. They would need inverted semantics to inform short entries, which is a
   redesign, not an extension.

### If this is ever revisited

Adding a short leg is **not** a punch-list item. It touches `PositionSizer` (short sizing
math), `decide_trade` (a new action type and inverted gate logic), live order submission
(short-sell and borrow mechanics), and `backtester.py` (short P&L accounting). It would
need its own dated spec under `docs/superpowers/specs/` and its own implementation plan.
Do not let it enter through an incremental change.

### Action taken

Documentation only. No code change — the existing `ValueError` and the `pipeline.py`
guard already encode the behavior correctly; they were simply undocumented as
*intentional*.

---

## Decision 2 — Keep the second paper account, but re-fund it to match the real tranche (audit item #9)

### What the audit worried about

`.github/workflows/live-trading.yml`'s `live-cycle-small` job runs a second paper account
(`ALPACA_API_KEY_SMALL`, `GRAYWIND_STATE_DIR=state/small`,
`GRAYWIND_DASHBOARD_DIR=dashboard-data/small`). The audit read this as scaling
infrastructure horizontally before the core hypothesis had been validated once, and
suggested pausing it.

### What the live numbers actually show

| Account | Equity (2026-08-31) | Sizing regime exercised | Trades logged |
|---|---|---|---|
| Main | ~$100,975 | Standard 1% risk fraction | 6 |
| Small | **exactly $2,000.00** | 3% low-capital risk fraction only | **0** |
| *Planned real tranche* | *$500* | *3% risk fraction **and** 50% position cap* | *—* |

`PositionSizer` thresholds are `low_capital_threshold=5000.0` and
`small_account_threshold=2000.0`, both compared with strict `<`. At exactly $2,000 the
small account is **below** the low-capital threshold (so it gets the 3% risk fraction) but
**not below** the small-account threshold (so the 50% `small_account_cap_fraction`
position cap never applies).

### Recommendation: keep it, and re-fund it below $2,000

Pausing it is the wrong call, but so is leaving it as-is. The reasoning the audit did not
have available:

The owner has now chosen **$500** as the first real-capital tranche. That amount sits
below *both* sizing thresholds. The main account at ~$100k exercises none of that path.
So the small account is the **only** rehearsal available for the exact sizing regime real
money will run under — which makes it validation infrastructure, not premature scaling.

But at exactly $2,000 it is sitting on a boundary and missing half the regime it should be
testing. **Re-fund the small paper account to $500** (matching the planned tranche), so it
exercises the 3% risk fraction *and* the 50% position cap together, on real market data,
before any real money does.

### Caveat that must not be lost

The small account has logged **zero trades in two weeks**. Re-funding it does not
automatically fix that — it may indicate the tier-2/3 signal rarely fires at this account
size, or that pool-equity math yields sub-`MIN_NOTIONAL` sizes that floor to zero shares
(`position_sizing.py:55-56`). **Investigate the zero-trade result before drawing any
conclusion from the re-funded account**, or it will produce another two weeks of silence
that gets misread as "no problems."

### Action required (not yet taken)

Re-funding an Alpaca paper account is done through the Alpaca dashboard, not through this
repo — it is an owner action, not a code change. No workflow edit is recommended; the
`live-cycle-small` job should keep running.

---

## Related

- `docs/superpowers/graywind-edge-thesis.md` — why long-only is consistent with the claim.
- `docs/superpowers/graywind-real-capital-done-criteria.md` — the $500 tranche decision.
