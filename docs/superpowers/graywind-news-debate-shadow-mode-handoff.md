# Graywind News-Debate Shadow Mode — Session Handoff

**Written:** 2026-08-27 (supersedes the 2026-08-25 handoff of the same name — this
sub-project is now SHIPPED, not "not yet started as of resume"). **For:** a fresh session
checking in on sub-project 3 of 3 of the capital-scaling redesign, or debugging why
`dashboard-data/news_debate_log.csv` is empty in production.

## Goal

Add a Claude-based bull/bear/judge news debate that logs a shadow-mode verdict for every
symbol/cycle next to VADER's existing sentiment score — without ever gating a trade. VADER
stays the live gate, unchanged. This is now **built, tested, reviewed, merged, and pushed to
`origin/main`** — but see "What has failed / risks / caveats" below: it cannot actually run in
production yet because the `ANTHROPIC_API_KEY` GitHub Actions secret has not been created. The
code is correct and waiting; only a manual secret-creation step remains.

- Spec (unchanged, still the binding authority): `docs/superpowers/specs/2026-08-25-graywind-news-debate-shadow-mode-design.md`
- Plan (fully executed, all 4 tasks + 1 fix wave complete): `docs/superpowers/plans/2026-08-27-graywind-news-debate-shadow-mode.md`
- Progress ledger for this plan's execution: deleted after the final review went clean (per
  `superpowers:subagent-driven-development`'s own convention — "the git history is the record
  now"). If you need the blow-by-blow (per-task review verdicts, the exact final-review findings
  list, the scoped re-review verdicts), it no longer exists as a file — reconstruct from the
  commit messages below and this handoff instead.

## How to resume (do this first)

1. Confirm branch and state: this work was done in an isolated agent worktree
   (`worktree-agent-ac1e2a7ec9b70e6e3`) and has already been fast-forward-merged into
   `origin/main` at `2723bed57675cdec4cf60254ba71ef8c12c3756d`. From any fresh checkout of
   `main`: `git log --oneline -7` should show (newest first) `2723bed` (plan doc),
   `d9c3e64` (final-review fix wave), `eab518a` (live_loop.py wiring), `45155a3`
   (evaluate_shadow_debate), `95fa50d` (log_news_debate), `59d5c89` (bull/bear/judge
   primitives), then `527e983` (the pre-existing tip this branch forked from, the
   performance-reports polish commit).
2. Run the test suite: `.venv/bin/python -m pytest tests/ -q` — expect `384 passed` (357
   baseline before this sub-project + 27 new: 10 + 5 + 5 + 6 across the four tasks, + 1
   seam-binding test added in the final-review fix wave).
3. **Immediate next action:** add the `ANTHROPIC_API_KEY` secret to this repo's GitHub Actions
   secrets (Settings → Secrets and variables → Actions). The workflow YAML already references
   `${{ secrets.ANTHROPIC_API_KEY }}` in both jobs (see below) — creating the secret is the ONLY
   remaining step to turn the feature on. This is a manual, credential-entering action outside
   what an agent session should do on its own (same category as the pre-existing
   `ALPACA_API_KEY_SMALL`/`ALPACA_API_SECRET_SMALL` secrets from the tier-allocation
   sub-project). Until it's added, `os.environ.get("ANTHROPIC_API_KEY")` returns `None` in every
   cron run, `llm_client` stays `None`, and the debate step is a clean no-op — the rest of the
   trading cycle is completely unaffected (this is the fails-open contract working as designed,
   not a bug).

## Current state (active files)

**Branch:** `worktree-agent-ac1e2a7ec9b70e6e3` (an agent-isolated worktree), 6 commits ahead of
the fork point `527e9831c8e91bd017bc8a68f1ff6c722c8f88e3`. Already fast-forward-merged and
pushed to `origin/main` — `origin/main` and this branch's `HEAD` are identical
(`2723bed57675cdec4cf60254ba71ef8c12c3756d`) as of this writing. No PR was opened; this repo's
established convention for sub-projects is direct-push-to-main after a clean final review (see
`git log` on `main` for precedent: `944abdc`, `b533ea4`, `2fa4004`, etc.).

**Files created (across `59d5c89`, `95fa50d`, `45155a3`):**
- `graywind_strategy/gates/news_debate.py` — `Verdict` dataclass; `bull_argument`,
  `bear_argument`, `judge_verdict` (forced-tool-use Claude calls, `claude-sonnet-5`, thinking
  disabled, `strict: true` schemas); `evaluate_shadow_debate` (orchestration: fetch headlines
  via `sentiment_gate.fetch_recent_headlines`, score with VADER, run/cache the debate).
