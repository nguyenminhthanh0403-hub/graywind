# Graywind — Tier-1 Exposure-Scaling Falsification Test — Results

**Date:** 2026-09-01. **For:** whoever next considers building live VIX/macro-based
exposure gating for tier 1 (the 70%-of-capital SPY buy-and-hold sleeve). Read this before
re-proposing the idea — it was tested, not just discussed, and it failed its own bar.

## Why this test happened

`docs/superpowers/graywind-edge-thesis.md`'s Part 2 named "extend the VIX/macro gates to
modulate tier-1 exposure" as the only lever that could plausibly deliver the project's
3–10% return goal *including down years*, and specified its own falsification test:
backtest SPY-only 2000-present, buy-and-hold vs. the same holding with exposure scaled
down during high-VIX/macro-stress regimes, compared on drawdown-adjusted return
(Calmar). If the gated variant doesn't improve on that metric, the doc says the
hypothesis is dead and tier-1 should stay passive. This was run as a `superpowers:brainstorming`
spike — a cheap, throwaway probe whose output is an answer, not code kept.

## Method

Data: SPY daily adjusted close (Yahoo Finance chart API, no key needed) and VIX/NFCI/
DGS10/DGS2 (FRED's public `fredgraph.csv`, no key needed), 2000-01-01 to 2026-09-01.

**Known data gap:** `BAMLH0A0HYM2` (the HY OAS series `macro_gate.py` uses live) only has
FRED history from 2023-09-04 forward — confirmed via an explicit `cosd=2000-01-01`
request, which still returns 2023-09-04 as the first row. Likely an ICE Data Indices
licensing change. Dropped from this test's stress signal in favor of NFCI + the 10y-2y
yield curve (both full-history) — not chased further; this was meant to be cheap.

**Stress-day rule:** `VIX ≥ 25.0 OR (NFCI ≥ 0.0 AND curve_slope(10y−2y) < 0.0)`, using
**yesterday's** close (a day's VIX/NFCI/curve close isn't known until after that day's
market close — the same instant SPY's own close is known). The first draft of this
script used same-day values and produced an inflated, fake 14.4% CAGR for the gated
variant by letting it dodge the exact day of every crash — impossible live. Lagging by
one day (mirroring `vix_gate.py`'s own documented anti-lookahead discipline) is what
produces the real numbers below.

**Two exposure rules tested**, both cutting exposure to 50% SPY / 50% uninvested cash
(0% return — conservative, ignores T-bill yield) on a stress day, applied day-by-day,
frictionless (a feasibility probe, not exact live rebalance mechanics):

- **Naive:** de-risk immediately when the lagged stress condition is true.
- **Confirmed (K=3):** asymmetric confirmation-bars filter — same idea as
  `graywind_strategy/volatility.py`'s already-shipped tier-2/3 whipsaw fix. Require the
  raw stress condition for 3 consecutive days before de-risking (slow exit), but return
  to 100% exposure immediately once the raw condition clears (fast re-entry). K=3 chosen
  because it's the same max K already used elsewhere in this codebase — not fit to this
  data.

## Results, full period 2000-01-07 to 2026-09-01

| metric | buy-and-hold | naive-gated | confirmed (K=3) |
|---|---|---|---|
| CAGR | 8.38% | 6.83% | 6.78% |
| Ann. Sharpe | 0.51 | 0.54 | 0.52 |
| Max Drawdown | -55.19% | -46.14% | -48.75% |
| **Calmar (CAGR / \|MDD\|)** | **0.15** | **0.15** | **0.14** |
| De-risked days | — | 19.3% | 16.0% |

Neither variant clears the edge thesis's own bar. The naive rule is a dead wash on
Calmar; the confirmation-bars variant is worse across every metric, not better.

**Per-year breakdown, worst 4 buy-and-hold years:**

| Year | buy-and-hold | naive-gated | confirmed |
|---|---|---|---|
| 2008 | -36.80% | -29.34% | -32.27% |
| 2002 | -21.58% | -17.91% | -17.51% |
| 2022 | -18.18% | -18.30% | -21.39% |
| 2001 | -11.76% | -17.13% | -17.41% |

Not uniformly protective — 2008 and 2002 improved, but 2022 and 2001 got *worse* under
both gated variants.

**The mechanism, not just the outcome:** mean SPY return on days *following* a stress
signal was **+23.6%/yr annualized**, vs **+6.6%/yr** on non-stress days. This signal
design tends to fire right before some of the market's best forward days (a known
vol-spike / mean-reversion effect) — cutting exposure right then gives back the rebound,
which is why both rules bleed CAGR without a matching Calmar improvement. Slowing the
exit down (the K=3 variant) didn't fix this, because the problem isn't reaction speed —
VIX/macro-stress signals at this frequency are closer to *coincident with the bottom*
than *leading* it.

## Conclusion

**Tier-1 gating will not be built on this thread.** Per the edge thesis's own
instruction ("if the test fails, tier-1 should stay a passive core") and the discipline
[[project-graywind-backtest-gate|the DSR gate]] already established elsewhere in this
project — two honestly-designed rules failing is a real answer, and continuing to try
variants until one wins by chance would be exactly the overfitting trap that gate exists
to prevent. If this gets revisited later, it needs a **materially different** mechanism
(a different signal class entirely, not another VIX/macro threshold variant) and should
clear this same Calmar bar before any live code gets written.

## Related

- `docs/superpowers/graywind-edge-thesis.md` — the thesis and falsification test this
  answers.
- `docs/superpowers/graywind-real-capital-readiness-handoff.md` — finding #1, the
  original tier-1-ungated observation this thread traces back to.
- `docs/superpowers/graywind-tier-pool-funding-gap-handoff.md` — the separate, unrelated
  tier-2/3 funding defect worked on the same day; don't conflate the two.
