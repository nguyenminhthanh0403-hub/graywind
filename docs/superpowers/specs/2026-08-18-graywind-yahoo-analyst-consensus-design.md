# Graywind Yahoo Analyst-Consensus Position-Sizer — Design

**Date:** 2026-08-18
**Status:** approved, not yet implemented
**Prior art:** `graywind_strategy/gates/{vix,macro,earnings,sentiment,sector}_gate*.py` and
their `evaluate_*_gate` wrappers in `pipeline.py` (the existing gate pattern this design
partially follows and partially departs from). Full source-list decision history: memory
`project-graywind-analysis-sources.md`.

## Goal

Add Yahoo Finance analyst consensus (recommendation trend + analyst price target) as a signal
into Graywind's live-trading pipeline — the first of three tracks decomposed out of the
"professional analysis sources" brainstorm (Reddit and YouTube are separate, unstarted specs).

Unlike the five existing gates, this is **not a blocking pass/fail check**. It's a **continuous
position-size multiplier**: strong analyst consensus scales a trade's share count up, weak or
negative consensus scales it down. No existing mechanism in this pipeline does this — the five
gates only ever block or allow.

**Out of scope:** Reddit, YouTube, any other data source. Stop/target-price adjustment (only
position size is affected). Any change to the five existing boolean gates' behavior.

## Architecture

