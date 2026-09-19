# Graywind Dual-Account + Trade-Approval Advisor — Session Handoff

**Written:** 2026-08-26 · **For:** whoever resumes this to execute the two implementation
plans below (both specs are approved, both plans are written — this session did design and
planning only, zero implementation).

## Goal

Two bundled efforts, planned in sequence this session:

1. **Dual-account rollout + tier symbol guardrails** — stand up the user's new $2k Alpaca
   paper account alongside the existing ~$100k one, both running Graywind's 70/20/10 tier
   split with real symbols (currently inert — `tier_config.py` ships empty).
2. **Trade-approval advisor** — turn Graywind from fully autonomous into
   approve-before-execute for every new-position buy (personal use only, confirmed with the
   user), via GitHub Issues as the approval surface. **Depends on #1 shipping first.**

- Spec 1: `docs/superpowers/specs/2026-08-26-graywind-dual-account-tier-symbols-design.md`
- Plan 1: `docs/superpowers/plans/2026-08-26-graywind-dual-account-tier-symbols.md`
- Spec 2: `docs/superpowers/specs/2026-08-26-graywind-trade-approval-advisor-design.md`
- Plan 2: `docs/superpowers/plans/2026-08-26-graywind-trade-approval-advisor.md`
- Progress ledger: none — neither plan has started execution yet. Task checkboxes inside each
  plan file are the source of truth once execution begins.

Both specs are user-approved. **Neither plan has been executed** — this handoff exists because
the user asked to pause after planning and pick this up later, before choosing an execution
approach.

## How to resume (do this first)

1. Confirm branch: `git log --oneline d7e1676..HEAD` should show 4 commits — two spec commits
   (`6897670`, `9d248c8`) then two plan commits (`ab104c4`, `69fb290`) — topped by `69fb290`
   ("docs: add implementation plan for GitHub-Issues trade-approval advisor gate"), possibly
   with newer live-cron auto-commits above it (normal — see "Verification idioms").
2. Read Plan 1 in full (`docs/superpowers/plans/2026-08-26-graywind-dual-account-tier-symbols.md`)
   — it's self-contained (real code in every step, no placeholders) and was already
   self-reviewed for spec coverage/type consistency at the bottom of the file.
3. **Immediate next action:** ask the user which execution approach for Plan 1 —
   `superpowers:subagent-driven-development` (fresh subagent per task, recommended by
   `writing-plans`) or `superpowers:executing-plans` (inline, batch with checkpoints). This
   choice was never made; the session paused right before it per the user's explicit request.
4. Do **not** start Plan 2 until Plan 1's Task 4 (workflow) and Task 5 (dashboard) are merged
   and the `ALPACA_API_KEY_SMALL`/`ALPACA_API_SECRET_SMALL` secrets exist — Plan 2's own header
   states this dependency explicitly.
5. **New since this handoff was written — applies to all projects, not just Graywind:** a
   `delegate` skill now exists (`~/.claude/skills/delegate`). When executing either plan's
   tasks via subagent-driven-development, if a given task is bounded, self-contained,
   boilerplate-shaped, and judged token-costly (no file/tool access needed to produce it),
   consider offloading it to the `delegate` CLI (free external model on OpenRouter) instead of
   a full Claude subagent — but the skill's gate is mandatory, not optional: delegate's output
   must go through a `code-review` pass, get a plain-language explanation, and get explicit
   manual approval before it's ever treated as done. Time pressure or "just get it done" from
   the user does not waive that gate (verified by pressure-testing the skill with subagents
   before it was deployed).

## Current state (active files)

**Branch:** `main`, 4 commits ahead of `origin/main` (not yet pushed — nobody has asked to
push this session's work).

**Files created this session (all committed):**
- `docs/superpowers/specs/2026-08-26-graywind-dual-account-tier-symbols-design.md` (`6897670`)
- `docs/superpowers/specs/2026-08-26-graywind-trade-approval-advisor-design.md` (`9d248c8`)
- `docs/superpowers/plans/2026-08-26-graywind-dual-account-tier-symbols.md` (`ab104c4`)
- `docs/superpowers/plans/2026-08-26-graywind-trade-approval-advisor.md` (`69fb290`)

**Files Plan 1's tasks will touch (untouched so far — Plan 1 hasn't started):**
- `graywind_strategy/tier_config.py` — currently ships `SYMBOL_TIER = {}` /
  `TIER1_SYMBOL_WEIGHTS = {}` (confirmed empty by a real `Read` this session). Plan 1 Task 1
  populates it with the guardrail-vetted starters: `{"AAPL": 2, "SERV": 3}` /
  `{"SPY": 1.0}`.
