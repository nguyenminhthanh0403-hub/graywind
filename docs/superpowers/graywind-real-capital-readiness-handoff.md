# Graywind — Real-Capital Readiness Audit — Session Handoff

**Written:** 2026-08-31 · **For:** whoever picks up Graywind next, to work through the fix
list below before real capital is ever put behind this system.

## STATUS UPDATE — 2026-08-31 (later session)

Most of this punch list has since been worked. **Read this block before re-doing
anything below.** The fix list further down is preserved as originally written; this
block is the current state.

| Item | Status | Where |
|---|---|---|
| #1 burn-in pacing | Recorded, no action needed | `graywind-real-capital-done-criteria.md` |
| #2 done-criteria doc | **Written** ($500 tranche, kill-on-losing-to-SPY, advance bar deliberately deferred) | `graywind-real-capital-done-criteria.md` |
| #3 edge thesis | **Written** — see the tier-1 finding below | `graywind-edge-thesis.md` |
| #4 diversify universe | **Not started** (correctly still gated behind #5) | — |
| #5 rolling drawdown breaker | **Implemented + tested**, not yet committed/pushed | `risk/drawdown_breaker.py` |
| #6 long-only decision | **Decided:** deliberate, documented, no code change | `graywind-standing-design-decisions.md` |
| #7 LLM promotion bar | **Written** — plus two blockers found | `graywind-news-debate-promotion-bar.md` |
| #8 data-vendor ceiling | **STILL OPEN** — not written | — |
| #9 dual-account | **Decided:** keep it, re-fund to $500 (owner action) | `graywind-standing-design-decisions.md` |

**Three findings worth carrying forward:**

1. **Tier 1 (70% of capital) is completely ungated.** `tier1_rebalance.py` has no VIX,
   macro, sentiment, or drawdown-breaker check; `run_tier1_rebalance` is guarded only by
   `should_rebalance_this_month`. Every gate in `decide_trade` protects only the 30% in
   tiers 2/3. This reframes what the gate stack can and cannot do for returns, and is the
   basis of the edge thesis doc.
2. **The news-debate shadow gate has logged nothing since it shipped 2026-08-28.**
   `dashboard-data/news_debate_log.csv` does not exist in `origin/main`. The
   `ANTHROPIC_API_KEY` secret is almost certainly unset — it expands to `""`, and
   `live_loop.py`'s `os.environ.get` treats that as "skip", silently. No calibration data
   is accumulating.
3. **The small paper account sits at exactly $2,000.00**, the `small_account_threshold`
   boundary, so it exercises the 3% low-capital risk fraction but *not* the 50% position
   cap. It has also logged zero trades in two weeks.

## Goal

Graywind's owner has now explicitly confirmed: **Graywind is a bid to eventually deploy
real capital**, not a learning-only exercise. That answer resolves a question this audit
raised (see "What has changed" below) and makes several previously-optional fixes
mandatory gates rather than nice-to-haves.

This handoff is the output of a two-part review conducted in conversation (not from a
written spec/plan — none exists yet for this audit):
1. A financial-advisor/broker/trader review of the **strategy and risk-management
   flaws**.
2. A tech-operator/capital-allocator review of the **development-process flaws**
   (scope, sequencing, moat, infra risk).

No formal plan or progress ledger exists for this work yet. **This document is the
source of truth for the fix list** until someone writes a proper plan (via
`superpowers:writing-plans`) for the first item below. Related prior docs:
- `docs/superpowers/burn-in-decision.md` — defines the paper-trading burn-in gate this
  audit's #1 item depends on.
- `docs/superpowers/graywind-phase1-mvp-handoff.md` — original Phase 1 context.
- `~/.claude/CLAUDE.md` (global, not in this repo) — the user's personal-project
  workflow, whose Refine "done criteria" and hardware/vendor abort-gate requirements
  are directly invoked by items #2 and #9 below.

## How to resume (do this first)

1. Confirm you're on `main`, no base branch — this audit isn't implemented as a branch,
   it's a punch list against the live system. Run `git log -3 --oneline` to see where
   `main` actually is.
2. Re-read `docs/superpowers/burn-in-decision.md` in full — it is the authority on why
   the burn-in clock exists and what disqualifies the original backtest numbers.
