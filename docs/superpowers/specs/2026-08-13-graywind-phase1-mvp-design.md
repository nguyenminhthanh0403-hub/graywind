# Graywind Phase 1 — Rule-Based Intraday Equities MVP

## Purpose

Graywind is an algorithmic trading bot. The end goal is trading real capital, but Phase 1
exists to prove the full pipeline (data → signal → risk-checked order → paper fill →
backtest evaluation) works end-to-end with a simple, well-understood strategy before any
machine learning or real money enters the picture.

**Goal path**: paper trading now → real capital later, only after a sustained proving
period on paper (Phase 3, not started).

## Scope decisions (locked in during brainstorming)

- **Asset class**: US equities (not crypto) — chosen despite crypto's faster
  iteration/no-PDT advantage, because the user wants equities specifically.
- **Framework**: LEAN Engine (QuantConnect), run fully free locally via `lean-cli` +
  Docker — not the paid QuantConnect Cloud. Chosen over Freqtrade/Jesse for multi-asset
  headroom (equities now, crypto later possible on the same engine).
- **Trading style**: intraday / day trading.
- **Capital**: starting under $25k. This makes the Pattern Day Trader (PDT) rule a hard
  constraint, not a soft one: max 3 day-trades (opened + closed same session) per rolling
  5 business days, enforced by FINRA/the broker, not just a risk preference.
- **Broker/data**: Alpaca — free paper trading API, free historical bars via the IEX feed
  (any Alpaca account), commission-free. Chosen over QuantConnect's own historical
  datasets, which are metered/paid beyond a small free sample — pulling from Alpaca
  directly keeps the whole stack at $0, matching the project's cost constraint.
- **Environment**: nothing installed yet. Phase 1 includes environment setup as its first
  task (Python, Docker, `lean-cli`, Alpaca paper account + API keys).
- **Trading hours**: US equities regular session only — ~9:30am–4:00pm ET, Monday–Friday,
  excluding market holidays. Graywind reads/trades live only during those hours; it is
  idle the rest of the time by definition of the asset class, not as a limitation to fix.
  No 24/7 operation is possible or intended for Phase 1 — that property belongs to crypto,
  which was considered and explicitly not chosen (see asset class decision above). No
  pre-market/after-hours extended sessions either — deferred, not in scope.

## Non-goals for Phase 1 (explicitly deferred)

- No ML/RL model (Phase 2 — see below).
- No regime filter, no multi-symbol portfolio optimization — one clear rule-based signal
  on a small fixed watchlist.
- No limit orders / partial-fill handling — market orders only.
- No Kelly Criterion position sizing — fixed-fractional only.
- No real capital — paper trading only.

## Architecture

Five components, matching the professional architecture described in the source guide
(`~/trading_bot_architecture_guide.md`), scoped down to rule-based + paper trading:

### 1. Data Ingestion
`fetch_alpaca_data.py` — a standalone script that pulls historical intraday 15-minute bars
from Alpaca's free Market Data API (IEX feed) for a fixed two-symbol watchlist (AAPL,
SPY — both highly liquid, minimizing slippage/fill-risk noise while the pipeline is being
proven) and writes them to local CSVs, which LEAN reads via a custom `PythonData` type.
15-minute (not 5-minute) bars chosen deliberately for Phase 1: lower noise for a first RSI/
MA-crossover implementation, and naturally fewer signals per day, which helps stay under
the PDT throttle's 3-day-trade window while the strategy is still unproven.

This mirrors the pattern already proven in the Bullion project
(`fetch_bullion_data.py` → `data.json` → app reads it locally) — same shape, not a new
one: an external fetch script writing a local file that the main app consumes, kept
decoupled so the fetch logic can be tested and rerun independently of the trading engine.

**This component serves the research/backtest path only.** It is separate from — and
should not be confused with — how the deployed bot gets data while actually paper trading
live; see "Live paper-trading data path" below.

### 2. Strategy Engine (rule-based)
A LEAN `QCAlgorithm` in Python. Signal: RSI + moving-average crossover on the watchlist.