- `graywind_strategy/sector_config.py` — Plan 1 Task 2 adds `"SERV": "robotics"`.
- `live_loop.py` — Plan 1 Task 3 changes `WATCHLIST` to `["AAPL", "SERV"]` and threads a new
  `GRAYWIND_STATE_DIR` env var through every state-persistence call.
- `.github/workflows/live-trading.yml` — Plan 1 Task 4 adds a second, sequential
  (`needs: live-cycle`) job for the $2k account.
- `index.html` — Plan 1 Task 5 renders both accounts side by side.
- **New GitHub secrets** `ALPACA_API_KEY_SMALL`/`ALPACA_API_SECRET_SMALL` — **manual, user's
  own step** (`gh secret set`), not part of any task. Not yet set as of this session.

**Scratch workspace / traps:**
- ⚠️ **Both plans are unstarted.** No task checkboxes are checked in either plan file yet —
  don't assume any progress beyond what's described here.
- ⚠️ Plan 2 (`trade-approval-advisor`) is **not executable yet** — it assumes Plan 1's
  `state_dir` local variable and `WATCHLIST = ["AAPL", "SERV"]` already exist in `live_loop.py`.
  Starting Plan 2 before Plan 1 lands will break immediately (its Task 3/4/5 reference
  `state_dir` and the new `WATCHLIST` contents that don't exist pre-Plan-1).
- ⚠️ Plan 2's own self-review caught and fixed a real bug before it ever got written down: an
  approved tier-2/3 buy must carry `stop_price`/`target_price` through from proposal to
  execution (added to the `pending_trades` row schema beyond what the spec's prose enumerated)
  — without it, `process_symbol`'s stop/target-exit check would crash on a `None` comparison
  the very next cycle after execution. This is already baked into Plan 2 Task 1/3/5 — just
  flagging it so a resuming session understands *why* the row schema has more fields than the
  spec's own Component 1 prose lists.
- ⚠️ `state/operational.csv` on `origin/main` showed `starting_equity: 100148.97` as of
  2026-08-25 — the **existing $100k account's balance has not been manually lowered**. Separate,
  still-open item from an earlier capital-redesign conversation, unrelated to standing up the
  new $2k account or either plan above. Not touched this session.

**Not mine — leave alone:** `docs/superpowers/graywind-news-debate-shadow-mode-handoff.md` is
untracked and belongs to a different, concurrent session's sub-project-3 (news-interpretation)
work — carried forward from the last two handoffs in this lineage. Deliberately **not
archived** despite being older than the 2-most-recent-by-mtime rule: that rule is for
superseded handoffs in the same lineage, not unrelated concurrent work in progress.

## What has changed

Both specs (brainstormed to approval this session) and both implementation plans (written via
`superpowers:writing-plans`) are committed on `main`. **Zero implementation** — no source file
outside `docs/superpowers/` was touched. Commits: `6897670`, `9d248c8`, `ab104c4`, `69fb290`.

**Decisions locked in this session (treat as confirmed, not open questions):**
- Starter tickers: `AAPL` (tier 2), `SERV` — Serve Robotics — (tier 3, new `robotics` sector
  tag). `SOUN` was the original candidate but dropped after live data showed it had grown to
  ~$3.1B market cap, no longer fitting "small-cap gamble" in spirit.
- Tier 1 gets `SPY` at full weight — not explicitly discussed in the prior session, added this
  session to close a gap (tier 1 needs at least one symbol or the monthly rebalance
  early-returns forever).
- Multi-account infra: `*_SMALL`-suffixed secrets, `state/small/`+`dashboard-data/small/`
  nesting, two sequential (not parallel) workflow jobs, side-by-side dashboard columns.
- Trade-approval advisor is **personal use only**, **approve-before-execute** for buys across
  all three tiers, **sells stay fully automatic**, **GitHub Issues** as the approval surface
  (owner-reaction-only, same-trading-day expiry, ~2% price-staleness re-check at approval
  time). The "stock advisor for other people" idea remains explicitly out of scope / parked.

## What has failed / risks / caveats

- **Nothing has failed** — no code has run yet, both plans are pre-execution.
- **UNVERIFIED:** Finnhub's free tier actually returning `marketCapitalization` from
  `/stock/profile2` — flagged in both the spec and Plan 1 Task 1, never hit with a real
  request this session (Plan 1's guardrail tests all mock the Finnhub response). Confirm this
  early when Plan 1 Task 1 executes; it's load-bearing for the whole guardrail.
- **UNVERIFIED:** live market-cap/volume numbers for `AAPL`/`SERV` were checked against
  stockanalysis.com this session (SERV: ~$423M cap / ~5.2M avg volume) but not against
  Finnhub's actual API response shape — same caveat as above.
- **Open, not decided:** how `ALPACA_API_KEY_SMALL`/`ALPACA_API_SECRET_SMALL` actually get set
  — the user confirmed they'll run `gh secret set` themselves after generating keys in the
  Alpaca dashboard; not done yet as of this session.
- **Unrelated but still pending:** lowering the existing $100k account's starting balance —
  open since an earlier conversation, irrelevant to either plan here.

## What's next (ordered)

1. Ask the user to choose Plan 1's execution approach: `superpowers:subagent-driven-development`
   (recommended) or `superpowers:executing-plans`.
2. Execute Plan 1 task-by-task (`docs/superpowers/plans/2026-08-26-graywind-dual-account-tier-symbols.md`).
   Tasks 1-3 are pure Python/TDD; Tasks 4-5 (workflow YAML, dashboard HTML/JS) have no
   automated test coverage in this repo and end in an explicit manual-verification step —
   don't skip those.
3. Once Plan 1 is merged and the `_SMALL` secrets exist, manually verify via a
   `workflow_dispatch` run that both accounts' jobs run correctly (see Plan 1 Task 4's Step 4).
4. Only then start Plan 2 (`docs/superpowers/plans/2026-08-26-graywind-trade-approval-advisor.md`),
   same execution-approach question again.
5. Plan 2 also ends in a manual-verification step (Task 6, Step 5) — trigger a real
   `workflow_dispatch` run, confirm a GitHub issue opens correctly, a 👍 from the repo owner
   executes the trade next cycle, and a reaction from anyone else is ignored. **This last check
   (non-owner reaction ignored) is the single most safety-critical thing to verify by hand** —
   the repo is public.

## Verification idioms used in this project (for the resuming session)

- Full test suite: use the project's `.venv`, not system `python3` —
  `.venv/bin/python -m pytest tests/ -q`.
- Local checkouts drift stale fast (a 15-min live cron auto-commits to `main`) —
  `git fetch origin main` and diff against `origin/main`, or read straight from a ref with
  `git show origin/main:<path>`.
- GitHub Actions run history (works unauthenticated, public repo, no `gh` CLI needed):
  ```
  curl -s "https://api.github.com/repos/nguyenminhthanh0403-hub/graywind/actions/workflows/live-trading.yml/runs?per_page=10" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); [print(r['run_number'], r['status'], r['conclusion'], r['event'], r['created_at']) for r in d['workflow_runs']]"
  ```
- Live public dashboard: `https://nguyenminhthanh0403-hub.github.io/graywind/`.
- This project follows TDD (red/green) for `gates/`/`pipeline.py`/`strategy_engine.py`/
  `backtester.py`/`risk/`/`live_loop.py` changes; workflow YAML and `index.html` changes have
  no automated coverage in this repo — validate YAML syntax with
  `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/live-trading.yml'))"` and
  verify HTML changes by serving locally (`python3 -m http.server`) plus a post-merge
  `workflow_dispatch` check, matching both plans' explicit manual-verification steps.
- **Always check `git branch -a` and `git log --all --oneline` for unmerged work** before
  starting — precedent: a fully-built, tested, unmerged branch sat untouched for 5 days
  earlier in this project's history with zero mention anywhere.
