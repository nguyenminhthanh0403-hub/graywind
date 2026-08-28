# Graywind News-Debate Shadow Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Claude-based bull/bear/judge news debate that logs a shadow-mode verdict for every symbol/cycle next to VADER's existing score, without ever gating a trade.

**Architecture:** A new leaf module (`graywind_strategy/gates/news_debate.py`) holds three Claude-calling primitives (`bull_argument`, `bear_argument`, `judge_verdict`, each taking an injected `llm_client`) plus one orchestration function (`evaluate_shadow_debate`) that fetches headlines (reusing `sentiment_gate.fetch_recent_headlines`), scores them with VADER, runs the debate (with a per-cycle in-memory cache), and returns a row dict. A new `dashboard_export.py::log_news_debate(rows, dashboard_dir=...)` appends those rows to `dashboard-data/news_debate_log.csv`, mirroring `state_store.py::append_decision_log`'s exact shape (list-of-rows, no-op on empty, header-written-once). `live_loop.py`'s `process_symbol()` calls the orchestration function additively, wrapped in try/except so a debate failure never affects the real buy/sell/hold decision; `decide_trade()` and `pipeline.py` are never touched.

**Tech Stack:** Python 3, `anthropic` SDK (new dependency), `pytest` + `unittest.mock.MagicMock` for injected-client testing (zero real API calls).

**Spec:** `docs/superpowers/specs/2026-08-25-graywind-news-debate-shadow-mode-design.md`

## Global Constraints

