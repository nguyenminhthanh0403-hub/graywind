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
