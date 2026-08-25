# Graywind News-Debate Shadow Mode — Design Spec

**Written:** 2026-08-25 · **Sub-project 3 of 3** in the capital-scaling redesign
([[project-graywind-capital-redesign]], memory) — the "upgrade `sentiment_gate.py` beyond
VADER polarity to actual read-and-interpret" piece.

## Goal

Replace `sentiment_gate.py`'s VADER compound-score scoring with a Claude-based bull/bear/judge
news debate — but run it in **shadow mode only**: it logs its verdict for every symbol/cycle
without ever gating a trade. VADER stays the live gate, unchanged, for the duration of this
spec. A later, separate decision (not part of this spec) is whether/how to make the debate
authoritative, made after reviewing enough shadow-mode history to trust it.

## Why shadow mode, not a straight swap

Brainstorming surfaced two flaws serious enough to change the design, not just tune it:

1. **Lookahead bias in any backtest use.** Claude's training data includes knowledge of what
   actually happened after any historical headline. Asking it to "interpret" a 2023 headline
   for a backtest risks it reasoning with hindsight of the outcome, not as a trader would have
   at the time — VADER's static lexicon can't do this. A backtest run through the debate could
   look great while being silently contaminated, and there'd be no way to tell from the numbers
   alone.
2. **No principled way to calibrate a threshold.** VADER's `-0.2` threshold came from
   eyeballing known headlines against a bounded, well-understood scale. A judge's `-1.0..1.0`
   score has no equivalent calibration set — and per (1), calibrating it against backtest
   results would be circular.

Shadow mode sidesteps both: `backtester.py` is untouched (no lookahead risk, nothing to
calibrate against), and live shadow verdicts are judged against real, not-yet-happened
outcomes, which is the only way to get real evidence the debate adds value.

**Also de-risked by this choice:** the debate adds three new network calls (bull, bear, judge)
on top of the existing headline fetch, each able to fail independently. If those calls gated
trades, that would triple the gate's failure surface. In shadow mode, a failed debate call
just means no logged verdict that cycle — VADER, unaffected, still decides the trade.

## Components

### 1. `graywind_strategy/gates/news_debate.py` (new module)

Three Claude calls per invocation, using forced structured output (tool-use/JSON schema, not
free-text parsing) so malformed output is a hard error, not a silent misparse:

- `bull_argument(llm_client, headlines) -> str` — argues the bullish read of the headlines.
- `bear_argument(llm_client, headlines) -> str` — argues the bearish read.
- `judge_verdict(llm_client, headlines, bull_argument, bear_argument) -> Verdict` — a small
  dataclass: `score: float` (`-1.0..1.0`), `reasoning: str`.

`llm_client` is injected (same dependency-injection shape as `news_client` throughout this
codebase), so tests mock it and never make a real API call. No new project dependency exists
yet — this spec adds `anthropic` to `requirements.txt` and `ANTHROPIC_API_KEY` to
`.env.example`, following the existing `ALPACA_API_KEY`/`FRED_API_KEY`/`FINNHUB_API_KEY`
pattern.

Fetching headlines reuses `sentiment_gate.fetch_recent_headlines()` unchanged — no duplicate
fetch logic.

### 2. Per-cycle cache

A simple in-memory (per `live_loop.py` process invocation) cache keyed on
`(symbol, hash(tuple(headlines)))`, skipping a re-debate if the headline set hasn't changed
since the last check this run. Cron invokes `live_loop.py` fresh each cycle (per
`state_store.py`'s own docstring: "each run is a fresh process"), so this cache's scope is one
cycle, not cross-cycle — it only prevents redundant debate calls if a symbol is checked more
than once within the same run. Not load-bearing for correctness; a nice-to-have that costs
almost nothing to include. No persistent cache, no cross-run state — that complexity is only
needed for backtest reproducibility, which is out of scope per the shadow-mode decision above.

### 3. Shadow logging

New file `dashboard-data/news_debate_log.csv` (same directory as the existing
`trade_log.csv`/`equity_curve.csv`, since like those it accumulates history rather than
snapshotting current state — the distinction `state_store.py`'s docstring already draws).
Columns: `timestamp, symbol, vader_score, vader_gate_result, debate_score, debate_reasoning`.
Logging both VADER's and the debate's outputs side by side on the same row is what makes later
comparison possible — the whole point of shadow mode.

New function `graywind_strategy/dashboard_export.py::log_news_debate(...)` appends one row,
following that module's existing append-only CSV pattern (distinct from `state_store.py`'s
overwrite-every-save pattern, matching `trade_log.csv`'s semantics, not `positions.csv`'s).

### 4. Wiring into `live_loop.py`

Called from `process_symbol()` (`live_loop.py:118`), alongside the existing `news_client`
usage, **additively** — it does not touch `decide_trade()`'s call or its return value.
`pipeline.py` is completely unchanged; the sentiment gate that actually decides `decision.action`
stays exactly as it is today. This is what makes the shadow-mode boundary structural rather
than just a convention someone could accidentally violate later — the debate's output has no
code path into `decide_trade()`.

## Error handling

Fails **open** for logging purposes, not closed — this is the opposite of every existing gate,
and deliberately so: a failed debate call (timeout, rate limit, malformed structured output)
should never affect the trade cycle, since it isn't gating anything. Catch the exception, skip
logging a row for that symbol/cycle, print a warning, move on. `process_symbol()`'s existing
flow continues unaffected.

## Testing

- `bull_argument`/`bear_argument`/`judge_verdict`: unit tests with a mocked `llm_client`
  (`MagicMock`, matching `test_sentiment_gate.py`'s `news_client` mocking pattern) — verify the
  prompt construction and that a mocked structured response parses into the right `Verdict`
  fields. A malformed/missing field in the mocked response should raise, not silently default.
- `log_news_debate`: round-trip test on `news_debate_log.csv`, same shape as
  `dashboard_export.py`'s existing tests for `trade_log.csv`.
- `process_symbol()` integration: a debate-call exception (mocked to raise) does not prevent
  the symbol's normal buy/sell/hold decision from proceeding, and does not raise out of
  `process_symbol()` itself.
- No test makes a real Claude API call.

## Deferred, not forgotten

- Whether/how to make the debate authoritative (replace VADER as the actual gate) — a future
  decision made after reviewing shadow-mode history, explicitly out of scope here.
- Backtest coverage for the debate gate — not pursued at all per the lookahead-bias finding
  above; if pursued later, requires either accepting the contamination risk explicitly or
  pinning a dated model snapshot old enough to predate the backtest window (evaluated during
  brainstorming, not adopted: doesn't cover recent history, adds version-pinning complexity,
  older models reason worse).
- Recalibrating `SENTIMENT_THRESHOLD` or defining an equivalent threshold for the debate's
  score — moot until/unless the debate becomes authoritative.
- Cross-run/persistent caching — only relevant if backtest coverage is revisited later.
