# Graywind × Bullion Macro-Event Debate — Session Handoff

**Written:** 2026-09-13. **For:** a fresh session checking in on the Bullion macro-event
shadow debate (a second, independent shadow-mode LLM signal, sibling to the existing
per-symbol `news_debate.py`), or debugging why `dashboard-data/macro_debate_log.csv` doesn't
exist yet.

## Goal

Read Bullion's market-wide news feed (`news.json` — Fed policy, geopolitics, macro
headlines; not per-symbol) once per trading cycle, make one forced-structured-output
DeepSeek call, and log a small set of probability-weighted event readings
(`event`/`probability`/`implication`) to a new CSV for later human review. Like
`news_debate.py`, this **never gates a trade** — `pipeline.py::decide_trade()` has no path
into it. VADER and the existing `macro_gate.py` breach-count gate are unaffected.

All 5 implementation tasks (1-5 of the 6-task plan) are **code-complete and committed** on
this feature branch. Task 6 (this handoff) is the last task in the plan. The feature has
**two independent blockers** before it will ever log a real row in production — see "What
has failed / risks / caveats" below; neither is a defect in this branch's code.

- Spec (binding authority): `docs/superpowers/specs/2026-09-12-graywind-bullion-macro-debate-design.md`
- Plan (5 of 6 tasks executed; this doc is Task 6): `docs/superpowers/plans/2026-09-12-graywind-bullion-macro-debate.md`

## How to resume (do this first)

1. **Location:** this work lives on branch `graywind-bullion-macro-debate`, checked out in
   the worktree `/Users/thanhnguyen/Projects/graywind/.worktrees/graywind-bullion-macro-debate`
   (confirmed via `git worktree list` — the primary checkout at
   `/Users/thanhnguyen/Projects/graywind` is on `main`, a different, earlier tip).
2. **This branch is NOT merged and NOT pushed.** `git log --oneline origin/main..HEAD`
   (run in this worktree) shows 8 commits ahead of `origin/main`, newest first:
   `dfa5e12` (wire into `live_loop.py` — Task 5), `8ab9d58` (`log_macro_debate` — Task 4),
   `1522e5f` (`evaluate_macro_debate` orchestration — Task 3), `245c7be` (DeepSeek
   structured call — Task 2), `d851638` (`fetch_bullion_headlines` + staleness guard —
   Task 1), `f26848f` (spec + plan docs), then `9a4dc0f` and `4bf19bf` — these last two are
   **not** part of this feature; they're pre-existing commits on local `main` that are
   themselves ahead of `origin/main` (unrelated tier-2/3 settlement + code-review fixes,
   not yet pushed by an earlier session). So: local `main` was already 2 commits ahead of
   `origin/main` when this branch forked from it, and this branch adds 6 more on top (soon
   7, once this handoff is committed). Confirm current state with
   `git log --oneline origin/main..HEAD` before assuming anything is live.
