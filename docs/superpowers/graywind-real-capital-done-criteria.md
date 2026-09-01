# Graywind — Real-Capital Done Criteria

**Date:** 2026-08-31

**Why this doc exists:** the global personal-project workflow (`~/.claude/CLAUDE.md`,
Refine stage) requires 2–3 concrete, project-specific "done" criteria to be written
*before* entering Refine, plus a hardware/vendor-dependency abort-gate check. Neither
existed for Graywind despite ~227 commits. The real-capital readiness audit
(`graywind-real-capital-readiness-handoff.md`, item #2) made writing this the first task,
because without it every remaining item is open-ended polish with no stopping rule.

**Companion doc:** `docs/superpowers/graywind-edge-thesis.md` — what Graywind claims and
how to prove it wrong. Read that first; this doc operationalizes it.

---

## Owner decisions (settled 2026-08-31)

These are the judgment calls the audit refused to invent. They are now decided:

| Question | Decision |
|---|---|
| Real capital at Phase 3 start | **$500** |
| Kill condition | **Graywind loses to SPY buy-and-hold over the burn-in window** |
| Phase-3 advance bar | **Deferred** until ≥20 real trades exist, then set from real data |
| Goal | Positive expected return in the **3–10%** band with bounded drawdown |

### On the $500 figure

$500 sits below both sizing thresholds in `graywind_strategy/risk/position_sizing.py`:
it triggers `low_capital_risk_fraction` (3% per trade, not 1%) and the
`small_account_cap_fraction` 50%-of-equity position cap. This is deliberate and
acceptable — the point of the first real-capital tranche is to exercise the real-money
code path (real fills, real slippage, real tax lots) at an amount that is genuinely
losable, not to generate meaningful returns.

**Implication to keep in view:** at $500 with 70% in a tier-1 SPY core, the tactical
overlay controls ~$150. Conclusions drawn from that overlay's P&L at this size are
directionally weak. Do not treat early real-capital results as a stronger signal than
the paper burn-in they follow.

### On the deferred advance bar

The kill condition is set but the advance bar is not. That asymmetry is intentional and
should be preserved: it means **there is currently exactly one hard gate, and it points
at stopping.** Nothing in this doc authorizes moving to real capital automatically.
Setting the advance bar is itself a required step once burn-in data exists, and it must
be written down here before any real-capital wiring is built.

---

## The burn-in pacing rule (do not misread this)

Per `docs/superpowers/burn-in-decision.md`, burn-in completes at:

> **4 weeks of live paper trading OR 20 real trades — whichever comes LATER.**

**Status as of 2026-08-31:** clock started 2026-08-17. 14 days elapsed. **6 trades
logged** (`git show origin/main:dashboard-data/trade_log.csv`) against the 20-trade
floor. At the observed pace (~6 trades / 14 days), the system lands near ~12 trades by
the 4-week mark of 2026-09-14.

**Therefore burn-in will NOT be complete on 2026-09-14, and that is expected, not a
bug.** It extends until the 20th trade. A future session finding "4 weeks elapsed" must
not declare burn-in complete. Shortening the trade-count bar under calendar pressure is
the single most common way retail systems fool themselves into declaring victory early.

Re-check with:

```
git show origin/main:dashboard-data/trade_log.csv | tail -n +2 | wc -l
```

(Always read `origin/main`, not the local checkout — live cron commits land directly on
`main` and the local copy goes stale within hours.)

---

## Done criteria

Graywind is "done enough" to stop refining and evaluate for Phase 3 when **all three**
hold. These are the stopping rule; meeting them ends Refine, it does not by itself
authorize real capital (see the deferred advance bar above).

### 1. Burn-in is genuinely complete
≥20 real paper trades **and** ≥4 weeks elapsed, with **zero PDT violations** and **zero
unhandled exceptions** across the window. Verified from
`dashboard-data/trade_log.csv` and the absence of any `pipeline-alarm` GitHub issue.

### 2. The overlay has not subtracted value
Realized P&L attributable to tier-2/3 trades over the burn-in window is **≥ 0**, and
total return does not trail SPY buy-and-hold over the same window. This is the
falsification test for Part 1 of the edge thesis, and its failure is the owner-selected
kill condition — not a prompt to tune the gates.

### 3. Risk controls are proven, not just present
The daily drawdown breaker and the rolling (weekly/monthly) breaker have both been
exercised at least once against real cycles, and `MAX_SYMBOLS_PER_SECTOR` has been
enforced with more than two symbols live. A risk control that has never fired is an
untested claim.

---

## Hardware / vendor abort-gate check

Required by the global workflow's Brainstorming gate, applied retroactively here.

**Hardware: clear.** Graywind is pure software — a cron-invoked Python process on GitHub
Actions hitting hosted APIs. There is no local-inference, sensor, or device dependency.
It does not have the failure shape that killed Reign (camera FOV, native sensor access)
or the local-LLM project (8GB RAM ceiling).

**Vendor: NOT clear — this is the live risk.** The system depends on `yfinance` (no SLA,
unofficial, silent schema breaks), Finnhub free tier (rate limits), FRED, and Alpaca.
This is the same *shape* of ceiling as the hardware failures above, just sourced
externally, and it is discovered mid-build rather than scoped up front.

**A full vendor evaluation is audit item #8 and has NOT been written yet** (the session
that wrote this doc had its research tooling unavailable). That evaluation — realistic
failure modes per vendor, which breaks first, paid alternatives and costs — must be
completed and folded into the Phase-3 cost model **before** real capital, not after a
live outage. Treat this gate as open, not cleared.

---

## What this doc does not authorize

- It does not authorize real-capital wiring. No real-money keys exist in this repo today
  and none should be added until the advance bar above is written and met.
- It does not set the advance bar. That is a separate, required decision.
- It does not extend to sizing beyond the first $500 tranche. Scaling is its own decision.

## Related

- `docs/superpowers/graywind-edge-thesis.md` — the claim being tested.
- `docs/superpowers/burn-in-decision.md` — authority on the pacing rule.
- `docs/superpowers/graywind-real-capital-readiness-handoff.md` — the 9-item audit.
