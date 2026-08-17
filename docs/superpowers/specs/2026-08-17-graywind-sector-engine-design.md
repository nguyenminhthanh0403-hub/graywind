# Graywind Sector-Aware Strategy Engine — Design

**Date:** 2026-08-17
**Status:** approved, not yet implemented
**Prior art:** `docs/superpowers/specs/2026-08-13-graywind-phase1-mvp-design.md` (the
RSI/SMA engine and `decide_trade`/backtester this design extends), `docs/superpowers/graywind-sector-engine-design-handoff.md` and `docs/superpowers/graywind-sector-model-handoff.md` (the two prior sessions that produced the root-cause analysis and architecture choice below).

## Goal

Graywind's fixed RSI(14)+SMA(10/30) crossover behaves worse on some symbols than others.
A root-cause analysis (see "Root cause" below) found this isn't sector-specific broken
logic — it's a general whipsaw problem in the signal that shows up more often on
higher-volatility symbols. This design adds a volatility-scaled confirmation-bars filter to
retune the existing signal, plus a small roster expansion, without rebuilding signal logic
per sector.

## Root cause (from the prior brainstorming session, included for context)

A hold-time breakdown of round-trip trades on XLK and AAPL, using the fixed backtester
against `data/sector/xlk.csv` / `alpaca_data/aapl.csv`:

| | XLK <1 day hold | XLK ≥1 day hold | AAPL <1 day hold | AAPL ≥1 day hold |
|---|---|---|---|---|
| Trades | 14 | 27 | 4 | 28 |
| Win rate | 21% | 56% | 25% | 57% |
| Avg P&L | -1.21% | +0.82% | -1.54% | +0.97% |

The failure signature (short-hold trades lose, long-hold trades win) is nearly identical on
both symbols. The actual sector difference is that XLK generates proportionally more
short-hold (whipsaw) entries — 34% of its trades vs. 13% for AAPL — because its higher
short-term volatility trips the crossover threshold prematurely more often. **Conclusion:
retune via volatility-scaled thresholds, not rebuild signal logic per sector.**

## Architecture

One parametrized engine, not N per-sector files. Two new modules:

- **`graywind_strategy/sector_config.py`** — a static `SYMBOL_SECTOR: dict[str, str]`
  mapping (symbol → sector tag) plus a reverse lookup. Sector tags exist for **future**
  non-volatility caveats (e.g. an energy oil-price gate, a tech earnings-surprise gate) —
  they are not consumed by anything in this design. This module is scaffolding for
  later work, not wired into the confirmation-bars calculation.
- **`graywind_strategy/volatility.py`** — computes each symbol's confirmation-bars count
  `K` from its own trailing volatility. No dependency on `sector_config.py`.

Roster expansion (locked in): add energy (XOM, CVX), tech (NVDA, MSFT), and health
(JNJ, UNH) alongside the existing AAPL/SPY — six new symbols, three new sectors, two per
sector.

## Data Flow

**`compute_atr_pct(df, period=14)`** in `volatility.py` computes ATR(14) as a % of close
price via `pandas_ta_classic`'s existing `.ta.atr()` accessor (same library already used for
RSI/SMA in `strategy_engine.py`). Trailing/causal by construction — bar *i* only ever
depends on bars ≤ *i*.

**`confirmation_bars_series(df, atr_period=14, percentile_window=260)`** ranks each bar's
ATR% against that *same symbol's own* trailing 260-bar window (~10 trading days at 26
15-minute bars/day) and buckets by percentile: bottom third → K=1, middle third → K=2, top
third → K=3. Self-relative rather than fixed absolute cutoffs, so it needs no per-symbol
tuning and treats a volatile tech name and a sleepy ETF consistently. Bars without enough
history for the ATR period or the percentile window default to K=1 (today's unfiltered
behavior) — safe, since `compute_signals` already returns "hold" for insufficient-history
bars regardless of K.

**`strategy_engine.compute_signals(df, ..., confirmation_bars=None)`** gets a new optional
parameter accepting `None` (back-compat — existing behavior and existing tests unchanged), a
plain int (fixed K, useful for simple tests), or a per-bar `Series` (the real path).
Internally: split the existing single crossover condition into `buy_condition`/
`sell_condition` booleans, precompute vectorized rolling-window mins for K∈{1,2,3} on each
condition (`rolling(k).min()`), then per-bar select the column matching that bar's own K. A
"buy" fires only if its condition held true for all of the last K_i bars ending at bar i —
still zero lookahead, since that window is entirely ≤ i.

**Call sites** (both need the same change): `backtester.py`'s `signals_by_symbol`
comprehension and `live_loop.py`'s per-symbol `compute_signals(df)` call each become
`compute_signals(df, confirmation_bars=volatility.confirmation_bars_series(df))`.

**Correction from the prior handoff:** `pipeline.py`'s `decide_trade()` only ever consumes
an already-computed `signal` string — it never touches RSI/SMA thresholds directly. The
confirmation-bars filter lives entirely in `compute_signals()`; `decide_trade()` and
`pipeline.py` do not need to change.

