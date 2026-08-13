# Graywind Phase 1 — Rule-Based Intraday Equities MVP (Hand-Rolled Pipeline)

**Supersedes**: `docs/superpowers/specs/2026-08-13-graywind-phase1-mvp-design.md` (LEAN
Engine-based). That spec is superseded because free-tier QuantConnect accounts have **zero**
API/CLI access by design — confirmed against QuantConnect's own docs and forum, not just
assumed. There is no free path to `lean init`/`lean-cli` for this project. See "Why LEAN was
dropped" below for the full evaluation.

## Purpose

Graywind is an algorithmic trading bot. The end goal is trading real capital, but Phase 1
exists to prove the full pipeline (data → signal → risk-checked order → paper fill →
backtest evaluation) works end-to-end with a simple, well-understood strategy before any
machine learning or real money enters the picture.

**Goal path**: paper trading now → real capital later, only after a sustained proving
period on paper (Phase 3, not started).

## Scope decisions (locked in during brainstorming)

- **Asset class**: US equities (not crypto) — unchanged from the prior spec.
- **Framework**: no third-party trading engine. Hand-rolled on `pandas` +
  `pandas-ta-classic` (signal math) + `alpaca-py` (historical bars, live paper order
  execution). $0 cost, no account beyond what's already required for the strategy itself.
- **Trading style**: intraday / day trading.
- **Capital**: starting under $25k — the Pattern Day Trader (PDT) rule is a hard constraint,
  not a soft one: max 3 day-trades (opened + closed same session) per rolling 5 business
  days, enforced by FINRA/the broker.
- **Broker/data**: Alpaca — free paper trading API, free historical bars via the IEX feed,
  commission-free, plus (new in this pivot) Alpaca's News API for the sentiment gate. All
  already covered by one Alpaca account.
- **Trading hours**: US equities regular session only — ~9:30am–4:00pm ET, Monday–Friday,
  excluding market holidays. No pre-market/after-hours extended sessions — deferred, not in
  scope.

## Why LEAN was dropped

- QuantConnect's own docs/forum confirm: "To use the CLI, you must be a member in an
  organization on a paid tier." Free accounts cannot run `lean init` at all — not a bug,
  a deliberate product gate.
- The open-source LEAN *engine* itself (not `lean-cli`) can technically run via a raw
  `docker run` with a default `config.json` (empty `api-access-token`, no QC account
  needed) — considered and **rejected** as too much hand-rolled Docker/data-format
  plumbing for this project's size and the available time budget.
- Three free alternative frameworks were evaluated and rejected:
  - **NautilusTrader** — free/MIT, actively developed, but its Alpaca integration is an
    unshipped RFC with no near-term maintainer commitment and two incomplete community
    forks. Worth rechecking before any future Phase 2 planning, not usable now.
  - **zipline-reloaded** — free, but backtest-only, no live/paper execution layer, needs
    its own data-bundle ingestion, designed for daily cross-sectional research rather than
    intraday single-symbol signals.
  - **backtrader** — free, but frozen/dead for new 2026 projects; its Alpaca link was
    always an unofficial, unmaintained third-party package.
  - Common gap across all three: none give free live/paper order execution, which was
    specifically what LEAN's paid tier was buying. This is why the decision bypasses
    third-party trading frameworks entirely rather than swapping to another one.

## Non-goals for Phase 1 (explicitly deferred)

- No ML/RL model (Phase 2).
- No multi-symbol portfolio optimization — one clear rule-based signal on a small fixed
  watchlist.
- No limit orders / partial-fill handling — market orders only.
- No Kelly Criterion position sizing — fixed-fractional only.
- No real capital — paper trading only.
- **Regime filter — revised, not deleted**: the prior spec's "no regime filter" is
  narrowed to permit exactly one coarse rule-based daily VIX threshold gate (see
  Architecture, component 3). This is a fixed threshold check, not a learned
  regime-detection system, and is the only exception to the no-ML/no-regime posture.

## Architecture

Six components (was five in the LEAN-based spec — the new Signal Augmentation Gates layer
is the addition):