- `tests/test_news_debate.py` — 16 tests, all Claude/news calls mocked (`MagicMock`), zero real
  API calls possible.

**Files modified:**
- `graywind_strategy/dashboard_export.py` — added `log_news_debate(rows,
  dashboard_dir=DEFAULT_DASHBOARD_DIR)`, `NEWS_DEBATE_LOG_FIELDS`, `NEWS_DEBATE_LOG_FILENAME`,
  `DEFAULT_DASHBOARD_DIR`. Appends to `<dashboard_dir>/news_debate_log.csv` (columns:
  `timestamp, symbol, vader_score, vader_gate_result, debate_score, debate_reasoning`),
  mirroring `state_store.py::append_decision_log`'s exact shape (list-of-rows, no-op on empty,
  header-written-once). `write_cycle_export` (pre-existing) is untouched.
- `live_loop.py` — `process_symbol()` gained three optional params (`llm_client=None,
  debate_cache=None, debate_rows=None`); every pre-existing call site is unaffected. The
  shadow-debate step runs only inside `if position is None:` (same scope as the real
  `decide_trade()` call), positioned AFTER the buy/hold decision and order submission (moved
  there in the final-review fix wave specifically so a slow/hung Claude call can never delay a
  real order), wrapped in try/except so a debate failure never propagates or blocks the real
  decision. `main()` reads `ANTHROPIC_API_KEY` (optional — never added to the fatal
  `all([...])` check that already covers the other four required keys) and
  `GRAYWIND_DASHBOARD_DIR` (optional, defaults to `"dashboard-data"`, mirrors the existing
  `GRAYWIND_STATE_DIR` pattern), constructs `llm_client = anthropic.Anthropic(api_key=...,
  timeout=20.0, max_retries=1)` only when the key is present, and flushes
  `log_news_debate(debate_rows, dashboard_dir=dashboard_dir)` — wrapped in try/except — in the
  `finally:` block, AFTER `write_cycle_export`.
- `.github/workflows/live-trading.yml` — both jobs (`live-cycle` for the 100k account,
  `live-cycle-small` for the small account) now pass `ANTHROPIC_API_KEY: ${{
  secrets.ANTHROPIC_API_KEY }}` (same secret, shared across both accounts, matching the existing
  `FRED_API_KEY`/`FINNHUB_API_KEY` sharing pattern — only the Alpaca brokerage keys are
  per-account). `live-cycle-small` additionally sets `GRAYWIND_DASHBOARD_DIR:
  dashboard-data/small` so the two accounts' shadow logs never collide.
- `requirements.txt` — added `anthropic` (unpinned, matching `pandas`/`alpaca-py`/`requests`
  style).
- `.env.example` — added `ANTHROPIC_API_KEY=your_anthropic_key_here`.
- `tests/test_dashboard_export.py`, `tests/test_live_loop.py` — extended with tests for the new
  behavior (5 and 7 new tests respectively, the latter including the fix-wave's timeout/retry
  assertion update).

**Explicitly NOT touched (per the spec, verified in every task and final review):**
- `graywind_strategy/gates/sentiment_gate.py` — byte-identical to before this sub-project.
- `graywind_strategy/pipeline.py` — `decide_trade()` has zero changes, no new parameters, no
  code path from the debate into it.
- `graywind_strategy/backtester.py` — zero changes, no debate coverage in backtests (deliberate,
  lookahead-bias risk per the spec).

**Scratch workspace / traps:**
- ⚠️ This session ran inside an isolated agent worktree
  (`/Users/thanhnguyen/Projects/graywind/.claude/worktrees/agent-ac1e2a7ec9b70e6e3`), not the
  main checkout. The sandbox refused any git command that tried to `cd`/`-C` outside that
  worktree, so "merge to main" was done by fetching `origin/main`, confirming no drift (it was
  exactly at this branch's fork point, `527e983`), and `git push origin HEAD:main` (a clean
  fast-forward, not a real 3-way merge) — rather than the more typical "checkout main, merge
  feature branch" sequence. This has the same end result but means there is no local `main`
  branch ref in this worktree that was ever moved; if you're reading this from a fresh checkout
  of `origin/main`, you're already on the right commit and none of that matters.