3. Check current trade count and pacing before doing anything else (see "Immediate next
   action").
4. **Immediate next action:** run `wc -l dashboard-data/trade_log.csv` and compare
   against the pacing math in item #1 below. If the live system is still on pace to fall
   short of 20 trades by 2026-09-14, that is expected and is *not* a bug — do not let
   anyone (including a future automated session) treat 2026-09-14 as a hard burn-in-complete
   date. The gate is "4 weeks **or** 20 trades, whichever is *later*."

## Current state (active files)

**Branch:** `main`, at commit `1f82cba` as of this writing (2026-08-27 commit, though
live-trading cron commits land on `main` directly every market cycle — check
`git log -1` for the actual current tip before trusting anything below as current).

**Live system status confirmed by this audit (as of 2026-08-31):**
- Alpaca **paper** account only — no real-capital wiring exists anywhere in the repo.
  `.github/workflows/live-trading.yml` reads `ALPACA_API_KEY`/`ALPACA_API_SECRET` (main
  account) and `ALPACA_API_KEY_SMALL`/`ALPACA_API_SECRET_SMALL` (second paper account) —
  both are paper keys per `.env.example` and the burn-in doc.
- Burn-in clock started 2026-08-17. As of 2026-08-31: 14 days elapsed, 14 days remaining
  to the 4-week mark (2026-09-14), **6 trades** logged in `dashboard-data/trade_log.csv`
  against a 20-trade floor. At the observed pace (~6 trades / 14 days), the system will
  land around ~12 trades by 2026-09-14 — short of 20. **This means burn-in should extend
  past 2026-09-14**, not stop there. Do not treat the calendar date alone as sufficient.
- Live universe: only `AAPL` (tier 2) and `SERV` (tier 3) actively traded
  (`graywind_strategy/tier_config.py:SYMBOL_TIER`), `SPY` buy-and-hold for tier 1. A
  broader roster (`NVDA`, `MSFT`, `XOM`, `CVX`, `JNJ`, `UNH`) is tagged in
  `graywind_strategy/sector_config.py:SYMBOL_SECTOR` but **not yet added** to
  `SYMBOL_TIER` — promotion requires running `validate_symbol_addition()` per symbol
  (see `tier_config.py` docstring).
- Equity curve: ~$100,000 → ~$100,975 over the burn-in window so far (see
  `dashboard-data/equity_curve.csv`). Not statistically meaningful at this sample size —
  do not read directional signal into it either way.

**Scratch workspace / traps:**
- ⚠️ Several **other in-flight work threads exist in this repo right now that are not
  part of this audit** — do not touch them as part of working this list:
  - `git status` shows a modified (tracked) `graywind-news-debate-shadow-mode-handoff.md`
    and untracked `graywind-news-debate-provider-cost-handoff.md`,
    `graywind-performance-reports-handoff.md`, and `scripts/fetch_serv_bars.py`.
  - Two other worktrees exist: `.claude/worktrees/agent-ac1e2a7ec9b70e6e3` (locked) and
    `.claude/worktrees/graywind-yahoo-analyst-consensus`. Both are separate, unrelated
    efforts — leave alone.
  - These are normal signs of parallel work in this repo, not evidence anything is
    broken. Just don't attribute them to this handoff or assume they're stale.

**Not mine — leave alone:** everything under `.venv/`, `__pycache__/`, `alpaca_data/`,
`.pytest_cache/` — build/data artifacts, not source.

## What has changed

Nothing has been implemented yet — this session was pure review/audit (grounded by
reading the actual repo state: workflows, gates, risk modules, commit history, trade
log) plus one explicit decision from the project owner:

- **Decision, now settled:** Graywind's purpose is real-capital deployment, not a
  learning-only exercise. This resolves the "which game are you playing" question the
  tech-operator review raised, and makes items #2 and #3 below non-optional.

## What has failed / risks / caveats

**Nothing has failed** — the live paper system is running correctly (cron confirmed
firing through 2026-08-31, `pipeline-alarm` GitHub-issue alerting already correctly
wired for cron/API failures — this was checked and does **not** need fixing).

**UNVERIFIED / not yet done — this is the actual fix list**, ordered by what should be
tackled first. Items 1–3 are prerequisites that inform how items 4–9 should be scoped, so
resist the urge to jump straight to engineering work before they're settled:

1. **Burn-in pacing.** Already covered above — extend the burn-in clock past
   2026-09-14 if the 20-trade floor isn't met by then. Do not shorten the trade-count
   bar under calendar pressure; that is the single most common way retail systems fool
   themselves into declaring victory early.

2. **Write the missing "done criteria" doc.** The user's own global workflow
   (`~/.claude/CLAUDE.md`, Refine stage) requires 2-3 concrete, project-specific "done"
   criteria be written *before* entering Refine — and separately requires a hardware/
   vendor-dependency abort-gate check. Neither exists for Graywind despite 227 commits /
   18 days of work. Now that real-capital deployment is the confirmed goal, this doc
   should specifically define: what burn-in result would justify moving to Phase 3 (real
   capital), what amount of capital, and what result would trigger killing the project
   instead. Write this before doing more feature work — it's what makes items 4-9 below
   prioritizable instead of open-ended polish.

3. **Write down the actual edge thesis.** Everything shipped so far (VIX gate,
   sentiment gate, earnings gate, DSR overfitting correction, drawdown breaker) is risk
   avoidance and statistical hygiene — none of it is a source of expected return. Before
   more infrastructure work, write a specific, falsifiable hypothesis for *why* Graywind
   should beat buy-and-hold SPY, and design the fastest test of that hypothesis. If no
   such hypothesis can be articulated, that's itself the most important finding of this
   audit and should change what "Phase 2" means.

4. **Diversify the live universe.** Only 2 active symbols (`AAPL`, `SERV`) is
   concentration risk, not a portfolio. Run `validate_symbol_addition()` (already built,
   in `tier_config.py`) against `NVDA`, `MSFT`, `XOM`, `CVX`, `JNJ`, `UNH` and promote the
   ones that clear the guardrail onto `SYMBOL_TIER`. Do this only after #2/#3 are
   settled — adding symbols before defining what "done" and "edge" mean just adds more
   unexplained trades to the burn-in log.

5. **Add a rolling drawdown breaker above the daily one.** `DrawdownBreaker` in
   `graywind_strategy/risk/drawdown_breaker.py` only halts new trades for the rest of
   the *current day* at a 2% loss. There is no weekly/monthly/strategy-level max
   drawdown breaker, and no portfolio-level correlation check across simultaneous
   tier-2/3 positions (the `MAX_SYMBOLS_PER_SECTOR = 3` cap in `tier_config.py` is real
   but untested with only 2 live symbols). Add before diversifying the universe (item
   #4), since concentration/correlation risk gets worse, not better, as more symbols go
   live.

6. **Decide the long-only question explicitly.** `PositionSizer.shares_to_buy` in
   `graywind_strategy/risk/position_sizing.py` hard-rejects any stop-at-or-above-entry
   setup — there is no short leg. Either document this as a deliberate long-only
   tactical overlay on a buy-and-hold core (a legitimate design), or scope in a hedge/
   short capability before real capital, so it isn't an undocumented directional bet on
   the market.

7. **Write the LLM shadow-to-authoritative promotion bar now, before it's needed.**
   `graywind_strategy/gates/news_debate.py` is correctly isolated in shadow mode today —
   it has no code path into `pipeline.py::decide_trade()`. But there's no written
   calibration criterion for *when* it would ever be promoted to gate real trades.
   Define the metric now (e.g., "debate verdict must beat VADER `sentiment_gate`'s
   realized P&L by margin X over N shadow-logged trades") while there's no deadline
   pressure to define it under.

8. **Evaluate the data-vendor ceiling before it becomes load-bearing.** `yfinance`,
   Finnhub free tier, and FRED (see `requirements.txt`, `.env.example`) are fine for
   paper trading but carry silent schema breaks, rate limits, and no SLA — this is the
   same shape of failure that killed the Reign and local-LLM projects (a hardware/vendor
   ceiling discovered mid-build instead of scoped up front). Evaluate paid/licensed data
   options as part of the Phase 3 real-capital plan, not after a live outage.

9. **Reconsider running two paper accounts before the first has proven anything.**
   `live-trading.yml`'s `live-cycle-small` job (using `ALPACA_API_KEY_SMALL`) scales
   infrastructure horizontally before the core hypothesis (item #3) has been validated
   even once on the main account. Low cost since both are paper, but worth a deliberate
   decision rather than default momentum — pause the second account until the main
   account clears burn-in with an actual edge signal, or document why running both in
   parallel is intentional.

## What's next (ordered)

1. Write the "done criteria" doc (item #2) — this is the actual first step; it makes
   every other item below prioritizable instead of open-ended. Use
   `superpowers:writing-plans` if it grows beyond a short doc.
2. Write the edge-thesis doc (item #3) alongside it — these two belong together since
   the done-criteria doc should reference what result would validate the thesis.
3. Let the burn-in clock keep running per item #1's pacing correction — no action
   needed here beyond not declaring it complete early.
4. Once #1/#2 are written: tackle #5 (rolling drawdown breaker) before #4
   (diversification), since risk controls should exist before the universe that needs
   them grows.
5. #6 (long-only decision), #7 (LLM promotion bar), #8 (data vendor), #9 (dual-account
   sequencing) can be done in any order once the above are settled — none are blocking
   the burn-in itself, but all should be resolved before Phase 3 (real capital) begins.

## Verification idioms used in this project (for the resuming session)

- Test suite: `pytest` from repo root (5,353 lines of tests vs. 2,134 lines of strategy
  code — TDD is enforced here, don't skip it for these fixes).
- Live state: `dashboard-data/trade_log.csv` and `dashboard-data/equity_curve.csv` are
  the ground truth for what's actually happened — always prefer `git show
  origin/main:dashboard-data/equity_curve.csv` over the local checkout, which is
  frequently stale relative to the live cron.
- Cron/pipeline health: check for an open GitHub issue labeled `pipeline-alarm` — its
  presence means the live cycle is currently failing; absence means it's healthy (this
  mechanism is already built and confirmed working, see `.github/workflows/
  live-trading.yml`).