## Error Handling

- **NaN/insufficient-warmup bars** — use `rolling(window, min_periods=window).rank(pct=True)`
  rather than a hand-rolled loop, so NaNs during warm-up propagate naturally. Any bar with a
  `NaN` percentile rank falls back to K=1 — consistent with `compute_signals` already
  treating early bars as "hold" regardless of K, so this fallback never masks a real problem.
- **Non-positive or missing close price** feeding `compute_atr_pct` — same fallback, K=1, no
  crash. Mirrors `pipeline.py`'s existing "invalid price → hold, never raise" contract, one
  layer earlier in the pipeline.
- **Caller/index mismatch** — a `confirmation_bars` Series not aligned to `df`'s index is a
  programmer error, not a market-data edge case, and raises `ValueError`. Internal
  preconditions fail loud; external/market-data gaps fail soft to a safe default — the same
  split the vix/sentiment/earnings gates already use.
- **New roster symbols with short history** — not an error, an expected extended fallback
  period: a freshly-fetched CSV without 260 bars of history runs at K=1 (unfiltered) until it
  accumulates enough trailing data for real percentile ranking (roughly the first ~2 live
  trading weeks for a brand-new symbol). This is the reason the roster ships
  backtest-first (see "Sequencing," below) rather than straight onto the live watchlist.

## Testing

**Unit tests** (new files, following this project's existing convention — plain synthetic
DataFrames, no mocking of the function under test):

- `tests/test_volatility.py`: `confirmation_bars_series` rises in a synthetic high-volatility
  segment vs. a low-volatility one (relative check, not a hardcoded value, since ranking is
  self-relative by design); all-K=1 on insufficient history; K=1 fallback on a
  non-positive/NaN close bar with no exception; `compute_atr_pct` sanity (non-negative, wider
  true-range bars produce a larger value).
- `tests/test_strategy_engine.py` additions: `confirmation_bars=None` reproduces today's
  existing fixture output exactly (regression guard proving back-compat); a buy condition
  holding for exactly 1 bar then breaking stays "hold" under `confirmation_bars=2` where it
  would fire today; a condition holding 3 consecutive bars fires "buy" only on the 3rd bar
  under `confirmation_bars=3`; a mixed per-bar `Series` (K=1 early, K=3 later) uses each
  bar's own K, not one global value; a misaligned-index `Series` raises `ValueError`.
- `tests/test_sector_config.py`: trivial mapping/reverse-lookup correctness.

**Integration tests** — extend `test_backtester.py`/`test_live_loop.py` using their existing
`unittest.mock.patch` convention: assert `run_backtest` and the live cycle call
`compute_signals` with a `confirmation_bars` kwarg actually derived from
`volatility.confirmation_bars_series(df)` for that symbol, not silently dropped.

**Out-of-sample validation** (research script, not pytest/CI — same category as
`scripts/run_sector_backtest.py`): a new `scripts/validate_sector_engine.py` splits each
symbol's CSV chronologically (last 20% of bars held out), then re-runs the hold-time whipsaw
breakdown from the root-cause analysis *only on that held-out slice*, comparing short-hold
win rate with confirmation-bars on vs. off. This is what actually proves the fix generalizes,
rather than just fitting the data already eyeballed during root-cause analysis.

## Roster and Sequencing (resolved 2026-08-17)

- **Roster locked in:** energy → XOM/CVX, tech → NVDA/MSFT, health → JNJ/UNH, alongside the
  existing AAPL/SPY.
- **Sequencing: backtest-validate first, then flip the live watchlist.** The six new symbols
  get fetched (`scripts/fetch_sector_data.py`/`fetch_alpaca_data.py`-style) and backtested —
  including the out-of-sample validation above — *before* `live_loop.py`'s `WATCHLIST` is
  touched. Rationale: the live cron still hasn't confirmed a completed market-hours cycle
  (unverified, tracked separately), and per "Error Handling" above, any brand-new symbol
  runs unfiltered (K=1) for its first ~2 weeks live regardless — validating on historical
  data first avoids live-trading an engine that's unproven on two independent fronts (cron
  reliability and volatility scaling) simultaneously.

## Out of Scope (this design)

- RSI oversold/overbought threshold adjustment by volatility — the root-cause analysis
  validated confirmation-bars as the fix; a second threshold-adjustment knob is not built
  here (YAGNI — add it only if confirmation-bars alone proves insufficient after the
  out-of-sample validation).
- Any consumption of `sector_config.py`'s `SYMBOL_SECTOR` tag — reserved for a future,
  separate design (e.g. sector-specific event gates), not part of this engine.
- The two sibling subsystems from the original decomposition (automated external
  financial-data feed, YouTube-transcript-derived signal) — separate specs, not started.
- Live cron verification and GitHub Actions secret confirmation — unrelated, unblocked,
  tracked in the carried-forward handoff thread, not part of this design.