- ⚠️ The plan's `.superpowers/sdd/2026-08-27-graywind-news-debate-shadow-mode/` execution
  workspace (ledger, task briefs, review packages, fix-wave brief/report) was deleted after the
  final review went clean, per that skill's own convention. It is NOT recoverable — this
  handoff and `git log` are now the only record of the per-task review findings and the
  final-review fix-wave findings.
- ⚠️ A pre-existing untracked worktree at `.claude/worktrees/graywind-yahoo-analyst-consensus`
  was confirmed merged (`git merge-base --is-ancestor`) before this session started — not
  touched, not relevant to this work.

**Not mine — leave alone:** anything under `.claude/worktrees/` other than this session's own
directory; the `project-graywind-capital-redesign.md` memory file (the coordinating session
updates that itself from this handoff, per instruction — do not edit it from here).

## What has changed

- `59d5c89` — `bull_argument`/`bear_argument`/`judge_verdict`/`Verdict` in
  `graywind_strategy/gates/news_debate.py`. 10 tests, all mocked. Task review: clean, no
  Critical/Important findings.
- `95fa50d` — `log_news_debate` in `graywind_strategy/dashboard_export.py`. 5 tests. Task
  review: clean; reviewer independently line-diffed it against `append_decision_log` and
  confirmed an exact-shape match.
- `45155a3` — `evaluate_shadow_debate` orchestration + per-cycle cache, added to
  `news_debate.py`. 5 tests (the plan's own text said "6 new" due to a miscount while writing
  the plan — ruled non-blocking, the 5 tests in the plan's actual code block are the real
  requirement). Task review: clean.
- `eab518a` — wired into `live_loop.py`'s `process_symbol()`/`main()`. 6 tests. Task review:
  clean — the reviewer independently verified (by reading the live file, not just diff context)
  that `decide_trade()`/`pipeline.py` are genuinely untouched, the fail-open catch genuinely
  never lets an exception propagate, and `ANTHROPIC_API_KEY` is genuinely not in the fatal key
  check.
- Final whole-branch review (most capable model, full `527e983..eab518a` diff): **"Ready to
  merge: With fixes."** Found 1 Critical + 5 Important + 7 Minor. The Critical and most of the
  Important findings were real production gaps that four task-scoped reviews structurally could
  not have caught (each task was individually correct; the INTEGRATED result had holes at the
  seams). Specifically:
  - **Critical:** `ANTHROPIC_API_KEY` was never wired into `live-trading.yml`'s env — the
    feature would have been a permanent, silent no-op in production as merged.
  - **Important:** the small-account job would have collided with the 100k account's
    `news_debate_log.csv` once the key was set (no per-account routing existed yet);
    `log_news_debate` was unguarded in `main()`'s `finally` block and ran before
    `write_cycle_export`, so a future schema mismatch could have suppressed the real dashboard
    export and failed the whole job; the Anthropic client had no `timeout`/`max_retries` and the
    debate step ran BEFORE order submission, risking a hung call delaying a real trade; nothing
    tested that `evaluate_shadow_debate`'s actual output keys match what `log_news_debate`
    expects (the exact seam a future rename could silently break).
