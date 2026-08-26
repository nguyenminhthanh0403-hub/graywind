# Graywind Backtest Gate — Design Spec

**Written:** 2026-08-26 · Sub-project 1 of 3 in the quant-discipline overhaul (see
`docs/superpowers/graywind-quant-discipline-brainstorm-handoff.md`). Sub-projects 2 (quarterly
performance reports) and 3 (personal-use advising UI) are separate, not-yet-brainstormed work —
this spec covers sub-project 1 only.

## Goal

Today, `validate_symbol_addition()` in `graywind_strategy/tier_config.py` only checks market
cap, average volume, and sector concentration before a symbol can be added to
`SYMBOL_TIER`/`TIER1_SYMBOL_WEIGHTS`. It never checks whether `decide_trade` (the intraday
strategy engine) actually performs acceptably on that symbol's own history. The user wants
Graywind held to the backtesting/reporting discipline "every quant community in the world"
uses before a new tier-2/3 symbol goes live — this spec adds a required historical-backtest
gate on top of the existing guardrail, so a symbol can clear market-cap/volume/sector and still
be rejected for backtesting badly.

Research pass (this session, inline — GitHub/Reddit/quant literature, low-effort Chinese-source
check): the two standards that actually matter and aren't already in Graywind are (1) testing
across multiple sequential time periods rather than one static window, since a strategy can look
great in one regime and die in the next, and (2) correcting a raw Sharpe ratio for the fact that
you tried more than one candidate symbol before this one happened to pass — the Deflated Sharpe
Ratio (Bailey & López de Prado). No-lookahead fill timing is **already correct** in
`graywind_strategy/backtester.py` (fills queue to the next bar's open, never the signal bar's
own close) — nothing to change there.

**Explicitly out of scope:**
- **Purged/embargoed k-fold cross-validation.** This fixes label leakage between train/test
  folds for a *fitted* model. `decide_trade`'s RSI(14)/SMA(10/30) thresholds are fixed, not fit
  to data — there's no parameter-fitting step for leakage to corrupt. Including it anyway would
  be applying academic rigor to a problem this codebase doesn't have.
- **True walk-forward re-optimization.** Same reasoning — walk-forward's classic form
  re-optimizes strategy parameters per fold. Section 3 below implements a **regime-robustness
  check** (same sequential-fold structure, no re-optimization) instead, and that's a deliberate
  scope decision, not a shortcut.
- Sub-projects 2 (quarterly reports) and 3 (advising UI) — separate specs, later.
- Retroactively re-validating `AAPL`/`SERV`, already live — this gate applies to *future*
  additions only. (The separate AAPL/SERV backtest sanity-check thread, blocked on the user
  running `scripts/fetch_serv_bars.py` themselves, is unrelated pre-existing work, not part of
  this spec.)

## Architecture

New module `graywind_strategy/backtest_gate.py` — kept separate from `tier_config.py`, which
stays scoped to tagging and the market-cap/volume/sector guardrail. `validate_symbol_addition()`
calls the new gate **last**, after the existing cheap checks, so a symbol that already fails on
market cap never triggers an expensive backtest fetch-and-run.

```python
# tier_config.py
def validate_symbol_addition(symbol, tier, finnhub_api_key, data_client, sector, ...):
    market_cap = fetch_market_cap(...)
    ...                                    # existing checks, unchanged
    check_guardrail(...)
    backtest_gate.validate_symbol_backtest(symbol, tier, data_client)   # new, last
```

`backtest_gate.py` owns: historical-data fetch/floor enforcement, the fold split, the
Deflated Sharpe Ratio calculation, the trial-count log, and threshold checks. It calls
`graywind_strategy.backtester.run_backtest()` per fold rather than reimplementing any
backtesting logic.

## Data window and floor

Fetch the maximum 15-minute-bar history the IEX free feed returns for the candidate symbol —
call `fetch_bars(data_client, symbol, start, end)` with `start` set far enough back (e.g. 10
years) that the feed's own limit, not an assumption in this code, determines how much comes
back. **Enforce a floor, don't assume one was met:** if the fetch returns fewer than 2 years of
bars *or* fewer than 300 total trades once folded and backtested, raise `GuardrailViolation`
citing which floor was missed, rather than backtesting on however little data showed up. This
matches the research's stated minimum for a sample that plausibly spans multiple market
regimes.

## Regime-robustness check (fold structure)