**Starting skeleton, not written from scratch**: `QuantConnect/Lean`'s own GitHub repo
(`Algorithm.Python/MovingAverageCrossAlgorithm.py`) plus its RSI/MACD/SMA/EMA/ATR
indicator examples are the literal starting point for this component. This is legitimate
reuse of engine boilerplate (Initialize/OnData wiring, indicator registration) — it saves
implementation time without shortcutting the actual strategy logic, which still has to be
designed and proven ourselves. See "Open-source references" below.

### 3. Risk Management
The load-bearing new component given the under-$25k constraint:

- **PDT throttle**: tracks day-trades in a rolling 5-business-day window; blocks any new
  day-trade once 3 are used in that window. Hard stop, not advisory.
- **Per-trade stop-loss / take-profit** and **fixed-fractional position sizing** (e.g.
  risk 1% of account equity per trade).
- **Daily drawdown circuit breaker** — halts new trades for the remainder of the day once
  realized+unrealized losses reach 2% of account equity for that day. 2% is a starting
  default (small enough that a bad day can't meaningfully damage a small account before
  the strategy is proven); revisit once backtest results give a real basis to tune it.

### 4. Execution & Routing
LEAN's built-in Alpaca brokerage integration, pointed at Alpaca's paper trading endpoint.
Market orders only.

### 5. Backtesting & Evaluation
`lean backtest` run locally via `lean-cli` against the Alpaca-sourced CSVs. Produces
standard stats (Sharpe ratio, max drawdown, win rate) plus one custom assertion specific
to this project: **no 5-business-day window in the backtest period ever exceeds 3
day-trades** — the PDT throttle is verified against historical simulation, not just
trusted from code review.

### Live paper-trading data path (distinct from component 1 above)
This was missing from an earlier draft of this spec and is added here explicitly, since
it's the actual "read the market in real time and trade on it" mechanism — component 1's
CSV pipeline only feeds `lean backtest`, not this.

When Phase 1 is deployed as a live paper-trading run (`lean live deploy`, targeting
Alpaca's paper endpoint), LEAN's built-in Alpaca brokerage integration handles real-time
data natively: once `Initialize()` declares the AAPL/SPY securities and 15-minute
resolution, LEAN subscribes to Alpaca's live data feed on its own and calls the
algorithm's `OnData()` automatically as each new bar closes during market hours. No custom
streaming code and no `fetch_alpaca_data.py` involvement — that script's CSVs are used
once, by the researcher, before deployment; the live loop is a different, LEAN-native
mechanism, running only within the trading-hours window defined in the scope decisions
above.

## Data flow

Two separate paths — research/backtest (before deployment) and live paper trading
(during market hours, after deployment). Both feed the same Strategy Engine / Risk
Management / Execution logic; only how data enters the pipeline differs.

**Research/backtest path** (run manually, any time, off market hours included):
```
Alpaca Market Data API (IEX feed)
        │  fetch_alpaca_data.py (manual run)
        ▼
Local CSV per symbol
        │  LEAN custom PythonData reader
        ▼
QCAlgorithm (Strategy Engine: RSI + MA crossover)
        │  signal (Buy/Sell/Hold)
        ▼
Risk Management (PDT throttle, stop-loss, position sizing, drawdown breaker)
        │  approved order (or blocked)
        ▼
Execution & Routing (simulated fills against historical data)
        │
        ▼
Backtesting & Evaluation (lean backtest — Sharpe, drawdown, win rate, PDT-compliance check)
```

**Live paper-trading path** (`lean live deploy`, active only ~9:30am–4:00pm ET weekdays):
```
Alpaca live data feed (IEX, real-time)
        │  LEAN's native Alpaca brokerage integration (no custom script)
        ▼
QCAlgorithm.OnData() (same Strategy Engine code as backtest)
        │  signal (Buy/Sell/Hold)
        ▼
Risk Management (same PDT throttle / stop-loss / sizing / drawdown logic)
        │  approved order (or blocked)
        ▼
Execution & Routing (LEAN → Alpaca brokerage, real paper-account fill)
```

## Error handling

- **Data fetch failures** (Alpaca API down, rate limited, symbol delisted): script logs
  and exits non-zero rather than silently writing a partial/stale CSV; the trading engine
  should never run against silently-stale data. (Direct lesson from Bullion: a silently
  empty/wrong secret caused 15 straight days of a cron job failing invisibly — see the
  project's own [[ci-verify-scheduled-runs-actually-succeed]] pattern of always checking
  that scheduled runs actually succeeded, not just that they ran.)
- **PDT throttle violated by a strategy signal**: the order is silently blocked and
  logged, not queued/deferred — the strategy engine must treat "blocked" as a normal
  outcome, not an error condition.
- **Broker rejection (insufficient buying power, market closed, etc.)**: logged, no
  retry-loop — a rejected order stays rejected for that signal; the next bar's signal is
  independent.

## Testing approach

- **Pure-Python unit tests** for the PDT-counter logic and position-sizing math — these
  don't need LEAN or Docker to run, so they're fast to iterate on. Same split Bullion used
  between pure-logic tests (`test_calibrate.py`) and integration checks.
- **Integration validation** via an actual `lean backtest` run against real historical
  data — not code review standing in for execution. (Bullion's project memory has a
  standing lesson about implementers substituting non-executing checks for real probes;
  this project inherits the same discipline: a claim of "the PDT throttle works" requires
  an actual backtest run showing it, not just reading the code.)
- **Manual paper-trading burn-in period** before advancing to Phase 2 (ML) or Phase 3
  (real capital). The exact length is a deliberate deferred decision, not an oversight —
  it depends on Phase 1's own backtest results (a strategy with a poor Sharpe ratio needs
  longer/no burn-in at all; a strong one still needs enough calendar time to cross a few
  different day-to-day conditions). The Phase 1 implementation plan must end with an
  explicit "set burn-in length" task informed by the actual backtest output, rather than
  silently skipping this decision.