- `d9c3e64` — the fix wave. Addressed the Critical finding and 4 of the 5 Important findings
  (see "Deferred" below for the one that wasn't), plus 5 cheap documentation/schema-hardening
  Minor findings (stale docstring reason for disabling thinking; `strict: true` added to all 3
  tool schemas; `live_loop.py`'s module docstring updated to mention the optional key;
  `evaluate_shadow_debate`'s docstring clarified that its VADER fields are independently
  recomputed, not a literal record of what the live gate saw; a naming-collision comment near
  `DEFAULT_DASHBOARD_DIR`). Added the one seam-binding test. Scoped re-review: **all findings
  ADDRESSED, zero new Critical/Important issues introduced by the fix diff itself.**
- `2723bed` — committed the plan doc itself (`docs/superpowers/plans/2026-08-27-graywind-news-debate-shadow-mode.md`),
  which had been written to disk but not yet committed when the merge/push happened.
- Merged and pushed to `origin/main` as a clean fast-forward (`527e983..2723bed`). No conflicts,
  no drift to reconcile (origin/main hadn't moved since this session forked from it).

## What has failed / risks / caveats

- **Nothing has failed** in the sense of a broken build or a failing test — final suite state is
  384/384 passing.
- **The feature cannot run in production yet.** See "Immediate next action" above:
  `ANTHROPIC_API_KEY` needs to be created as a GitHub Actions repo secret. Until then this is
  fully-built, fully-tested, dead code from production's perspective — by design (fails open),
  not a bug.
- **DEFERRED BY DELIBERATE RULING (not an oversight) — an already-held position produces no
  shadow-debate row.** The debate step is scoped to `if position is None:` in
  `process_symbol()`, the same branch `decide_trade()` itself only reaches. While a symbol's
  position stays open (potentially for days), no comparison row is logged for it. The final
  reviewer flagged this and suggested extending coverage to the held-position branch too. The
  controller ruled this out of the fix wave: it's a genuine feature-scope enhancement (would
  need to change the asserted behavior of `test_process_symbol_does_not_debate_an_already_held_position`
  and broaden tested surface) rather than a defect, and risk-managing an unattended overnight fix
  wave outweighed closing this particular gap. **If you want to close it:** run the debate
  unconditionally near the end of `process_symbol()`, outside both the `if position is None:`
  and `else:` branches — costs one extra debate call per held symbol per cycle (cheap at Sonnet
  5 rates), and would need `test_process_symbol_does_not_debate_an_already_held_position`
  rewritten to assert the opposite (that a held position DOES get debated).
- **DEFERRED — `debate_reasoning` is unbounded free text committed to git forever.** At
  `max_tokens=1024` per judge call, each row can carry up to ~4KB of reasoning text; over many
  cycles this could meaningfully grow `dashboard-data/news_debate_log.csv` (a file this repo
  also serves via GitHub Pages). No functional risk today (nothing parses the file yet), but a
  truncation length is a real design decision nobody has made yet. Worth revisiting once there's
  real shadow-mode history to look at.
- **No live/production smoke test has been run.** There was no `ANTHROPIC_API_KEY` in this
  session's environment (by design — a real key would let a test accidentally make a live API
  call, which the spec explicitly forbids), so nothing here has ever exercised a real Anthropic
  API response shape. The forced-tool-use/structured-output code in `news_debate.py` is written
  against the current documented API contract (verified via the `claude-api` skill during
  planning and independently re-verified by the final reviewer) but has never round-tripped
  against the real API. **First real verification will happen automatically** the next time the
  15-minute cron fires after the `ANTHROPIC_API_KEY` secret is added — watch
  `dashboard-data/news_debate_log.csv` for its first real row, and watch the workflow run logs
  for any `news debate shadow-mode error` stderr line (the fail-open catch's warning message) in
  case the real API disagrees with the schema in some way this session couldn't test.

## What's next (ordered)

1. Add the `ANTHROPIC_API_KEY` GitHub Actions repo secret (manual, human-only step).
2. After the next cron cycle (or a manual `workflow_dispatch` run) following that, check
   `dashboard-data/news_debate_log.csv` exists and has a real row for each watchlist symbol, and
   check the Actions run log for any `news debate shadow-mode error` warnings.
3. Let shadow-mode history accumulate. The spec's own "Deferred, not forgotten" section (still
   binding, unchanged) lists what comes after there's enough history: whether/how the debate
   ever becomes authoritative (replacing VADER), backtest coverage (rejected for now, lookahead
   bias), and threshold recalibration (moot until authoritative) — none of that is this
   sub-project's job.
4. Optionally revisit the two deferred items above (held-position coverage,
   `debate_reasoning` size) once there's a reason to prioritize them.
5. This closes out **sub-project 3 of 3** of the capital-scaling redesign (per memory file
   `project-graywind-capital-redesign.md` — not edited by this session, the coordinating session
   updates it from this handoff).

## Verification idioms used in this project (for the resuming session)

- Test suite: `.venv/bin/python -m pytest tests/ -q` from repo root — 384 passing as of this
  handoff (357 pre-sub-project-3 baseline + 27 new).
- New Claude-API-calling code is tested via an injected, mocked `llm_client` — zero tolerance
  for a test that could make a real network/API call; see `tests/test_news_debate.py`'s
  `_fake_llm_client_for_debate`/`_fake_tool_response` helpers, mirroring
  `tests/test_sentiment_gate.py`'s `news_client` mocking pattern.
- YAML changes: `.venv/bin/python -c "import yaml; yaml.safe_load(open('<path>'))"` (this
  worktree's `.venv` already has `pyyaml` installed from the fix wave).
- Before starting related work, check `git branch -a` / `git worktree list` / `git log --all
  --oneline` for unmerged work — this repo has a documented history of stale unmerged branches.
  As of this session: `main` was the only real branch besides this session's own agent worktree;
  a pre-existing worktree at `.claude/worktrees/graywind-yahoo-analyst-consensus` was confirmed
  already merged and left untouched.