### 1. Data Ingestion
`fetch_alpaca_data.py` — pulls historical intraday 15-minute bars from Alpaca's free
Market Data API (IEX feed) for a fixed two-symbol watchlist (AAPL, SPY — both highly
liquid, minimizing slippage/fill-risk noise while the pipeline is being proven) into local
CSVs, which are loaded directly into a pandas DataFrame (replaces the prior spec's custom
LEAN `PythonData` reader — no behavior change, just a simpler consumer). 15-minute bars
kept from the prior spec: lower noise for a first RSI/MA-crossover implementation, and
naturally fewer signals per day, helping stay under the PDT throttle's 3-day-trade window
while the strategy is unproven.

This mirrors the pattern already proven in the Bullion project
(`fetch_bullion_data.py` → `data.json` → app reads it locally): an external fetch script
writing a local file that the main app consumes, kept decoupled so fetch logic can be
tested and rerun independently of the trading loop.

**This component serves the research/backtest path only** — see "Live path" below for how
the deployed bot gets data while actually paper trading.

### 2. Strategy Engine (rule-based)
RSI + moving-average crossover computed via `pandas_ta_classic` directly on the ingested
DataFrame — same signal logic/thresholds as the prior spec, now plain pandas instead of a
LEAN `QCAlgorithm`. `pandas-ta-classic` (github.com/xgboosted/pandas-ta-classic) is an
actively maintained fork of the original `pandas-ta` (which carries sustainability/
donation-risk warnings on its own site), 250+ indicators, no TA-Lib dependency.

### 3. Signal Augmentation Gates (NEW)
Three independent boolean gates a raw buy signal must pass before reaching Risk
Management. All are simple threshold rules, not trained models, consistent with the
project's no-ML non-goal:

- **VIX gate**: blocks if yesterday's FRED `VIXCLS` daily close exceeds a configured
  threshold. FRED integration reuses the same free-instant-API-key pattern already proven
  in the Bullion project.
- **Sentiment gate**: blocks if VADER's compound sentiment score on recent Alpaca News
  headlines (already free with any Alpaca account, no new signup, 6+ years of headlines)
  falls below a configured negative threshold. VADER is local/lexicon-based — no API call,
  no model training.
- **Earnings gate**: blocks if Finnhub's earnings-calendar endpoint shows an earnings date
  for the symbol within N days (free tier, confirmed no credit card required, key issued
  on email confirmation, 60 calls/min). Confirmed first that Alpaca's own Corporate
  Actions API does **not** cover earnings dates (only dividends/mergers/spinoffs/splits) —
  Finnhub fills a real gap, not a redundant integration.

**Fail-closed rule**: if any gate's underlying data source is unreachable for a symbol,
that gate blocks the trade — it does not skip itself and let the signal through.

### 4. Risk Management
Unchanged in logic from the prior spec, now called from a plain Python loop instead of
`QCAlgorithm` hooks:

- **PDT throttle**: tracks day-trades in a rolling 5-business-day window; blocks any new
  day-trade once 3 are used. Hard stop, not advisory.
- **Per-trade stop-loss / take-profit** and **fixed-fractional position sizing** (e.g. risk
  1% of account equity per trade).
- **Daily drawdown circuit breaker** — halts new trades for the remainder of the day once
  realized+unrealized losses reach 2% of account equity for that day. Starting default;
  revisit once backtest results give a real basis to tune it.

### 5. Execution & Routing
`alpaca-py`'s `TradingClient` places market orders directly against Alpaca's paper
trading endpoint — replaces LEAN's built-in brokerage integration with a direct API call.
Market orders only, same as the prior spec.

### 6. Backtesting & Evaluation
A hand-rolled bar-by-bar backtest loop over the historical DataFrame — replaces
`lean backtest`. Computes the same stats as before (Sharpe ratio, max drawdown, win rate)
manually, plus the same custom assertion: **no 5-business-day window in the backtest
period ever exceeds 3 day-trades**, verified against historical simulation and its own
trade log rather than LEAN's results JSON.

## Live path

A scheduled loop script, active only during market hours (~9:30am–4:00pm ET weekdays),
fetches the latest bar plus gate data (VIX, sentiment, earnings) every 15 minutes and
evaluates the same signal → gates → risk-checks → order code path used in backtesting.
Replaces `lean live deploy`. No custom streaming infrastructure — a scheduled poll is
sufficient at 15-minute resolution.

## Data flow

Two paths — research/backtest (any time, off market hours included) and live paper
trading (market hours only, after deployment). Both feed the same Strategy Engine / Gates
/ Risk Management / Execution logic; only how data enters differs.