- `graywind_strategy/gates/sentiment_gate.py` — **zero changes**. VADER keeps gating trades unchanged.
- `graywind_strategy/pipeline.py`'s `decide_trade()` — **zero changes, no new parameters.** No code path from the debate into it.
- `graywind_strategy/backtester.py` — **zero changes.** No backtest coverage for the debate (lookahead-bias risk).
- Every function that calls the Claude API (`bull_argument`/`bear_argument`/`judge_verdict`) takes an injected `llm_client` and is tested with a `MagicMock`, mirroring `tests/test_sentiment_gate.py`'s `news_client` mocking pattern exactly. **Zero tests may make a real Claude API call.**
- Error handling **fails open**: a failed debate call must never affect the trade cycle — only skip logging that row. Catch broadly, print a warning, move on.
- `requirements.txt` gets `anthropic` added; `.env.example` gets `ANTHROPIC_API_KEY` added, following the existing `ALPACA_API_KEY`/`FRED_API_KEY`/`FINNHUB_API_KEY` pattern. `ANTHROPIC_API_KEY` is **optional** — unlike the other four keys, its absence must not block the trading cycle (fails open at the process level too: `live_loop.py` only constructs an `llm_client` when the key is present, and skips the whole debate step when it isn't).
- TDD (red/green) for every change under `graywind_strategy/` and `live_loop.py`.

---

## File Structure

- **Create** `graywind_strategy/gates/news_debate.py` — `Verdict` dataclass; `bull_argument`, `bear_argument`, `judge_verdict` (Claude calls via injected `llm_client`, forced tool-use for structured output); `evaluate_shadow_debate` (orchestration: fetch headlines, score with VADER, run/cache the debate, return a row dict).
- **Create** `tests/test_news_debate.py` — unit tests for all four functions above, `llm_client`/`news_client` always `MagicMock`.
- **Modify** `graywind_strategy/dashboard_export.py` — add `log_news_debate(rows, dashboard_dir=...)`, `NEWS_DEBATE_LOG_FIELDS`, `NEWS_DEBATE_LOG_FILENAME`, `DEFAULT_DASHBOARD_DIR`.
- **Modify** `tests/test_dashboard_export.py` — round-trip + no-op + header-once + CRLF-regression tests for `log_news_debate`.
- **Modify** `live_loop.py` — `process_symbol()` gets three new optional params (`llm_client`, `debate_cache`, `debate_rows`) and an additive shadow-debate step; `main()` constructs `llm_client` from `ANTHROPIC_API_KEY` (optional), initializes `debate_cache`/`debate_rows`, passes them through, and flushes `debate_rows` via `log_news_debate` in the `finally` block.
- **Modify** `tests/test_live_loop.py` — new `process_symbol()` tests (debate row recorded on success; debate exception doesn't block the real decision or propagate) and new `main()` tests (llm_client constructed iff `ANTHROPIC_API_KEY` set).
- **Modify** `requirements.txt` — add `anthropic`.
- **Modify** `.env.example` — add `ANTHROPIC_API_KEY=your_anthropic_key_here`.

---

### Task 1: `news_debate.py` — bull/bear/judge primitives

**Files:**
- Create: `graywind_strategy/gates/news_debate.py`
- Test: `tests/test_news_debate.py`
- Modify: `requirements.txt`
- Modify: `.env.example`

**Interfaces:**
- Produces: `Verdict(score: float, reasoning: str)` dataclass; `bull_argument(llm_client, headlines: list[str]) -> str`; `bear_argument(llm_client, headlines: list[str]) -> str`; `judge_verdict(llm_client, headlines: list[str], bull_argument: str, bear_argument: str) -> Verdict`. All three raise on malformed/missing structured-output fields (no silent defaulting).

- [ ] **Step 1: Add `anthropic` to `requirements.txt` and `ANTHROPIC_API_KEY` to `.env.example`**

Append `anthropic` as a new line to `requirements.txt` (unpinned, matching the style of `pandas`/`alpaca-py`/`requests`, not `yfinance==1.6.0`).

Append to `.env.example` (after the existing `FINNHUB_API_KEY` line):
```
ANTHROPIC_API_KEY=your_anthropic_key_here
```

Validate nothing else broke:
```bash
.venv/bin/pip install -r requirements.txt
```
Expected: installs cleanly, `anthropic` importable via `.venv/bin/python -c "import anthropic"`.

- [ ] **Step 2: Write the failing tests for `bull_argument`**

Create `tests/test_news_debate.py`:

```python
from unittest.mock import MagicMock

import pytest

from graywind_strategy.gates.news_debate import (
    Verdict,
    bear_argument,
    bull_argument,
    judge_verdict,
)


def _fake_tool_response(tool_name, input_dict):
    fake_block = MagicMock()
    fake_block.type = "tool_use"
    fake_block.name = tool_name
    fake_block.input = input_dict
    fake_response = MagicMock()
    fake_response.content = [fake_block]
    return fake_response


def test_bull_argument_returns_argument_text_from_tool_response():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tool_response(
        "submit_bull_argument", {"argument": "Strong earnings beat signals upside."}
    )

    result = bull_argument(fake_client, ["Company beats earnings"])

    assert result == "Strong earnings beat signals upside."


def test_bull_argument_forces_the_bull_tool_and_includes_headlines_in_the_prompt():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tool_response(
        "submit_bull_argument", {"argument": "..."}
    )

    bull_argument(fake_client, ["Company beats earnings expectations"])

    call_kwargs = fake_client.messages.create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {"type": "tool", "name": "submit_bull_argument"}
    assert call_kwargs["tools"][0]["name"] == "submit_bull_argument"
    prompt_text = call_kwargs["messages"][0]["content"]
    assert "Company beats earnings expectations" in prompt_text


def test_bull_argument_raises_on_missing_argument_field():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tool_response(
        "submit_bull_argument", {}
    )
    with pytest.raises(KeyError):
        bull_argument(fake_client, ["Some headline"])


def test_bull_argument_raises_when_no_matching_tool_use_block_returned():
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.content = []
    fake_client.messages.create.return_value = fake_response
    with pytest.raises(ValueError):
        bull_argument(fake_client, ["Some headline"])
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_news_debate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graywind_strategy.gates.news_debate'`

- [ ] **Step 4: Write `news_debate.py` with `bull_argument` (minimal, to pass Step 2's tests)**

Create `graywind_strategy/gates/news_debate.py`:

```python
"""Claude-based bull/bear/judge news debate -- SHADOW MODE ONLY. This
module's output never gates a trade: `pipeline.py::decide_trade()` has no
code path into anything here, and this file imports nothing from
`pipeline.py`. VADER (`sentiment_gate.py`) stays the live, unchanged gate.
See docs/superpowers/specs/2026-08-25-graywind-news-debate-shadow-mode-design.md
for the full "why shadow mode" reasoning (lookahead bias, no principled
threshold calibration).

Model choice: `claude-sonnet-5`, not Opus. This runs on every symbol/cycle
of a 15-minute live-trading cron during market hours (up to ~26 cycles/day
x 2 symbols x 3 calls/symbol = ~156 calls/day) purely to accumulate shadow
history for later comparison -- it is not gating capital at risk, so the
cost/quality tradeoff favors the cheaper tier. This is a judgment call the
spec leaves open (it doesn't name a model); revisit if/when the debate is
ever considered for promotion to authoritative (see spec's "Deferred, not
forgotten" section).

Every Claude call below forces structured output via a single tool choice
(`tool_choice={"type": "tool", "name": ...}`) with `additionalProperties:
False` schemas, and reads required fields with direct dict indexing (not
`.get()`) -- a malformed or missing field is a loud KeyError/ValueError,
never a silent default, per the spec's testing requirements. Thinking is
explicitly disabled on these calls (`thinking={"type": "disabled"}`):
forcing a specific tool_choice is not compatible with extended thinking,
and thinking adds unneeded latency/cost to a short structured-output call
that never gates anything time-sensitive.

`llm_client` is injected on every function here (same shape as
`news_client` throughout this codebase) -- tests always pass a MagicMock
and never make a real API call.
"""
from dataclasses import dataclass

NEWS_DEBATE_MODEL = "claude-sonnet-5"
NEWS_DEBATE_MAX_TOKENS = 1024

BULL_TOOL_NAME = "submit_bull_argument"
BEAR_TOOL_NAME = "submit_bear_argument"
JUDGE_TOOL_NAME = "submit_verdict"


@dataclass
class Verdict:
    score: float
    reasoning: str


def _headlines_block(headlines):
    if not headlines:
        return "(no recent headlines)"
    return "\n".join(f"- {h}" for h in headlines)


def _tool_call(llm_client, prompt, tool):
    response = llm_client.messages.create(
        model=NEWS_DEBATE_MODEL,
        max_tokens=NEWS_DEBATE_MAX_TOKENS,
        thinking={"type": "disabled"},
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool["name"]:
            return block.input
    raise ValueError(f"news_debate: no {tool['name']} tool_use block in response")


_ARGUMENT_TOOL_SCHEMA = {
    "type": "object",
    "properties": {"argument": {"type": "string"}},
    "required": ["argument"],
    "additionalProperties": False,
}


def bull_argument(llm_client, headlines):
    tool = {
        "name": BULL_TOOL_NAME,
        "description": "Submit the strongest bullish (buy-supporting) reading of these headlines.",
        "input_schema": _ARGUMENT_TOOL_SCHEMA,
    }
    prompt = (
        "You are a bullish trading analyst. Argue the strongest bullish "
        "reading of these recent headlines:\n\n" + _headlines_block(headlines)
    )
    return _tool_call(llm_client, prompt, tool)["argument"]


def bear_argument(llm_client, headlines):
    tool = {
        "name": BEAR_TOOL_NAME,
        "description": "Submit the strongest bearish (sell/avoid-supporting) reading of these headlines.",
        "input_schema": _ARGUMENT_TOOL_SCHEMA,
    }
    prompt = (
        "You are a bearish trading analyst. Argue the strongest bearish "
        "reading of these recent headlines:\n\n" + _headlines_block(headlines)
    )
    return _tool_call(llm_client, prompt, tool)["argument"]


def judge_verdict(llm_client, headlines, bull_argument, bear_argument):
    # Parameters intentionally shadow this module's own bull_argument/
    # bear_argument function names (spec's exact signature) -- not called
    # recursively here, so this is inert shadowing, not a bug.
    tool = {
        "name": JUDGE_TOOL_NAME,
        "description": "Submit a final sentiment verdict weighing the bull and bear arguments.",
        "input_schema": {
            "type": "object",
            "properties": {
                "score": {"type": "number", "minimum": -1.0, "maximum": 1.0},
                "reasoning": {"type": "string"},
            },
            "required": ["score", "reasoning"],
            "additionalProperties": False,
        },
    }
    prompt = (
        "You are an impartial judge. Weigh the bull and bear arguments below "
        "against the original headlines and give a final sentiment score from "
        "-1.0 (extremely bearish) to 1.0 (extremely bullish).\n\n"
        "Headlines:\n" + _headlines_block(headlines) +
        "\n\nBull argument:\n" + bull_argument +
        "\n\nBear argument:\n" + bear_argument
    )
    result = _tool_call(llm_client, prompt, tool)
    return Verdict(score=float(result["score"]), reasoning=result["reasoning"])
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_news_debate.py -v`
Expected: 4 PASS

- [ ] **Step 6: Write the failing tests for `bear_argument` and `judge_verdict`**

Append to `tests/test_news_debate.py`:

```python
def test_bear_argument_returns_argument_text_from_tool_response():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tool_response(
        "submit_bear_argument", {"argument": "Fraud investigation signals downside."}
    )

    result = bear_argument(fake_client, ["Company faces fraud investigation"])

    assert result == "Fraud investigation signals downside."


def test_bear_argument_forces_the_bear_tool():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tool_response(
        "submit_bear_argument", {"argument": "..."}
    )

    bear_argument(fake_client, ["Some headline"])

    call_kwargs = fake_client.messages.create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {"type": "tool", "name": "submit_bear_argument"}


def test_judge_verdict_parses_score_and_reasoning():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tool_response(
        "submit_verdict", {"score": 0.6, "reasoning": "Bull case outweighs bear case here."}
    )

    verdict = judge_verdict(
        fake_client, ["Company beats earnings"], "bull case text", "bear case text",
    )

    assert verdict == Verdict(score=0.6, reasoning="Bull case outweighs bear case here.")


def test_judge_verdict_includes_both_arguments_in_the_prompt():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tool_response(
        "submit_verdict", {"score": 0.0, "reasoning": "..."}
    )

    judge_verdict(fake_client, ["headline"], "THE BULL CASE", "THE BEAR CASE")

    prompt_text = fake_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "THE BULL CASE" in prompt_text
    assert "THE BEAR CASE" in prompt_text


def test_judge_verdict_raises_on_missing_score_field():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tool_response(
        "submit_verdict", {"reasoning": "no score given"}
    )
    with pytest.raises(KeyError):
        judge_verdict(fake_client, ["headline"], "bull", "bear")


def test_judge_verdict_raises_on_missing_reasoning_field():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tool_response(
        "submit_verdict", {"score": 0.5}
    )
    with pytest.raises(KeyError):
        judge_verdict(fake_client, ["headline"], "bull", "bear")
```

- [ ] **Step 7: Run to verify these new tests fail for the right reason, then confirm all pass**

Run: `.venv/bin/python -m pytest tests/test_news_debate.py -v`
Expected: all 10 tests PASS (the implementation from Step 4 already covers `bear_argument`/`judge_verdict` since they share `_tool_call`; if any fail, fix `news_debate.py`, not the tests).

- [ ] **Step 8: Commit**

```bash
git add graywind_strategy/gates/news_debate.py tests/test_news_debate.py requirements.txt .env.example
git commit -m "feat: add bull/bear/judge news-debate primitives (shadow mode)"
```

---

### Task 2: `dashboard_export.py::log_news_debate`

**Files:**
- Modify: `graywind_strategy/dashboard_export.py`
- Test: `tests/test_dashboard_export.py`

**Interfaces:**
- Consumes: nothing from Task 1 (independent of `news_debate.py`; only shares the row-dict shape by convention).
- Produces: `log_news_debate(rows, dashboard_dir=DEFAULT_DASHBOARD_DIR) -> None`. `rows` is a list of dicts with keys `timestamp, symbol, vader_score, vader_gate_result, debate_score, debate_reasoning`. No-op on an empty list (does not touch disk). Appends to `<dashboard_dir>/news_debate_log.csv`, writing the header only if the file doesn't already exist yet (mirrors `state_store.py::append_decision_log`'s exact shape, just targeting `dashboard-data/` instead of `state/`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dashboard_export.py`:

```python
from graywind_strategy.dashboard_export import log_news_debate


def test_log_news_debate_appends_one_row_per_call(tmp_path):
    dashboard_dir = str(tmp_path)
    log_news_debate(
        rows=[{
            "timestamp": "2026-08-27T10:00:00-04:00", "symbol": "AAPL",
            "vader_score": 0.15, "vader_gate_result": True,
            "debate_score": 0.4, "debate_reasoning": "Bull case narrowly wins.",
        }],
        dashboard_dir=dashboard_dir,
    )
    rows = _read_csv(os.path.join(dashboard_dir, "news_debate_log.csv"))
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["vader_score"] == "0.15"
    assert rows[0]["debate_score"] == "0.4"
    assert rows[0]["debate_reasoning"] == "Bull case narrowly wins."


def test_log_news_debate_is_a_noop_on_empty_rows(tmp_path):
    dashboard_dir = str(tmp_path)
    log_news_debate(rows=[], dashboard_dir=dashboard_dir)
    assert not os.path.exists(os.path.join(dashboard_dir, "news_debate_log.csv"))


def test_log_news_debate_writes_header_once_across_multiple_calls(tmp_path):
    dashboard_dir = str(tmp_path)
    row = {
        "timestamp": "2026-08-27T10:00:00-04:00", "symbol": "AAPL",
        "vader_score": 0.0, "vader_gate_result": True,
        "debate_score": 0.0, "debate_reasoning": "neutral",
    }
    log_news_debate(rows=[row], dashboard_dir=dashboard_dir)
    log_news_debate(rows=[row], dashboard_dir=dashboard_dir)

    path = os.path.join(dashboard_dir, "news_debate_log.csv")
    with open(path) as f:
        lines = f.readlines()
    assert lines[0].strip() == "timestamp,symbol,vader_score,vader_gate_result,debate_score,debate_reasoning"
    assert len(lines) == 3  # one header + two data rows, not two headers


def test_log_news_debate_creates_dashboard_dir_if_missing(tmp_path):
    dashboard_dir = str(tmp_path / "nested" / "dashboard-data")
    log_news_debate(
        rows=[{
            "timestamp": "t", "symbol": "AAPL", "vader_score": 0.0,
            "vader_gate_result": True, "debate_score": 0.0, "debate_reasoning": "x",
        }],
        dashboard_dir=dashboard_dir,
    )
    assert os.path.exists(os.path.join(dashboard_dir, "news_debate_log.csv"))


def test_log_news_debate_writes_bare_lf_not_crlf(tmp_path):
    # Same regression class as write_cycle_export's CRLF check -- must be
    # checked at the byte level, csv.DictReader silently absorbs CRLF.
    dashboard_dir = str(tmp_path)
    log_news_debate(
        rows=[{
            "timestamp": "t", "symbol": "AAPL", "vader_score": 0.0,
            "vader_gate_result": True, "debate_score": 0.0, "debate_reasoning": "x",
        }],
        dashboard_dir=dashboard_dir,
    )
    content = open(os.path.join(dashboard_dir, "news_debate_log.csv"), "rb").read()
    assert b"\r\n" not in content
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_dashboard_export.py -v -k news_debate`
Expected: FAIL — `ImportError: cannot import name 'log_news_debate'`

- [ ] **Step 3: Implement `log_news_debate` in `dashboard_export.py`**

Add near the top of `graywind_strategy/dashboard_export.py`, after the existing `STATUS_FIELDS`/`_UNEVALUATED_STATUS` constants:

```python
DEFAULT_DASHBOARD_DIR = "dashboard-data"
NEWS_DEBATE_LOG_FILENAME = "news_debate_log.csv"
NEWS_DEBATE_LOG_FIELDS = [
    "timestamp", "symbol", "vader_score", "vader_gate_result",
    "debate_score", "debate_reasoning",
]
```

Add this function at the end of the file:

```python
def log_news_debate(rows, dashboard_dir=DEFAULT_DASHBOARD_DIR):
    """Appends shadow-mode news-debate rows to
    <dashboard_dir>/news_debate_log.csv, accumulating across every cycle
    ever run -- same append-forever semantics as append_decision_log in
    state_store.py (list of rows, no-op on empty, header written once),
    just targeting dashboard-data/ directly instead of state/ (this data
    is dashboard-facing history like trade_log.csv/equity_curve.csv, not
    operational state). Written directly here rather than through the
    scratch-dir-then-merge_dashboard_export.py two-step used for
    trade_log.csv/equity_curve.csv/status.csv, since live-trading.yml's
    final `git add -A dashboard-data` step picks up any file in that
    directory regardless of how it got there -- no workflow change needed.
    """
    if not rows:
        return
    os.makedirs(dashboard_dir, exist_ok=True)
    path = os.path.join(dashboard_dir, NEWS_DEBATE_LOG_FILENAME)
    file_exists = os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=NEWS_DEBATE_LOG_FIELDS, lineterminator="\n")
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_dashboard_export.py -v`
Expected: all PASS (previous `write_cycle_export` tests unaffected, plus 5 new ones).

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/dashboard_export.py tests/test_dashboard_export.py
git commit -m "feat: add log_news_debate for shadow-mode news_debate_log.csv"
```

---

### Task 3: `news_debate.py::evaluate_shadow_debate` orchestration

**Files:**
- Modify: `graywind_strategy/gates/news_debate.py`
- Test: `tests/test_news_debate.py`

**Interfaces:**
- Consumes: `bull_argument`, `bear_argument`, `judge_verdict`, `Verdict` (Task 1, same file); `graywind_strategy.gates.sentiment_gate.fetch_recent_headlines`, `sentiment_score`, `sentiment_gate` (existing, unchanged).
- Produces: `evaluate_shadow_debate(llm_client, news_client, symbol, as_of_date, cache) -> dict` with keys `vader_score, vader_gate_result, debate_score, debate_reasoning`. `cache` is a plain dict the caller owns and passes in (mutated in place); keyed on `(symbol, hash(tuple(headlines)))`. Raises `SentimentDataUnavailable` (propagated from `fetch_recent_headlines`) or whatever `bull_argument`/`bear_argument`/`judge_verdict` raise on failure -- this function does **not** catch anything itself; the caller (`live_loop.py::process_symbol`, Task 4) is responsible for the fail-open catch.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_news_debate.py`:

```python
from graywind_strategy.gates.news_debate import evaluate_shadow_debate
from graywind_strategy.gates.sentiment_gate import SentimentDataUnavailable


def _fake_news_client(headlines):
    fake_article_list = []
    for h in headlines:
        article = MagicMock()
        article.headline = h
        fake_article_list.append(article)
    fake_response = MagicMock()
    fake_response.data = {"news": fake_article_list}
    fake_client = MagicMock()
    fake_client.get_news.return_value = fake_response
    return fake_client


def _fake_llm_client_for_debate(score=0.5, reasoning="net positive"):
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [
        _fake_tool_response("submit_bull_argument", {"argument": "bull case"}),
        _fake_tool_response("submit_bear_argument", {"argument": "bear case"}),
        _fake_tool_response("submit_verdict", {"score": score, "reasoning": reasoning}),
    ]
    return fake_client


def test_evaluate_shadow_debate_returns_vader_and_debate_fields():
    news_client = _fake_news_client(["Analysts praise company for a great, impressive earnings beat"])
    llm_client = _fake_llm_client_for_debate(score=0.7, reasoning="Strong beat outweighs bear case")

    result = evaluate_shadow_debate(
        llm_client=llm_client, news_client=news_client, symbol="AAPL",
        as_of_date=None, cache={},
    )

    assert result["vader_score"] > 0.0
    assert result["vader_gate_result"] is True
    assert result["debate_score"] == 0.7
    assert result["debate_reasoning"] == "Strong beat outweighs bear case"


def test_evaluate_shadow_debate_propagates_headline_fetch_failure():
    news_client = MagicMock()
    news_client.get_news.side_effect = Exception("network error")
    llm_client = MagicMock()

    with pytest.raises(SentimentDataUnavailable):
        evaluate_shadow_debate(
            llm_client=llm_client, news_client=news_client, symbol="AAPL",
            as_of_date=None, cache={},
        )
    llm_client.messages.create.assert_not_called()


def test_evaluate_shadow_debate_propagates_malformed_debate_output():
    news_client = _fake_news_client(["Some headline"])
    llm_client = MagicMock()
    llm_client.messages.create.return_value = _fake_tool_response(
        "submit_bull_argument", {}  # missing "argument" -> KeyError
    )

    with pytest.raises(KeyError):
        evaluate_shadow_debate(
            llm_client=llm_client, news_client=news_client, symbol="AAPL",
            as_of_date=None, cache={},
        )


def test_evaluate_shadow_debate_reuses_cached_verdict_for_same_symbol_and_headlines():
    headlines = ["Company beats earnings"]
    news_client = _fake_news_client(headlines)
    llm_client = _fake_llm_client_for_debate(score=0.3, reasoning="first call")
    cache = {}

    first = evaluate_shadow_debate(
        llm_client=llm_client, news_client=news_client, symbol="AAPL",
        as_of_date=None, cache=cache,
    )
    # Second call: same symbol, same headlines (news_client mock still
    # returns the same headline set) -- must hit the cache, not call the
    # LLM again. If it did call again, side_effect (a 3-item list, already
    # exhausted) would raise StopIteration.
    second = evaluate_shadow_debate(
        llm_client=llm_client, news_client=news_client, symbol="AAPL",
        as_of_date=None, cache=cache,
    )

    assert first["debate_score"] == second["debate_score"] == 0.3
    assert llm_client.messages.create.call_count == 3  # not 6 -- second call was a cache hit


def test_evaluate_shadow_debate_does_not_reuse_cache_across_different_symbols():
    headlines = ["Company beats earnings"]
    news_client = _fake_news_client(headlines)
    llm_client = MagicMock()
    llm_client.messages.create.side_effect = [
        _fake_tool_response("submit_bull_argument", {"argument": "bull"}),
        _fake_tool_response("submit_bear_argument", {"argument": "bear"}),
        _fake_tool_response("submit_verdict", {"score": 0.1, "reasoning": "r1"}),
        _fake_tool_response("submit_bull_argument", {"argument": "bull"}),
        _fake_tool_response("submit_bear_argument", {"argument": "bear"}),
        _fake_tool_response("submit_verdict", {"score": 0.2, "reasoning": "r2"}),
    ]
    cache = {}

    aapl_result = evaluate_shadow_debate(
        llm_client=llm_client, news_client=news_client, symbol="AAPL",
        as_of_date=None, cache=cache,
    )
    serv_result = evaluate_shadow_debate(
        llm_client=llm_client, news_client=news_client, symbol="SERV",
        as_of_date=None, cache=cache,
    )

    assert aapl_result["debate_score"] == 0.1
    assert serv_result["debate_score"] == 0.2
    assert llm_client.messages.create.call_count == 6
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_news_debate.py -v -k evaluate_shadow_debate`
Expected: FAIL — `ImportError: cannot import name 'evaluate_shadow_debate'`

- [ ] **Step 3: Implement `evaluate_shadow_debate`**

Add to `graywind_strategy/gates/news_debate.py`, at the top add the import:

```python
from graywind_strategy.gates.sentiment_gate import (
    fetch_recent_headlines,
    sentiment_gate,
    sentiment_score,
)
```

Add this function at the end of the file:

```python
def evaluate_shadow_debate(llm_client, news_client, symbol, as_of_date, cache):
    """Fetches this symbol's recent headlines, scores them with VADER (same
    scoring the live sentiment gate uses), and runs the bull/bear/judge
    debate on the same headline set -- returning both side by side so the
    caller can log a shadow-mode comparison row. Independent of
    pipeline.py::decide_trade()'s own gate evaluation: this always fetches
    and scores, regardless of whether decide_trade() would have reached
    its sentiment gate this cycle (e.g. signal != "buy", or an earlier
    gate like vix would have short-circuited it) -- that's what lets the
    shadow log build comparison history for every symbol/cycle rather than
    only the subset of cycles where VADER's gate happened to run live.

    `cache` is an in-memory dict the caller owns (per live_loop.py process
    invocation -- see the module docstring), keyed on
    (symbol, hash(tuple(headlines))): a repeat call this run with the same
    symbol and an unchanged headline set skips re-running the debate.

    Raises on any failure (headline fetch, malformed debate output) --
    does not catch anything itself. The caller is responsible for the
    fail-open catch (see live_loop.py::process_symbol), since only the
    caller knows this is a shadow-mode-only call that must never affect
    the real trade decision.
    """
    headlines = fetch_recent_headlines(news_client, symbol, as_of=as_of_date)
    vader_score = sentiment_score(headlines)
    vader_gate_result = sentiment_gate(vader_score)

    cache_key = (symbol, hash(tuple(headlines)))
    if cache_key in cache:
        verdict = cache[cache_key]
    else:
        bull = bull_argument(llm_client, headlines)
        bear = bear_argument(llm_client, headlines)
        verdict = judge_verdict(llm_client, headlines, bull, bear)
        cache[cache_key] = verdict

    return {
        "vader_score": vader_score,
        "vader_gate_result": vader_gate_result,
        "debate_score": verdict.score,
        "debate_reasoning": verdict.reasoning,
    }
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_news_debate.py -v`
Expected: all PASS (10 from Task 1 + 6 new = 16).

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/gates/news_debate.py tests/test_news_debate.py
git commit -m "feat: add evaluate_shadow_debate orchestration with per-cycle cache"
```

---

### Task 4: Wire into `live_loop.py`

**Files:**
- Modify: `live_loop.py`
- Test: `tests/test_live_loop.py`

**Interfaces:**
- Consumes: `graywind_strategy.gates.news_debate.evaluate_shadow_debate` (Task 3); `graywind_strategy.dashboard_export.log_news_debate` (Task 2); `anthropic.Anthropic` (the SDK client class).
- Produces: `process_symbol(...)` gains three new optional keyword params: `llm_client=None`, `debate_cache=None`, `debate_rows=None` — every existing positional/keyword call site is unaffected when these are omitted (same pattern as `cycle_timestamp`/`decision_rows`/etc.). `main()` constructs `llm_client` from `ANTHROPIC_API_KEY` (optional — absence does not block the cycle), and flushes `debate_rows` via `log_news_debate` in the `finally` block.

- [ ] **Step 1: Write the failing `process_symbol` tests**

Append to `tests/test_live_loop.py` (near the other `process_symbol` collector tests, e.g. after `test_process_symbol_without_decision_rows_does_not_raise`):

```python
from graywind_strategy.gates.news_debate import Verdict


def test_process_symbol_records_debate_row_when_llm_client_given():
    open_positions = {}
    fake_result = {
        "vader_score": 0.1, "vader_gate_result": True,
        "debate_score": 0.4, "debate_reasoning": "net bullish",
    }
    debate_rows = []
    with patch("live_loop.evaluate_shadow_debate", return_value=fake_result) as mock_debate:
        live_loop.process_symbol(
            symbol="AAPL", signal="hold", current_price=150.0, today=date(2024, 1, 8),
            open_positions=open_positions, equity=10000.0,
            pdt_throttle=MagicMock(can_open_day_trade=lambda *a, **kw: True),
            position_sizer=MagicMock(), drawdown_breaker_ok=True, fred_api_key="k",
            news_client=object(), finnhub_api_key="k", trading_client=MagicMock(),
            drawdown_breaker=MagicMock(),
            cycle_timestamp="2026-08-27T10:00:00-04:00",
            llm_client=object(), debate_cache={}, debate_rows=debate_rows,
        )

    mock_debate.assert_called_once()
    assert debate_rows == [{
        "timestamp": "2026-08-27T10:00:00-04:00", "symbol": "AAPL", **fake_result,
    }]


def test_process_symbol_debate_exception_does_not_block_real_decision_or_propagate():
    open_positions = {}
    with patch("live_loop.evaluate_shadow_debate", side_effect=RuntimeError("rate limited")), \
         patch("live_loop.decide_trade", return_value=TradeDecision(action="hold", reason="no buy signal")) as mock_decide:
        # Must not raise -- the whole point of fail-open.
        live_loop.process_symbol(
            symbol="AAPL", signal="buy", current_price=150.0, today=date(2024, 1, 8),
            open_positions=open_positions, equity=10000.0,
            pdt_throttle=MagicMock(can_open_day_trade=lambda *a, **kw: True),
            position_sizer=MagicMock(), drawdown_breaker_ok=True, fred_api_key="k",
            news_client=object(), finnhub_api_key="k", trading_client=MagicMock(),
            drawdown_breaker=MagicMock(),
            llm_client=object(), debate_cache={}, debate_rows=[],
        )

    mock_decide.assert_called_once()  # the real decision still ran


def test_process_symbol_skips_debate_entirely_when_llm_client_not_given():
    open_positions = {}
    with patch("live_loop.evaluate_shadow_debate") as mock_debate, \
         patch("live_loop.decide_trade", return_value=TradeDecision(action="hold", reason="no buy signal")):
        live_loop.process_symbol(
            symbol="AAPL", signal="hold", current_price=150.0, today=date(2024, 1, 8),
            open_positions=open_positions, equity=10000.0,
            pdt_throttle=MagicMock(can_open_day_trade=lambda *a, **kw: True),
            position_sizer=MagicMock(), drawdown_breaker_ok=True, fred_api_key="k",
            news_client=object(), finnhub_api_key="k", trading_client=MagicMock(),
            drawdown_breaker=MagicMock(),
        )

    mock_debate.assert_not_called()


def test_process_symbol_does_not_debate_an_already_held_position():
    open_positions = {"AAPL": {
        "entry_price": 100.0, "shares": 5, "stop": 90.0, "target": 130.0,
        "opened_date": "2024-01-05",
    }}
    with patch("live_loop.evaluate_shadow_debate") as mock_debate:
        live_loop.process_symbol(
            symbol="AAPL", signal="hold", current_price=110.0, today=date(2024, 1, 8),
            open_positions=open_positions, equity=10000.0,
            pdt_throttle=MagicMock(), position_sizer=MagicMock(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(),
            finnhub_api_key="k", trading_client=MagicMock(), drawdown_breaker=MagicMock(),
            llm_client=object(), debate_cache={}, debate_rows=[],
        )

    mock_debate.assert_not_called()
```

Check imports at the top of `tests/test_live_loop.py` already include `date` (from `datetime`), `MagicMock`, `patch`, `TradeDecision` — add `from graywind_strategy.gates.news_debate import Verdict` only if a test above ends up needing the real dataclass (the tests as written use plain dicts for `fake_result`, so this import is unnecessary — remove that import line from the test file if included, to avoid an unused-import lint flag).

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -v -k debate`
Expected: FAIL — `TypeError: process_symbol() got an unexpected keyword argument 'llm_client'` (and `AttributeError`/`ImportError` on `live_loop.evaluate_shadow_debate` not existing yet).

- [ ] **Step 3: Wire `process_symbol()` and imports in `live_loop.py`**

Add to the imports near the top of `live_loop.py` (alongside the existing `graywind_strategy` imports):

```python
import anthropic

from graywind_strategy.gates.news_debate import evaluate_shadow_debate
from graywind_strategy.dashboard_export import write_cycle_export, log_news_debate
```

(This replaces the single existing `from graywind_strategy.dashboard_export import write_cycle_export` line — extend it rather than duplicating the import.)

Change `process_symbol`'s signature (currently ending `rsi=None, sma_fast=None, sma_slow=None, decision_rows=None):`) to:

```python
def process_symbol(symbol, signal, current_price, today, open_positions, equity,
                    pdt_throttle, position_sizer, drawdown_breaker_ok,
                    fred_api_key, news_client, finnhub_api_key, trading_client,
                    drawdown_breaker, cycle_timestamp=None, cycle_trades=None,
                    symbol_statuses=None, tier_pools=None,
                    rsi=None, sma_fast=None, sma_slow=None, decision_rows=None,
                    llm_client=None, debate_cache=None, debate_rows=None):
```

Update the docstring's closing paragraph (after the existing `pending_same_day_trades` paragraph) by adding:

```
    `llm_client`/`debate_cache`/`debate_rows` are the shadow-mode
    news-debate collectors -- when `llm_client` is None (the
    ANTHROPIC_API_KEY-not-set case), the debate step is skipped entirely,
    identical to behavior before these parameters existed. When given,
    a debate-call failure (network, malformed structured output) is caught
    here and never propagates or affects the real buy/sell/hold decision
    below -- shadow mode fails open, the opposite of every real gate in
    this file. Runs only in the same branch as the real decide_trade()
    call (mirrors "alongside the existing news_client usage" -- an
    already-held position never reaches this branch and is never debated
    either, matching decide_trade()'s own skip-if-holding scope), but
    independently of decide_trade()'s own signal/gate short-circuiting --
    it always fetches and scores headlines when reached, so the shadow log
    accumulates a verdict for every symbol/cycle this branch runs, not
    just the subset where VADER's gate happened to run live.
```

Inside the `if position is None:` block, immediately before the existing `decision = decide_trade(...)` call, insert:

```python
        if llm_client is not None:
            try:
                debate_result = evaluate_shadow_debate(
                    llm_client=llm_client, news_client=news_client, symbol=symbol,
                    as_of_date=today, cache=debate_cache if debate_cache is not None else {},
                )
                if debate_rows is not None:
                    debate_rows.append({
                        "timestamp": cycle_timestamp, "symbol": symbol, **debate_result,
                    })
            except Exception as exc:
                print(f"{symbol}: news debate shadow-mode error, skipping this cycle's row: {exc}",
                      file=sys.stderr)

```

- [ ] **Step 4: Run to verify the `process_symbol` tests pass**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -v -k debate`
Expected: 4 PASS

Run the full file to confirm no regressions from the signature change:
Run: `.venv/bin/python -m pytest tests/test_live_loop.py -v`
Expected: all PASS.

- [ ] **Step 5: Write the failing `main()` tests for optional `llm_client` construction**

Append to `tests/test_live_loop.py`:

```python
def test_main_constructs_llm_client_when_anthropic_key_set():
    fake_account = MagicMock()
    fake_account.equity = "10000.0"
    fake_trading_client = MagicMock()
    fake_trading_client.get_account.return_value = fake_account
    fake_trading_client.get_all_positions.return_value = []
    fake_state = {"day_trade_dates": [], "day": None, "starting_equity": None, "open_positions": {}}

    with patch("live_loop.is_market_hours", return_value=True), \
         patch.dict(os.environ, {
             "ALPACA_API_KEY": "k", "ALPACA_API_SECRET": "k",
             "FRED_API_KEY": "k", "FINNHUB_API_KEY": "k",
             "ANTHROPIC_API_KEY": "fake-anthropic-key",
         }), \
         patch("live_loop.TradingClient", return_value=fake_trading_client), \
         patch("live_loop.StockHistoricalDataClient"), \
         patch("live_loop.NewsClient"), \
         patch("live_loop.anthropic.Anthropic") as mock_anthropic_ctor, \
         patch("live_loop.load_state", return_value=fake_state), \
         patch("live_loop.save_state"), \
         patch("live_loop.load_tier_pools", return_value={1: 0.0, 2: 0.0, 3: 0.0}), \
         patch("live_loop.save_tier_pools"), \
         patch("live_loop.load_rebalance_state", return_value={"last_rebalance_month": None}), \
         patch("live_loop.save_rebalance_state"), \
         patch("live_loop.fetch_bars", return_value=[]), \
         patch("live_loop.append_decision_log"), \
         patch("live_loop.log_news_debate") as mock_log_news_debate, \
         patch("live_loop.write_cycle_export"):
        result = live_loop.main()

    assert result == 0
    mock_anthropic_ctor.assert_called_once_with(api_key="fake-anthropic-key")
    mock_log_news_debate.assert_called_once()
    assert mock_log_news_debate.call_args.args[0] == []  # no symbols processed (fetch_bars -> [])


def test_main_skips_llm_client_construction_when_anthropic_key_unset():
    fake_account = MagicMock()
    fake_account.equity = "10000.0"
    fake_trading_client = MagicMock()
    fake_trading_client.get_account.return_value = fake_account
    fake_trading_client.get_all_positions.return_value = []
    fake_state = {"day_trade_dates": [], "day": None, "starting_equity": None, "open_positions": {}}

    with patch("live_loop.is_market_hours", return_value=True), \
         patch.dict(os.environ, {
             "ALPACA_API_KEY": "k", "ALPACA_API_SECRET": "k",
             "FRED_API_KEY": "k", "FINNHUB_API_KEY": "k",
         }, clear=False), \
         patch("live_loop.TradingClient", return_value=fake_trading_client), \
         patch("live_loop.StockHistoricalDataClient"), \
         patch("live_loop.NewsClient"), \
         patch("live_loop.anthropic.Anthropic") as mock_anthropic_ctor, \
         patch("live_loop.load_state", return_value=fake_state), \
         patch("live_loop.save_state"), \
         patch("live_loop.load_tier_pools", return_value={1: 0.0, 2: 0.0, 3: 0.0}), \
         patch("live_loop.save_tier_pools"), \
         patch("live_loop.load_rebalance_state", return_value={"last_rebalance_month": None}), \
         patch("live_loop.save_rebalance_state"), \
         patch("live_loop.fetch_bars", return_value=[]), \
         patch("live_loop.append_decision_log"), \
         patch("live_loop.log_news_debate") as mock_log_news_debate, \
         patch("live_loop.write_cycle_export"):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        result = live_loop.main()

    assert result == 0
    mock_anthropic_ctor.assert_not_called()
    mock_log_news_debate.assert_called_once()
    assert mock_log_news_debate.call_args.args[0] == []
```

- [ ] **Step 6: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -v -k anthropic_key`
Expected: FAIL — `AttributeError: <module 'live_loop'> does not have the attribute 'anthropic'` (and `log_news_debate` not called since it isn't wired into `main()` yet).

- [ ] **Step 7: Wire `main()` in `live_loop.py`**

In `main()`, right after the existing key-reads (`api_key`/`api_secret`/`fred_api_key`/`finnhub_api_key`) and their `all([...])` check — do **not** add `ANTHROPIC_API_KEY` to that `all([...])` list, its absence must not block the cycle — add:

```python
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
```

Right after the existing `news_client = NewsClient(api_key, api_secret)` line, add:

```python
    llm_client = anthropic.Anthropic(api_key=anthropic_api_key) if anthropic_api_key else None
```

Right after the existing `decision_rows = []` line, add:

```python
    debate_cache = {}
    debate_rows = []
```

In the `process_symbol(...)` call inside the `for symbol in WATCHLIST:` loop, add three new kwargs at the end of the call (after `decision_rows=decision_rows,`):

```python
                    llm_client=llm_client, debate_cache=debate_cache, debate_rows=debate_rows,
```

In the `finally:` block, right after the existing `append_decision_log(decision_rows, state_dir=state_dir)` line, add:

```python
        log_news_debate(debate_rows)
```

- [ ] **Step 8: Run to verify all `live_loop.py` tests pass**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -v`
Expected: all PASS (pre-existing tests unaffected: they don't set `ANTHROPIC_API_KEY`, so `llm_client` stays `None` and `debate_rows` stays `[]`, making `log_news_debate([])` a true no-op — no disk writes, no behavior change. Confirmed safe because Task 2's `log_news_debate` no-ops on an empty list without touching the filesystem.)

- [ ] **Step 9: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all PASS, count = 357 (baseline) + 10 (Task 1) + 6 (Task 3) + 5 (Task 2) + 6 (Task 4 process_symbol/main tests) = 384.

- [ ] **Step 10: Commit**

```bash
git add live_loop.py tests/test_live_loop.py
git commit -m "feat: wire news-debate shadow logging into live_loop.py process_symbol/main"
```

---

## Self-Review Notes (for the plan author, already applied above)

- **Spec coverage:** Component 1 (news_debate.py, 3 Claude calls) -> Task 1. Component 2 (per-cycle cache) -> Task 3. Component 3 (shadow logging, dashboard_export.py) -> Task 2. Component 4 (wiring into live_loop.py, additive) -> Task 4. Error handling (fails open) -> Task 4 Step 3 (try/except in process_symbol). Testing section's four bullets -> Tasks 1, 2, 3, 4 respectively; "no test makes a real Claude API call" -> every test uses `MagicMock`, verified by construction (no test imports/constructs a real `anthropic.Anthropic()` with a real key). requirements.txt/.env.example -> Task 1 Step 1.
- **Explicitly NOT touched, verified:** no task modifies `sentiment_gate.py`, `pipeline.py`, or `backtester.py`; `decide_trade()`'s call site in `live_loop.py` is untouched (only new code is inserted *before* it, not into it).
- **Type consistency check:** `evaluate_shadow_debate`'s return dict keys (`vader_score, vader_gate_result, debate_score, debate_reasoning`) match `NEWS_DEBATE_LOG_FIELDS` (minus `timestamp`/`symbol`, which `process_symbol` adds) and match the dict `log_news_debate` expects per row. `Verdict.score`/`Verdict.reasoning` match what `judge_verdict` constructs and what `evaluate_shadow_debate` reads (`verdict.score`, `verdict.reasoning`). `process_symbol`'s new params (`llm_client`, `debate_cache`, `debate_rows`) match exactly what `main()` passes and what the Task 4 tests exercise.
