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
explicitly disabled on these calls (`thinking={"type": "disabled"}`): this
is a deliberate cost/latency choice, not a forced API workaround -- these
calls fire on every symbol/cycle of a 15-minute market-hours cron purely to
accumulate shadow history, so the extra latency/cost of extended thinking
buys nothing for a call that never gates anything time-sensitive. Revisit
if this debate is ever promoted to authoritative.

`llm_client` is injected on every function here (same shape as
`news_client` throughout this codebase) -- tests always pass a MagicMock
and never make a real API call.
"""
from dataclasses import dataclass

from graywind_strategy.gates.sentiment_gate import (
    fetch_recent_headlines,
    sentiment_gate,
    sentiment_score,
)

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
        "strict": True,
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
        "strict": True,
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
        "strict": True,
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

    Note: the returned `vader_score`/`vader_gate_result` are RECOMPUTED
    here independently (a fresh fetch_recent_headlines + sentiment_score
    call) -- they are NOT copied from whatever decide_trade()'s own
    sentiment gate actually saw/decided that cycle. A reader of
    news_debate_log.csv should not treat these two fields as a literal
    record of the live gate's decision, especially on a cycle where an
    earlier gate (e.g. vix) short-circuited decide_trade() before its own
    sentiment gate ever ran.
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