**Research/backtest path:**
```
Alpaca Market Data API (IEX feed)
        │  fetch_alpaca_data.py (manual run)
        ▼
Local CSV per symbol
        │  loaded into pandas DataFrame
        ▼
Strategy Engine (RSI + MA crossover via pandas_ta_classic)
        │  raw signal (Buy/Sell/Hold)
        ▼
Signal Augmentation Gates (VIX / sentiment / earnings — fail closed)
        │  gated signal
        ▼
Risk Management (PDT throttle, stop-loss, position sizing, drawdown breaker)
        │  approved order (or blocked)
        ▼
Execution & Routing (simulated fills against historical data)
        │
        ▼
Backtesting & Evaluation (hand-rolled loop — Sharpe, drawdown, win rate, PDT-compliance check)
```

**Live paper-trading path:**
```
Scheduled loop (market hours only, every 15 min)
        │  fetches latest bar (Alpaca) + gate data (FRED, Alpaca News, Finnhub)
        ▼
Strategy Engine (same code as backtest)
        │  raw signal
        ▼
Signal Augmentation Gates (same code as backtest, fail closed)
        │  gated signal
        ▼
Risk Management (same code as backtest)
        │  approved order (or blocked)
        ▼
Execution & Routing (alpaca-py TradingClient → Alpaca paper endpoint, real paper-account fill)
```

## Error handling

- **Data fetch failures** (Alpaca API down, rate limited, symbol delisted): script logs
  and exits non-zero rather than silently writing a partial/stale CSV; the trading loop
  should never run against silently-stale data. (Direct lesson from Bullion: a silently
  empty/wrong secret caused 15 straight days of a cron job failing invisibly.)
- **Gate data source unreachable** (FRED/Alpaca News/Finnhub down or erroring): that gate
  fails closed and blocks the trade — this is the fail-closed rule from Architecture
  component 3, restated here as the operative error-handling behavior, not just a design
  note.
- **PDT throttle violated by a strategy signal**: the order is silently blocked and
  logged, not queued/deferred — the strategy loop treats "blocked" as a normal outcome,
  not an error condition.
- **Broker rejection** (insufficient buying power, market closed, etc.): logged, no
  retry-loop — a rejected order stays rejected for that signal; the next bar's signal is
  independent.

## Testing approach

- **Pure-Python unit tests** for PDT-counter logic, position-sizing math, and (new) each
  of the three gates — the gate tests use fixture data, not live API calls, so they stay
  fast and deterministic.
- **Integration validation** via a real end-to-end backtest run against real fetched data
  — not code review standing in for execution. (Bullion's project memory has a standing
  lesson about implementers substituting non-executing checks for real probes; this
  project inherits the same discipline.)
- **Manual paper-trading burn-in period** before advancing to Phase 2 (ML) or Phase 3
  (real capital). Length is a deliberate deferred decision — it depends on Phase 1's own
  backtest results. The implementation plan must end with an explicit "set burn-in length"
  task informed by actual backtest output, not a silent skip.
- Before wiring any of the four new free-resource integrations (pandas-ta-classic, Alpaca
  News+VADER, FRED VIX, Finnhub earnings) into the plan, confirm each API's real response
  shape and rate limits against a live test call — not just documentation prose. This
  standard already produced this pivot itself (reading QuantConnect's docs/forum and the
  raw `nautilus_trader` GitHub issue directly, rather than trusting a summary).

## Future phases (separate specs, not detailed here)

- **Phase 2**: replace the rule-based RSI/MA signal with a trained ML/RL model
  (RandomForest/XGBoost, or FinRL's DRL agents) once Phase 1's pipeline is proven sound.
  Re-evaluate NautilusTrader's Alpaca adapter maturity at this point — it was the
  strongest long-term engine of the three rejected alternatives, if its adapter ships.
- **Phase 3**: graduate from Alpaca paper trading to small real capital, only after a
  sustained proving period on paper.

## Environment setup (Phase 1, Task 1)

No Docker, no `lean-cli`. Python 3.11+ (3.14.6 confirmed working during the abandoned LEAN
attempt, no compatibility issues). Package set: `pandas`, `pandas-ta-classic`, `alpaca-py`,
`vaderSentiment`, `requests`, `pytest`. Accounts needed: Alpaca paper (already required),
FRED API key (free, instant), Finnhub API key (free, instant, no card).
