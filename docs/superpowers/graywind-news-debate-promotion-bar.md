# Graywind — News-Debate Shadow-to-Authoritative Promotion Bar

**Date:** 2026-08-31

**Why this doc exists:** audit item #7
(`graywind-real-capital-readiness-handoff.md`). The LLM news-debate gate
(`graywind_strategy/gates/news_debate.py`) is correctly isolated in shadow mode — it has
no code path into `pipeline.py::decide_trade()` and cannot affect a trade today. But no
written criterion exists for *when* it would ever be promoted to gate real trades. The
bar is being written now, while there is no deadline pressure to define it under. A
promotion bar invented later, in the moment someone wants to promote it, is not a bar.

---

## The bar

The debate gate may be promoted from shadow to authoritative **only when all four hold**:

1. **Volume.** At least **50 shadow-logged decisions** across at least **20 distinct
   trading days**. Fewer than this cannot separate skill from noise on a
   two-outcome-per-trade signal.
2. **It disagrees enough to matter.** The debate verdict must differ from the VADER
   `sentiment_gate` verdict on **≥20% of logged decisions**. If it agrees with VADER
   almost always, it is an expensive re-implementation of a free lexicon scorer and
   should be deleted, not promoted.
3. **It wins on the disagreements.** Restricted to the subset where debate and VADER
   disagree, trades aligned with the debate verdict must show **higher realized P&L per
   trade** than trades aligned with the VADER verdict, by a margin exceeding the standard
   error of the difference. Agreement cases carry no information about which gate is
   better and must be excluded from the comparison.
4. **Cost is justified.** Measured Anthropic API spend per additional dollar of realized
   P&L attributable to the debate gate must be positive. See
   `archive/graywind-news-debate-provider-cost-handoff.md`.

**Failing criterion 2 or 3 means delete the gate, not tune it.** A shadow gate that never
earns promotion is a successful experiment with a negative result, and removing it is the
correct outcome.

---

## Two blockers that make this bar uncomputable today

Both were found by inspecting the live repo, not inferred. Neither is a reason to weaken
the bar; both are prerequisites to ever evaluating it.

### Blocker 1 — no data is being collected, and the owner has ruled out paying to fix it

**Owner decision, 2026-08-31: `ANTHROPIC_API_KEY` will NOT be set — paying Anthropic for
this feature is too costly.** That closes option 1 of the three in
`archive/graywind-news-debate-provider-cost-handoff.md` (keep `claude-sonnet-5`, ~$10–20/month).
The consequence is that **no shadow data will accumulate at all** until a cheaper provider
is wired in, so the promotion bar above is currently unreachable — not failing, just
never evaluated.

**Evidence that narrows the remaining two options** (gathered 2026-08-31 while trying to
use OpenRouter's free tier for an unrelated task): OpenRouter has been withdrawing its
free model catalog. Five commonly-used `:free` slugs — DeepSeek V3.1, Llama 3.3 70B,
Qwen3 235B, Gemma 3 27B, Mistral Small 3.2 — every one returned
`404: "This model is unavailable for free. The paid version is available now"`. The only
still-routable free model was rate-limited upstream (`429`).

This materially weakens **option 2** ("fully free via OpenRouter"), which assumed a stable
free catalog and a $10 top-up unlocking 1,000 free requests/day. A feature needing ~156
calls/day cannot be built on models that are being retired without notice — and if it
silently stops logging, the failure looks exactly like today's: an empty log nobody
notices.

**Therefore the recommendation is option 3** — DeepSeek via OpenRouter, paid, ~$2–3/month.
It is roughly an order of magnitude cheaper than the rejected Anthropic option, uses an
OpenRouter key already wired into this repo's secrets, and does not depend on a free tier
that is actively disappearing. The code change is the same one option 2 would need
(`news_debate.py::_tool_call()` plus `live_loop.py`'s client wiring for OpenRouter's
request/response shape).

**Until that is done, treat the news-debate gate as dormant, not merely un-promoted.**
The honest alternative, if ~$2–3/month is also unwanted, is to delete the shadow path
rather than leave code that looks active and logs nothing.

### The original blocker detail

`dashboard-data/news_debate_log.csv` **does not exist anywhere in `origin/main`'s tree**,
despite the shadow gate having shipped 2026-08-28 and the live cron having run many
cycles since.

The cause is near-certainly an unset GitHub secret. `.github/workflows/live-trading.yml`
references `ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}` (lines 53 and 211), but
an unset secret expands to the empty string, and `live_loop.py:394` reads it with
`os.environ.get("ANTHROPIC_API_KEY")`. Empty string is falsy, so the debate step is
skipped and the cycle proceeds normally — by design (the key is documented as optional),
but **silently**. Nothing alerts on it.

This is the exact failure shape recorded elsewhere in this project's history: an unset CI
secret expanding to `""` and failing quietly forever rather than loudly once.

**Required action before the bar can ever be evaluated** (note the Anthropic option is
closed — see the owner decision above; these are the two remaining paths):
- **Wire a cheaper provider** (the option-3 recommendation), **or** consciously decide the
  debate experiment is not being run and remove the dead code path rather than leaving it
  looking active. Leaving it as-is is not a third option — it is the current state, and it
  produces nothing.
- Then verify from the run side, not the code side: after a market-hours cycle, confirm
  `dashboard-data/news_debate_log.csv` exists on `origin/main` and is gaining rows.
  Reading the workflow file is not verification that it ran.

### Blocker 2 — the log schema cannot express the comparison

Criterion 3 needs realized P&L attributed to each gate's verdict. Neither log carries it:

| File | Fields | Missing |
|---|---|---|
| `news_debate_log.csv` (`NEWS_DEBATE_LOG_FIELDS`) | timestamp, symbol, vader_score, vader_gate_result, debate_score, debate_reasoning | any trade outcome |
| `trade_log.csv` (`TRADE_FIELDS`) | timestamp, symbol, side, qty, price, reason | realized P&L — it records **fills**, not round-trips |

So computing the bar requires a two-step derivation, not a schema field:
1. Pair buy fills to their closing sell fills per symbol in `trade_log.csv` to produce
   realized per-round-trip P&L.
2. Join those round-trips back to `news_debate_log.csv` on `(symbol, timestamp)`, matching
   each entry to the debate verdict logged in the cycle that opened it.

**This analysis script is deliberately NOT built yet** — with zero rows collected there is
nothing to run it against, and building it now would mean writing an unrunnable,
untestable joiner. It is deferred, not ready. When Blocker 1 is cleared and rows begin
accumulating, add `scripts/analyze_news_debate_shadow.py` following the existing
`scripts/generate_performance_report.py` pattern (reads `dashboard-data/` CSVs, prints a
report), with tests following `tests/test_generate_performance_report.py`'s
fixture-CSV style.

---

## Status

The bar above is written and binding. It cannot be evaluated until Blocker 1 is cleared;
it cannot be computed until Blocker 2's script exists. Promotion before both are resolved
is not permitted regardless of how good the debate reasoning looks by eye — reading
plausible LLM justifications is not evidence, which is the entire reason this gate was
built in shadow mode.

## Related

- `docs/superpowers/graywind-news-debate-shadow-mode-handoff.md` — how shadow mode works.
- `docs/superpowers/archive/graywind-news-debate-provider-cost-handoff.md` — cost side of criterion 4.
- `docs/superpowers/graywind-real-capital-done-criteria.md` — the project's stopping rules.