3. Run the test suite from this worktree: `.venv/bin/python -m pytest tests/ -q` — expect
   `524 passed` (verified fresh in this session, 2026-09-13, no `anthropic`/DeepSeek install
   step needed — `openai` and `requests` are both already in `requirements.txt` and already
   installed in this worktree's `.venv`).
4. **Immediate next action — check both blockers before assuming either is fixed:**
   - `gh secret list --repo nguyenminhthanh0403-hub/graywind` (this worked directly in this
     session, unauthenticated-401 caveat below does NOT apply to `gh secret list` itself,
     only to the raw REST endpoint) — confirm whether `DEEPSEEK_API_KEY` has been added.
     As of 2026-09-13 it is **absent** (list showed only `ALPACA_API_KEY`,
     `ALPACA_API_KEY_SMALL`, `ALPACA_API_SECRET`, `ALPACA_API_SECRET_SMALL`,
     `CLOUDFARE_API_KEY`, `FINNHUB_API_KEY`, `FRED_API_KEY` — no `DEEPSEEK_API_KEY`).
   - `curl -s https://nguyenminhthanh0403-hub.github.io/claudekit/bullion-live-map/news.json`
     and inspect `generated_at` — see the staleness finding below; as of 2026-09-13 it is
     still stuck at `2026-09-05T00:02:31Z`, unchanged from the plan's own 2026-09-12
     research.

## Current state (active files)

- `graywind_strategy/gates/macro_debate.py` (new module, Tasks 1-3): `MacroNewsUnavailable`
  exception; `BULLION_NEWS_URL`; `STALENESS_CEILING_HOURS = 48`;
  `fetch_bullion_headlines(session=requests) -> list[dict]`; `MacroEvent` dataclass
  (`event`, `probability`, `implication`); `evaluate_macro_events(llm_client, headlines) ->
  list[MacroEvent]` (one forced-tool-choice DeepSeek call, `extra_body={"thinking":
  {"type": "disabled"}}`, same discipline as `news_debate.py::_tool_call`);
  `evaluate_macro_debate(llm_client, session=requests) -> list[dict]` (orchestration —
  fetch then evaluate, raises on any failure, does not catch anything itself).
- `graywind_strategy/dashboard_export.py` (extended, Task 4): `MACRO_DEBATE_LOG_FILENAME =
  "macro_debate_log.csv"`; `MACRO_DEBATE_LOG_FIELDS = ["timestamp", "event", "probability",
  "implication"]`; `log_macro_debate(rows, dashboard_dir=DEFAULT_DASHBOARD_DIR)` — same
  append-forever, header-once, no-op-on-empty semantics as `log_news_debate`.
- `live_loop.py` (wired, Task 5): imports `evaluate_macro_debate` (line 48) and
  `log_macro_debate` (line 51, added to the existing `dashboard_export` import); new
  standalone function `run_macro_debate_cycle(llm_client, cycle_timestamp,
  macro_debate_rows)` (line 254, right before `process_symbol`) — fails open, catches any
  exception, prints `macro debate shadow-mode error, skipping this cycle's row: {exc}` to
  stderr, appends nothing on failure; `macro_debate_rows = []` initialized alongside
  `debate_rows = []` (line 910); called once per cycle, gated on `if llm_client is not
  None:` (line 1021), before the per-symbol `for symbol in WATCHLIST:` loop — deliberately
  outside it, since Bullion's feed is market-wide, not per-symbol; `log_macro_debate(...)`
  called alongside `log_news_debate(...)` inside the same already-guarded `try:` block
  (verified present at the call site added in `dfa5e12`).
- `tests/test_macro_debate.py` (new, Tasks 1-3): 10 tests covering fetch/staleness,
  structured-call parsing + forced-tool/thinking-disabled assertions, and orchestration
  (including that returned dicts carry no `timestamp` key).
- `tests/test_dashboard_export.py` (extended, Task 4): 2 new tests for `log_macro_debate`
  round-trip and no-op-on-empty.
- `tests/test_live_loop.py` (extended, Task 5): 2 new tests for `run_macro_debate_cycle`
  (success appends timestamped rows; exception is swallowed and appends nothing).
- **Not created yet:** `dashboard-data/macro_debate_log.csv` does not exist in this worktree
  — confirmed via `ls dashboard-data/`. Expected: no real cycle has run this code yet (see
  blockers below).

**Not mine — leave alone:** the sibling worktrees `.claude/worktrees/agent-ac1e2a7ec9b70e6e3`
and `.claude/worktrees/graywind-yahoo-analyst-consensus` under the primary checkout (per the
2026-08-28 news-debate handoff, still true); anything under `state/small` or
`dashboard-data/small` (the separate small-account pipeline, unrelated to this feature).

## What has changed

Since the plan was written (`f26848f`, 2026-09-12), all 5 implementation tasks were executed
in order, one commit per task, matching the plan's own task numbering exactly:

- `d851638` — Task 1: `fetch_bullion_headlines` + staleness guard.
- `245c7be` — Task 2: `evaluate_macro_events` (structured DeepSeek call).
- `1522e5f` — Task 3: `evaluate_macro_debate` (orchestration).
- `8ab9d58` — Task 4: `log_macro_debate` (dashboard CSV export).
- `dfa5e12` — Task 5: `live_loop.py` wiring.

No deviation from the plan's specified code was needed — no fix-wave commits, unlike the
news-debate feature's history (which needed a post-review fix wave, see that handoff for
context). Full suite run fresh this session: `524 passed` (up from whatever the count was
before this branch — the plan added ~14 new tests across the 5 tasks; exact prior baseline
not re-derived here, not needed for this handoff's purpose).

## What has failed / risks / caveats

- **Bullion's `news.json` feed is confirmed stale, past this feature's own 48h ceiling —
  a Bullion-side blocker, not a Graywind one.** The plan's own 2026-09-12 research found
  `generated_at: 2026-09-05` when checked that day — 7 days stale. Re-checked independently
  in this session on 2026-09-13: **still** `generated_at: 2026-09-05T00:02:31Z` — now 8
  days stale, and identical to the byte down to the second from the plan's finding a day
  earlier. That the value hasn't moved at all in a full day is itself evidence Bullion's
  news cron is not merely lagging but not running — not a slow producer, a dead one. Until
  Bullion's news cron is fixed, `fetch_bullion_headlines` will raise
  `MacroNewsUnavailable` on essentially every real cycle, and
  `dashboard-data/macro_debate_log.csv` will not gain rows. This is expected fail-open
  behavior, not a bug in this feature — but it means the feature is effectively dormant on
  ship, same shape as the original `news_debate.py` launch being blocked on a missing
  secret. **This is a Bullion-side blocker; nothing in this branch's code can fix it.**
- **Second, independent blocker, verified this session, and strictly upstream of the one
  above: `DEEPSEEK_API_KEY` is not set as a repo secret.** `gh secret list --repo
  nguyenminhthanh0403-hub/graywind` (ran successfully in this session — see "Verification
  idioms" below for why this differs from the sibling handoff's claim that `gh` isn't
  available) returned `ALPACA_API_KEY`, `ALPACA_API_KEY_SMALL`, `ALPACA_API_SECRET`,
  `ALPACA_API_SECRET_SMALL`, `CLOUDFARE_API_KEY`, `FINNHUB_API_KEY`, `FRED_API_KEY` — no
  `DEEPSEEK_API_KEY`. Per `live_loop.py`'s own docstring and `llm_client` construction
  (around line 895-901), when `DEEPSEEK_API_KEY` is unset, `llm_client` stays `None`, and
  `run_macro_debate_cycle` is gated on `if llm_client is not None:` (line 1021) — **it is
  never even called in production today.** This means the Bullion staleness check above
  never gets a chance to run at all right now; both blockers must clear independently
  before a single row can appear. This secret is shared with `news_debate.py` (the DeepSeek
  swap for that feature happened 2026-09-02, per project memory) — fixing it for one
  feature fixes it for both.
- **The sibling handoff (`graywind-news-debate-shadow-mode-handoff.md`, 2026-08-28) is
  stale on this exact point** — it refers to `ANTHROPIC_API_KEY` and `pip install
  anthropic`, both superseded by the 2026-09-02 DeepSeek swap. Do not follow that document's
  secret name or install step for either feature; use `DEEPSEEK_API_KEY` and the already-
  installed `openai` package. (Not fixing that file here — out of scope for this task; flagging
  so a resuming session doesn't act on the stale name.)
- **No live smoke test against the real DeepSeek API or the real Bullion feed has
  happened.** All 14 new tests mock both the HTTP call (`session.get`) and the LLM client
  (`fake_client.chat.completions.create`) — same caveat pattern as `news_debate.py`'s own
  handoff history at launch.
- **This branch is unmerged and unpushed** (see "How to resume" #2) — a resuming session
  should not assume any of this code is live in production until it's merged to `main` and
  pushed to `origin/main`.
- **DEFERRED BY DESIGN (per spec's "Deferred, not forgotten"), not a defect:** no promotion
  bar for this signal (mirroring `graywind-news-debate-promotion-bar.md`) — deliberately not
  written yet, since writing one before a single row exists would invent criteria with
  nothing to check them against. Also deferred: fixing Bullion's cron (belongs to the
  Bullion project, not this one) and any comparison/analysis script.

## What's next (ordered)

1. **Add the `DEEPSEEK_API_KEY` GitHub Actions repo secret** (manual, human-only step,
   shared with `news_debate.py`) — without this, `run_macro_debate_cycle` never executes at
   all, regardless of Bullion's feed state.
2. **Separately, check whether Bullion's news cron has been fixed:**
   `curl -s https://nguyenminhthanh0403-hub.github.io/claudekit/bullion-live-map/news.json`
   and inspect `generated_at` — it needs to be within `STALENESS_CEILING_HOURS` (48h) of
   the check time. Both #1 and #2 must be true before a row can appear; neither alone is
   sufficient.
3. Once both are true, trigger a `workflow_dispatch` run of `live-trading.yml` during market
   hours (13:30-20:00 UTC on a weekday) and confirm `dashboard-data/macro_debate_log.csv`
   gains rows; scan the Actions run log for any `macro debate shadow-mode error` warnings
   (the fail-open catch's message) even on a run that does log rows, in case some events
   partially succeed.
4. Merge this branch to `main` and push to `origin/main` — not done as part of this plan's
   6 tasks; use `superpowers:finishing-a-development-branch` when ready.
5. Let shadow-mode history accumulate once rows start landing; revisit the deferred
   promotion bar only once `dashboard-data/macro_debate_log.csv` has real history to check
   criteria against.

## Verification idioms used in this project (for the resuming session)

- Test suite: `.venv/bin/python -m pytest tests/ -q` — `524 passed` as of this session, no
  extra install steps needed (`openai`/`requests` already in `requirements.txt` and already
  in this worktree's `.venv`).
- **Checking real repo secrets (names only, never values):** `gh secret list --repo
  nguyenminhthanh0403-hub/graywind` **worked directly in this session** (`gh` CLI is
  installed and authenticated in this environment) — this corrects the sibling
  `news_debate.py` handoff's claim that `gh` isn't available; that claim was true in
  whatever environment wrote that handoff, not in this one. Try `gh secret list` first;
  fall back to asking the user to read the GitHub UI directly only if `gh` errors out
  (the unauthenticated REST secrets-list endpoint still 401s either way).
- Bullion feed staleness check: `curl -s
  https://nguyenminhthanh0403-hub.github.io/claudekit/bullion-live-map/news.json | head -c
  400` and read the `generated_at` field directly — no auth needed, public GitHub Pages URL.
- GitHub Actions run/job/step history (works unauthenticated, public repo):
  ```
  curl -s "https://api.github.com/repos/nguyenminhthanh0403-hub/graywind/actions/workflows/live-trading.yml/runs?per_page=50"
  curl -s "https://api.github.com/repos/nguyenminhthanh0403-hub/graywind/actions/runs/<run_id>/jobs"
  ```
- Ahead/behind state against `origin/main`: `git log --oneline origin/main..HEAD` from
  inside the relevant worktree — don't assume `main == origin/main` without checking; this
  session found local `main` itself 2 commits ahead of `origin/main`, unrelated to this
  feature.
- Before starting related work, check `git branch -a` / `git worktree list` / `git log --all
  --oneline` for unmerged work — this repo has a documented history of stale unmerged
  branches and multiple concurrent worktrees.
