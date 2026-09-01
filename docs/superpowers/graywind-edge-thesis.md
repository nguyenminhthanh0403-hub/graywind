# Graywind — Edge Thesis

**Date:** 2026-08-31

**Why this doc exists:** the real-capital readiness audit
(`docs/superpowers/graywind-real-capital-readiness-handoff.md`, item #3 in its list)
found that everything shipped so far — VIX gate, sentiment gate, earnings gate, macro
gate, sector gates, DSR overfitting correction, drawdown breaker — is *risk avoidance
and statistical hygiene*. None of it is a source of expected return. Before more
infrastructure gets built, the claim being made has to be written down in a form that
can be proven wrong.

**Owner's stated goal:** Graywind should be consistently profitable in the 3–10% range,
now and going forward.

---

## First, an honest reframing of the goal

No strategy is *always* profitable, and any doc that implies otherwise is lying to its
author. What is achievable, and what "3–10%" should be read as here, is:

> a positive **expected** annual return in the 3–10% band, with drawdowns bounded
> tightly enough that a bad year is a small loss rather than a -20% hole.

The distinction matters because it changes what has to be built. Chasing "never a losing
period" leads to overtrading and curve-fitting. Chasing "positive expectancy, bounded
downside" leads to position sizing and exposure control — which is what this system is
actually made of.

## The structural fact that determines the thesis

Graywind allocates 70/20/10 across tiers (`tier_config.py:TIER_TARGET_WEIGHTS`):

| Tier | Weight | Holding | Gated by the risk stack? |
|---|---|---|---|
| 1 | 70% | SPY buy-and-hold (`TIER1_SYMBOL_WEIGHTS`) | **No** |
| 2 | 20% | Intraday engine (AAPL) | Yes |
| 3 | 10% | Intraday engine (SERV) | Yes |

**Tier 1 is entirely ungated.** `graywind_strategy/tier1_rebalance.py` contains only
`compute_rebalance_orders` and `should_rebalance_this_month` — no VIX check, no macro
check, no sentiment check, no drawdown-breaker check. `run_tier1_rebalance` is called at
`live_loop.py:454` guarded solely by `should_rebalance_this_month`. Every gate in
`pipeline.py::decide_trade` (vix, sentiment, earnings, macro, sector, drawdown, PDT)
applies only to the tier-2/3 intraday path.

The consequence, stated plainly: **the entire risk apparatus protects 30% of the capital
and leaves the 70% that actually drives returns fully exposed.**

## The arithmetic this forces

- **Average SPY year (~10%):** the 70% core contributes ~7% on its own. That already
  lands inside the 3–10% target band without the overlay doing anything.
- **Bad SPY year (-20%):** the 70% core contributes **-14%**. The 30% overlay risks 1–3%
  of equity per trade (`position_sizing.py`), so it cannot plausibly offset a -14% hole.
  The target band breaks, and no amount of tier-2/3 gate tuning fixes it.

So the 3–10% goal is *already met* in normal and good years by the index core alone, and
is *structurally unreachable* in bad years given where the gates currently point.

## The thesis, in two parts

### Part 1 — the thesis Graywind operates under today

**Claim:** Graywind's returns come from the 70% SPY core. Tiers 2/3 are a small,
bounded-risk tactical overlay whose job is *not to subtract* from the core. The edge
being claimed is enforced discipline — fixed-fractional sizing, breakers, PDT
compliance, mechanical entries/exits — producing a return that tracks the index core
without the behavioral leakage of discretionary retail trading.

**This is deliberately a modest claim.** It does not assert alpha over SPY. It asserts
the overlay is not a wealth transfer away from the core.

**Falsification test (the cheap one, runnable at burn-in completion):** compute realized
P&L attributable to tier-2/3 trades over the burn-in window from
`dashboard-data/trade_log.csv`. If that number is **negative**, the overlay is
subtracting and Part 1 is falsified — the correct response is to shrink or remove tiers
2/3, not to tune them.

This is also exactly the kill condition the owner selected (see
`graywind-real-capital-done-criteria.md`): losing to SPY over burn-in means the overlay
destroyed value relative to just holding the core.

### Part 2 — the thesis worth testing next (the actual upgrade path)

**Claim:** extending the *already-built* VIX and macro gates to modulate **tier-1 core
exposure** — not just tier-2/3 entries — is the only lever that could deliver the 3–10%
band *including down years*. Reducing SPY exposure during high-VIX / multi-breach macro
regimes converts the -14% bad-year case into something shallower, at the cost of giving
up some upside in the melt-up years.

**Why this is the right next hypothesis:** it reuses machinery that already exists and is
already live-tested (`evaluate_vix_gate`, `evaluate_macro_gate` in `pipeline.py`), rather
than requiring a new signal to be invented. It also targets the 70% rather than the 30%,
so its effect size can actually move the portfolio number.

**Falsification test:** backtest SPY-only, 2000–present, comparing (a) buy-and-hold
against (b) the same holding with exposure scaled down while the VIX gate is closed or
the macro gate shows ≥2 breaches. If (b) does not improve drawdown-adjusted return versus
(a), the hypothesis is dead and tier-1 should stay a passive core.

**Not yet scoped.** This is named here as the next thing to test, deliberately *not*
implemented as part of the readiness punch list — it is a strategy change and needs its
own spec and plan.

## Status of this doc

Parts 1 and 2 are written as the recommendation of the session that produced this doc,
derived from the code facts above and the owner's stated 3–10% goal. The owner selected
the kill condition and capital figure recorded in
`graywind-real-capital-done-criteria.md`; the two-part thesis framing here is the
analysis, and remains open to the owner's revision.

## Related

- `docs/superpowers/graywind-real-capital-done-criteria.md` — what result advances or
  kills the project, and the burn-in pacing rule.
- `docs/superpowers/burn-in-decision.md` — why the original backtest numbers are
  disqualified as evidence of edge.
- `docs/superpowers/graywind-real-capital-readiness-handoff.md` — the audit that
  required this doc.