New module **`graywind_strategy/gates/analyst_consensus.py`** (kept in the existing `gates/`
directory for consistency with the other signal-source modules, even though it doesn't block):

- `fetch_analyst_consensus(symbol) -> (recommendation_mean: float, target_mean: float)` — uses
  `yfinance.Ticker(symbol).info`, reading `recommendationMean` and `targetMeanPrice`. Missing/
  `None` fields or any fetch exception raise `AnalystDataUnavailable`.
- `analyst_consensus_multiplier(recommendation_mean, target_mean, current_price) -> float` —
  pure scoring logic (below), no I/O.
- `AnalystDataUnavailable(Exception)`.

New wrapper in `pipeline.py`, **`evaluate_analyst_consensus_multiplier`** — following the same
`fetch_X` / pure-logic / `evaluate_X` three-layer split as the other gates, but returning
`float` instead of `bool`, and reading/writing the cache described below.

New dependency: **`yfinance`** — not currently in `requirements.txt`; verified live against
`yfinance==1.6.0` that `Ticker("AAPL").info` returns `recommendationMean`, `targetMeanPrice`,
and related analyst fields as expected (recommendationMean=2.087, targetMeanPrice=325.70 for
AAPL at verification time) — add to `requirements.txt` as part of implementation.

## Scoring

Two independent, bounded sub-multipliers, averaged:

```
multiplier_rec    = 1.15 - 0.075 * (clamp(recommendation_mean, 1, 5) - 1)
                     # Strong Buy (1.0) = 1.15x, Hold (3.0) = 1.00x, Strong Sell (5.0) = 0.85x
                     # clamped defensively: Yahoo documents this as a 1-5 scale but doesn't
                     # guarantee it in the response, same defensive posture as the target clamp

multiplier_target  = 1.0 + clamp((target_mean - current_price) / current_price, -0.15, 0.15)
                     # capped at +/-15% analyst-price-target upside/downside

multiplier = (multiplier_rec + multiplier_target) / 2
                     # naturally bounded to [0.85, 1.15]; no extra clamp needed
```

Each half is independently testable and independently legible in a trade log (a resuming
session or the user reading `state/analyst_consensus.csv` can tell which half drove a given
multiplier). This was chosen over a single combined weighted formula for that legibility, and
over dropping the price target entirely (which would have contradicted the already-scoped goal
of using both signals).

## Caching

`state/analyst_consensus.csv`, columns: `symbol,date,recommendation_mean,target_mean,multiplier`.

Before fetching for a symbol on a given `as_of_date`, check for an existing `(symbol, date)`
row; if present, reuse its `multiplier`. If absent, fetch via `fetch_analyst_consensus`,
compute the multiplier, append the row, and write. A missing file or a malformed row is treated
as a cache miss (re-fetch), never a crash.

**Why this must be a persisted file, not an in-memory cache:** `.github/workflows/
live-trading.yml` runs every ~15-minute live cycle as a **fresh GitHub Actions process**
(checkout → install deps → run `live_loop.py` → exit) — there is no long-lived daemon to hold
state in memory across cycles. `state/analyst_consensus.csv` follows the exact precedent of
`state/operational.csv` and `state/positions.csv`, both committed by the workflow's existing
`git add -A state` step — no workflow changes needed, the file just needs to exist under
`state/` to be picked up.

**Why cache at all:** analyst consensus doesn't move intraday; fetching it on every ~15-minute
cycle across a whole watchlist would be unnecessary load against `yfinance`'s unofficial
endpoint, risking a rate-limit/block that would degrade every other symbol's evaluation too.

## Wiring into `pipeline.py`

Applied immediately after the existing sizing call in `decide_trade`, before the existing
zero-shares hold-check:

```python
shares = position_sizer.shares_to_buy(account_equity, current_price, stop_price)
shares = round(shares * evaluate_analyst_consensus_multiplier(
    symbol=symbol, as_of_date=as_of_date, current_price=current_price))
if shares <= 0:
    return TradeDecision(action="hold", reason="position size rounds to zero shares")
```

`gates_always_pass=True` (the existing flag that bypasses the five blocking gates for
synthetic/testing runs) does **not** bypass this multiplier — decided explicitly: that flag is
documented specifically as skipping *blocking* gates, and this isn't one. A caller wanting
"raw" unaugmented sizing for a test would need to mock `evaluate_analyst_consensus_multiplier`
directly, the same way a test today would mock any other `evaluate_*` wrapper it wants inert.

## Error Handling

- `fetch_analyst_consensus` raises `AnalystDataUnavailable` on any fetch failure or missing/
  `None` field — mirrors the other gates' `fetch_X` contract.
- `evaluate_analyst_consensus_multiplier` catches `AnalystDataUnavailable` from a fresh fetch
  (cache-miss path only; a cache hit never calls the fetcher) and returns `1.0` — neutral, no
  adjustment. The trade proceeds exactly as if this source didn't exist. This is a deliberate
  departure from the other five gates' fail-**closed** contract: a multiplier has no natural
  "block" value, and defaulting to neutral rather than to a punitive multiplier (e.g. treating
  fetch failure as `0.85x`) avoids letting a data outage masquerade as a real bearish signal.

**Look-ahead-bias guard (caught in spec self-review):** `yfinance`'s `.info` has no historical
point-in-time query — it only ever returns *today's* live analyst consensus, unlike
`sentiment_gate.py`'s `as_of`-windowed news query or `earnings_gate.py`'s calendar-based
lookahead. Since `decide_trade` is the single path both `live_loop.py` and `backtester.py`
call, naively fetching on every call would leak today's analyst opinions into historical
backtest decisions. **`evaluate_analyst_consensus_multiplier` therefore only fetches/applies
the multiplier when `as_of_date == date.today()`** (the live case); for any other
`as_of_date` (the backtest case), it returns `1.0` immediately, without calling the fetcher or
touching the cache. This is an honest limitation, not a workaround: no free historical
analyst-consensus source exists, so a real trader couldn't have this signal for a past date
either.

## Testing

New `tests/test_analyst_consensus.py`, mirroring `test_earnings_gate.py`'s shape:
1. `analyst_consensus_multiplier` boundary values: Strong Buy (1.0) and Strong Sell (5.0)
   recommendation endpoints; price-target upside/downside beyond +/-15% clamps correctly;
   Hold (3.0) + 0% upside = exactly `1.0`.
2. `fetch_analyst_consensus` raises `AnalystDataUnavailable` on a mocked fetch exception and on
   a mocked response missing `recommendationMean`/`targetMeanPrice`.
3. Cache behavior: cache hit reuses the stored multiplier without calling the fetcher; cache
   miss fetches, computes, and appends a new row; a malformed/missing CSV is treated as a miss,
   not a crash.

4. `as_of_date != date.today()` → `evaluate_analyst_consensus_multiplier` returns `1.0`
   without calling `fetch_analyst_consensus` or touching the cache (the look-ahead-bias guard).

Extend `tests/test_pipeline.py`'s existing `decide_trade` tests with one new case confirming
the multiplier is applied to `shares` on a live (`as_of_date == today`) call, and one
confirming it still applies under `gates_always_pass=True`.

`test_backtester.py` needs one new case confirming a historical backtest run gets neutral
(`1.0`) multipliers throughout — i.e. that the look-ahead-bias guard actually holds end-to-end
through the real backtester call path, not just at the unit level.

## Deferred, not forgotten

- Reddit and YouTube tracks — separate, unstarted brainstorm → spec → plan cycles.
- Any interaction between this multiplier and the existing five gates beyond simple ordering
  (e.g. whether a very bearish consensus should ever escalate to a full block rather than just
  shrinking size) — not raised during brainstorming, not in scope here.