Split the fetched bar history into **4 sequential, non-overlapping folds** (~6 months each,
adjusted evenly if the total isn't exactly divisible). Run `run_backtest()` independently on
each fold — each fold restarts its own equity curve from `starting_equity`, exactly like
`run_sector_backtest.py`'s existing per-symbol pattern, so folds are apples-to-apples and one
fold's drawdown can't mask another's.

**Every fold must individually clear all four thresholds below** — not an average across folds.
A symbol that crushes fold 1 (bull run) and fails fold 3 (chop) is rejected; averaging would
hide exactly the regime-fragility this check exists to catch.

| Metric | Threshold | Source |
|---|---|---|
| Sharpe ratio (annualized, `PERIODS_PER_YEAR_15MIN`) | ≥ 1.0 | existing `backtester.sharpe_ratio` |
| Max drawdown | ≤ 25% | existing `backtester.max_drawdown` |
| Win rate | ≥ 45% | existing `backtester.win_rate` |
| Trade count | ≥ 30 per fold | `len(result.trades)` |

## Deflated Sharpe Ratio (anti-cherry-picking check)

The 4 fold results aren't stitched together into one curve (each fold restarts its own equity),
so this needs its own, fifth `run_backtest()` call over the **entire fetched window
unfolded** — a check on the overall result's statistical significance, not a per-fold check.

`deflated_sharpe_ratio(sharpe, n_trials, n_returns, skew, kurtosis)` — closed-form correction
from Bailey & López de Prado ("The Deflated Sharpe Ratio," 2014): given the raw Sharpe, the
number of prior trials (candidate symbols already run through this gate), the sample length,
and the return distribution's skew/kurtosis, it computes the probability the *true* Sharpe
exceeds zero after accounting for the fact that the best of N trials looks better than any one
trial would by chance. **Require DSR ≥ 0.95.**

**Trial counter:** every symbol run through this gate — pass or fail — appends a row to a
committed log, `graywind_strategy/backtest_gate_trials.json` (symbol, tier, timestamp,
pass/fail, raw Sharpe). `n_trials` for a new candidate is the count of prior rows plus one (for
itself). **The counter never resets** — confirmed with the user: erring toward a stricter bar
over time is the safe default, since the failure mode of "too strict" is a rejected mediocre
symbol, while the failure mode of "resets and gets lax" is a bad symbol going live with real
money.

## Error handling

- Every rejection path raises `GuardrailViolation` (the existing exception type in
  `tier_config.py`, reused rather than introducing a second exception class) with a message
  naming the exact check and number that failed: which fold, which metric, or "DSR N.NN below
  0.95 threshold with N_TRIALS prior candidates."
- Fetch failures (no bars returned, feed error) fail closed — raise, don't silently proceed
  with less data than the floor requires. Same "a guardrail that fails open on missing data
  isn't a guardrail" principle the existing market-cap check already follows.
- The trial-count log is append-only; a write failure (e.g. disk/permissions) should raise
  rather than silently skip logging the trial — an unlogged trial would let a future DSR
  calculation undercount N and pass a symbol it shouldn't.

## Testing

TDD, per this project's existing convention for `backtester.py`/`pipeline.py`/`gates/`/etc.
All fixtures are synthetic price series, not real market data — deterministic and fast:

- **Floor enforcement:** a fetch returning < 2 years of bars, and one returning ≥ 2 years but
  < 300 total trades once backtested, both raise with the right message.
- **Fold logic:** a symbol with a synthetic series that clears every fold passes; one that
  clears 3 of 4 folds (fails only fold 3) is rejected, with fold 3 named in the error.
- **Per-metric fold failures:** one synthetic case per threshold (Sharpe, drawdown, win rate,
  trade count) failing in isolation, to confirm each is actually checked independently.
- **DSR:** unit tests on `deflated_sharpe_ratio()` directly — monotonic behavior (same raw
  Sharpe + more trials → lower DSR), and an end-to-end case where a symbol clears every fold but
  is rejected because a high trial count drops its DSR below 0.95.
- **Trial log:** appending a new trial doesn't corrupt or truncate prior rows; a symbol that
  fails is still logged (so a later, easier symbol doesn't benefit from an undercounted N).
- Mocking style matches `earnings_gate.py`'s existing tests (mock `data_client`/fetch calls,
  not real API calls).

## Deferred, not forgotten

- Purged/embargoed k-fold CV — explicitly excluded, see Goal section (no fitted-parameter
  leakage to purge).
- True walk-forward re-optimization — explicitly excluded, same section (no parameters to
  re-optimize).
- Sub-project 2 (quarterly performance reports) and sub-project 3 (personal-use advising UI) —
  separate future specs.
- Retroactive backtest-gate validation of `AAPL`/`SERV` — this gate governs future additions
  only; the two live symbols were added under the pre-existing market-cap/volume/sector-only
  guardrail.