## Open-source references (confirmed via web search, 2026-08-13)

These are boilerplate/plumbing to build on top of, not sources of proven alpha — no
credible free source hands over a working profitable strategy (if one existed and worked,
publishing it would let the market arbitrage the edge away). What's genuinely useful:

- **`QuantConnect/Lean`** (github.com/QuantConnect/Lean) — the engine itself, MIT-adjacent
  open source. `Algorithm.Python/MovingAverageCrossAlgorithm.py` and the RSI/MACD/SMA/EMA/
  ATR indicator examples are Phase 1's literal starting skeleton for the Strategy Engine.
- **Alpaca's own example repos** (`alpacahq/Momentum-Trading-Example`,
  community moving-average/ROC bots like `YuxinSUN89/Alpaca_API_Trading`) — reference for
  Alpaca API wiring patterns, though LEAN's built-in Alpaca brokerage integration already
  covers this, so these are secondary reference, not something we integrate directly.
  **Note**: `alpacahq/example-scalping` explicitly requires $25k+ equity for PDT reasons —
  confirms the PDT constraint is a real, commonly-hit wall, and this repo is disqualified
  for Phase 1's under-$25k scope.
- **FinRL** (`AI4Finance-Foundation/FinRL`, MIT licensed) — an open-source deep
  reinforcement learning *training framework* (DQN/PPO/SAC/A2C/TD3 agents + market
  environments), not a pretrained profitable model — still requires training on our own
  data. Flagged as the **Phase 2** ML option to evaluate then, not adopted now.

## Future phases (separate specs, not detailed here)

- **Phase 2**: replace the rule-based RSI/MA signal with a trained ML/RL model
  (RandomForest/XGBoost, or FinRL's DRL agents) once Phase 1's pipeline is proven sound.
- **Phase 3**: graduate from Alpaca paper trading to small real capital, only after a
  sustained proving period on paper.

## Environment setup (Phase 1, Task 0)

Nothing is installed yet. First task in the implementation plan must cover: Python,
Docker, `lean-cli` (`pip install lean`), Docker image pull, and creating an Alpaca
paper-trading account + API keys. All free, all one-time.
