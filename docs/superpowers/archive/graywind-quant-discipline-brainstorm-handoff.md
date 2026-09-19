# Graywind Quant-Discipline Overhaul — Session Handoff

**Written:** 2026-08-26 · **For:** whoever resumes this to continue brainstorming (NOT yet at
the spec-writing stage) a 3-part quant-rigor overhaul for Graywind, after Plan 1 (dual-account
rollout) shipped earlier in this same session.

## Goal

Two separate threads finished/advanced this session:

1. **Dual-account rollout + tier symbols (Plan 1) — DONE, merged, pushed.** See "What has
   changed" below for the full account.
2. **New, much bigger ask, currently mid-brainstorm, no spec yet:** the user wants Graywind
   held to the same backtesting/reporting discipline "every quant community in the world" uses,
   decomposed into 3 sub-projects (this session's proposed breakdown, user hasn't objected):
   - **Sub-project 1:** a backtest-before-adding-symbol gate — every symbol added to
     `SYMBOL_TIER`/`TIER1_SYMBOL_WEIGHTS` must clear a ≥5-year historical backtest (not just
     the existing market-cap/volume/sector guardrail from Plan 1), with a check for
     performance quality.
   - **Sub-project 2:** quarterly (~3-month cycle) performance reports — profit/loss and *why*,
     generated from real trading history.
   - **Sub-project 3:** a separate investor-advising UI/UX — **personal use only** (user
     explicitly confirmed this when asked), free to host (budget-constrained).

No spec or plan file exists yet for any of the 3 sub-projects — we are still in
`superpowers:brainstorming`'s architectural path, past classification and the first
scope-defining question, about to start a research pass to inform sub-project 1's design.

## How to resume (do this first)

1. Confirm Plan 1 landed: `git log --oneline -1` should show `44f79dc` (merge commit) as HEAD,
   and `git status` should say "up to date with 'origin/main'" — Plan 1 is fully merged and
   pushed, not local-only.
2. Re-invoke `superpowers:brainstorming` — this conversation already did: classify as
   **architectural** (multiple independent subsystems), decompose into the 3 sub-projects
   above, ask the first clarifying question (advising UI scope — answered: personal use only).
   Do not re-ask that question.
3. No progress ledger exists — this handoff *is* the ledger for the brainstorm-in-progress.
   Trust this file + `git log` over any recollection of the conversation.
4. **Immediate next action:** do the research pass described in "What's next" step 2 below,
   then continue brainstorming's "explore approaches" step for sub-project 1 (the backtest
   gate) using what that research turns up.

## Current state (active files)

**Branch:** `main`, up to date with `origin/main` (Plan 1 pushed at `44f79dc`).

**Files created/changed this session, all committed and pushed:**
- `graywind_strategy/tier_config.py` (`dfb85f9`) — guardrail module + populated
  `SYMBOL_TIER={"AAPL":2,"SERV":3}` / `TIER1_SYMBOL_WEIGHTS={"SPY":1.0}`.
- `graywind_strategy/sector_config.py` (`3cd2e51`) — tagged `SERV` as `robotics`.
- `live_loop.py` (`695abd0`) — `WATCHLIST=["AAPL","SERV"]`, `GRAYWIND_STATE_DIR` threaded
  through all state I/O.
- `.github/workflows/live-trading.yml` (`bb91d53`) — new `live-cycle-small` job
  (`needs: live-cycle`) for the $2k account.
- `index.html` (`807eb16`) — dashboard renders both accounts side by side.
- `docs/superpowers/plans/2026-08-26-graywind-dual-account-tier-symbols.md` (`cb99052`) — all
  task checkboxes checked except Task 4 Step 4 (see caveats below).

**Files for the NEW brainstorm that don't exist yet (nothing written beyond this handoff):**
- No spec, no plan, no design doc for any of the 3 sub-projects above.

**Scratch workspace / traps:**
- ⚠️ `scripts/fetch_serv_bars.py` — **untracked, uncommitted.** Written this session as a
  one-off fetch script (needs real `ALPACA_API_KEY`/`ALPACA_API_SECRET` in the environment,
  which no Claude session has — the user must run it themselves). Produces
  `alpaca_data/serv.csv`, which **does not exist yet**. This is a separate, smaller thread
  (backtest sanity-check for AAPL/SERV, see "What's next" step 4) from the big 3-sub-project
  brainstorm — don't conflate the two.
- ⚠️ `state/small/` and `dashboard-data/small/` **do not exist on `origin/main` yet.** A
  `workflow_dispatch` run (#93, `https://github.com/nguyenminhthanh0403-hub/graywind/actions/runs/33008354876`)
  confirmed both jobs run in the correct order and complete successfully, but it landed at
  20:02 UTC — just past the 13:30-20:00 UTC market-hours window — so `live_loop.py` exited on
  its first line (`is_market_hours()`) before either account wrote anything. This is a timing
  gap, not a bug: the next in-hours cron firing (or another manual `workflow_dispatch` run
  during 13:30-20:00 UTC) should produce real `state/small/`/`dashboard-data/small/` content.
  Check `origin/main`'s tree before assuming this is still open.
- ⚠️ `ALPACA_API_KEY_SMALL`/`ALPACA_API_SECRET_SMALL` — user confirmed (in chat) these are now
  set with the correct exact names after an earlier naming mismatch
  (`ALPACA_API_SMALL_KEY`/`...SECRET`, wrong word order). **No session can independently verify
  this** — this machine has no `gh` CLI and no `GITHUB_TOKEN`/`GH_TOKEN` (confirmed by direct
  `curl` returning 401 on the secrets-list endpoint). Trust the workflow run's success as the
  only available signal, not a direct secrets check.
- ⚠️ No historical backtest has ever been run for `SERV` (no local CSV), and `AAPL`'s last
  backtest (`scripts/run_sector_backtest.py`) predates the tier-pool-scoped equity sizing
  entirely — it used a flat $10,000, not the real $20,000/$400 tier-2 pool sizes. Don't cite
  that old backtest as validating the current live setup.

**Not mine — leave alone:** `docs/superpowers/graywind-news-debate-shadow-mode-handoff.md` —
untracked, belongs to a different concurrent session's sub-project-3 (news-interpretation)
work. Same note carried forward from the prior handoff in this lineage.

**Archived this session:** `docs/superpowers/graywind-dual-account-advisor-plans-handoff.md`
(the prior handoff in this lineage, untracked, now superseded by this file) →
`docs/superpowers/archive/graywind-dual-account-advisor-plans-handoff.md`.

## What has changed

**Plan 1 (dual-account rollout) — fully executed, inline (`superpowers:executing-plans`, on
`main` directly per user's explicit choice), all 5 tasks + checkbox-update commit, merged with
4 concurrent live-cron auto-commits (clean, no conflicts), pushed to `origin/main` at `44f79dc`.
285/285 tests pass.**

`delegate` was considered per the prior handoff's guidance but didn't apply: the plan's own
tasks already contained complete, ready-to-write code with no drafting step to offload — what
remained was pure file/tool-access work delegate explicitly can't do.

**Two real bugs found and fixed beyond the plan's literal given code:**
1. `validate_symbol_addition` fetched market cap AND volume before checking either — a symbol
   failing only the market-cap floor still triggered a real `fetch_avg_volume` call against an
   unmocked `data_client` in the plan's own test, masking the intended "market cap" failure
   message. Fixed to check market cap immediately after fetching it, before ever fetching
   volume.
2. `test_reconcile_positions_does_not_fabricate_broker_only_position` hardcoded `"SPY"` as the
   broker-only example, but `reconcile_positions`'s warning only fires for `WATCHLIST` members
   — once `SPY` left `WATCHLIST` (Task 3), this test silently stopped testing anything. Swapped
   to `"SERV"`.

Dashboard (Task 5) also diverged from the plan's assumed markup in three ways the plan author
didn't have visibility into (footer lived inside `renderApp`'s template not as static page
content; there was a retry button in the error path; "no status data yet" was a guard inside
`renderApp`, not a separate branch) — adapted `renderAccount`/`loadAccount` to preserve all
three. Manually verified via headless-Chrome screenshots (`claude-in-chrome` extension wasn't
connected this session): $100k column renders real data, $2k column gracefully shows
"couldn't load" + a working Retry button, grid correctly stacks to one column at 600px width.

**Then, after Plan 1 shipped:** user asked to backtest AAPL/SERV performance. That surfaced two
gaps (no `SERV` historical data at all; `AAPL`'s old backtest predates tier-pool sizing) —
`scripts/fetch_serv_bars.py` was written for the user to run themselves (needs real
credentials). That in turn led to a much bigger ask: standardize Graywind's practices against
what quant communities (US/UK/Chinese) actually do. `superpowers:brainstorming` was invoked
(classified **architectural**, decomposed into the 3 sub-projects above). Research approach was
scoped down from the user's original list: GitHub + Reddit + established quant literature
(walk-forward validation, López de Prado's overfitting corrections) are genuinely searchable;
RedNote/Facebook were flagged as very low-yield for automated search (app-first, not indexed,
private groups) — not rejected outright, just expectation-set low.

**User feedback captured to memory this session:**
- [[feedback-double-review-scope]] — a delegate+Claude-review 2x pass is reserved for deep
  research / genuinely token-intensive big tasks, **not** a default on every spec/plan (I had
  proposed the blanket version; user corrected it down).
- [[project-graywind-capital-redesign]] — updated to reflect Plan 1 shipped+pushed.

## What has failed / risks / caveats

- **Nothing has failed in the shipped Plan 1 code** — 285/285 tests, clean merge, workflow run
  succeeded.
- **UNVERIFIED:** the small account's actual end-to-end trading cycle (real
  `state/small/`/`dashboard-data/small/` content) — blocked purely on timing (see trap above),
  not a code defect.
- **UNVERIFIED / NOT YET DONE:** any historical backtest of `AAPL`/`SERV` at the real
  tier-pool-scoped equity. This is a live gap in what's actually running with real (paper)
  money right now, independent of the bigger quant-discipline brainstorm.
- **Open, not decided:** the actual quality thresholds (Sharpe/max-drawdown/win-rate cutoffs,
  lookback window, walk-forward window sizes) for sub-project 1's backtest gate — this is
  exactly what the research pass is meant to inform. Nothing proposed yet.
- **Decision carried forward, don't re-litigate:** advising UI (sub-project 3) is personal-use
  only — no auth system, no RIA/compliance surface, no multi-user design needed.
- **Decision carried forward, don't re-litigate:** the double-review (delegate + Claude review)
  quality gate is reserved for deep-research/token-intensive tasks only — do not propose it as
  a default for every future spec/plan on this project.

## What's next (ordered)

1. Resume `superpowers:brainstorming` (architectural path) for the quant-discipline overhaul.
   Sequencing already agreed with the user: sub-project 1 (backtest gate) → 2 (quarterly
   reports) → 3 (advising UI). Don't re-ask the scope question already answered.
2. Do the research pass **inline** (not via a subagent, unless the user asks for one — this
   session's environment defaults to not spawning agents unprompted): GitHub repos and Reddit
   (r/algotrading, r/quant) for real backtesting-framework conventions (walk-forward,
   no-lookahead fill timing, overfitting corrections like deflated/probabilistic Sharpe ratio,
   purged/embargoed k-fold cross-validation), plus a genuine but low-expectation attempt at
   Chinese-language quant sources (Zhihu, published methodology from Ubiquant/High-Flyer/
   Minghong) — skip RedNote/Facebook as impractical unless a cheap attempt is warranted.
   Synthesize into concrete, Graywind-specific standards.
3. Continue brainstorming's "explore approaches" step for sub-project 1 using that research →
   present design in chat sections → write spec to
   `docs/superpowers/specs/<date>-graywind-<topic>-design.md` → spec self-review → user reviews
   spec → `superpowers:writing-plans`. Do not skip straight to code — no implementation until a
   spec is written and approved (architectural-path hard gate).
4. **Separate, smaller thread — do independently of the above whenever convenient:** ask the
   user to run `python3 scripts/fetch_serv_bars.py` (with their own `ALPACA_API_KEY`/
   `ALPACA_API_SECRET` exported) to produce `alpaca_data/serv.csv`. Once it exists, run the
   tier-pool-scoped backtest as a standalone sanity check: `AAPL` at $20,000 (tier-2 pool,
   $100k account) and $400 (tier-2 pool, $2k account); `SERV` at $10,000 and $200 (tier-3
   pools). **Exclude `SPY`** — it's tier-1 buy-and-hold via `tier1_rebalance.py`, not the
   intraday `decide_trade` engine `graywind_strategy/backtester.py` replays, so running it
   through this backtester would simulate behavior it never actually exhibits live.
5. Whenever during 13:30-20:00 UTC: confirm `state/small/` + `dashboard-data/small/` actually
   appear on `origin/main` from a real in-hours cycle — closes Plan 1 Task 4 Step 4 for good
   (currently the plan's only unchecked step).

## Verification idioms used in this project (for the resuming session)

- Full test suite: use the project's `.venv`, not system `python3` —
  `.venv/bin/python -m pytest tests/ -q`.
- Local checkouts drift stale fast (a 15-min live cron auto-commits to `main`) —
  `git fetch origin main` and diff against `origin/main`, or read straight from a ref with
  `git show origin/main:<path>`.
- GitHub Actions run history (works unauthenticated, public repo, no `gh` CLI needed —
  confirmed working this session even with `gh` fully absent from this machine):
  ```
  curl -s "https://api.github.com/repos/nguyenminhthanh0403-hub/graywind/actions/workflows/live-trading.yml/runs?per_page=10" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); [print(r['run_number'], r['status'], r['conclusion'], r['event'], r['created_at']) for r in d['workflow_runs']]"
  ```
  Per-job/per-step breakdown: `curl -s ".../actions/runs/<run_id>/jobs"`.
- Repo tree contents without cloning: `curl -s "https://api.github.com/repos/<owner>/<repo>/contents/<path>"`.
- Listing or setting repo secrets requires real auth (`gh` CLI or a token) — **not available on
  this machine**; unauthenticated calls to the secrets API return 401. Don't assume a future
  session has `gh` either — check first (`which gh`) rather than assuming from this note.
- Live public dashboard: `https://nguyenminhthanh0403-hub.github.io/graywind/`.
- This project follows TDD (red/green) for `gates/`/`pipeline.py`/`strategy_engine.py`/
  `backtester.py`/`risk/`/`live_loop.py` changes; workflow YAML and `index.html` changes have
  no automated coverage — validate YAML with
  `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/live-trading.yml'))"`
  (needs `pyyaml`, not in the base venv — `pip install pyyaml` into `.venv` first) and verify
  HTML changes with a local `python3 -m http.server` plus headless-Chrome screenshots (the
  `claude-in-chrome` extension was not connected this session — fell back to a headless Chrome
  subprocess with `--user-data-dir=/tmp/cdp-shot-$$`; the process can hang on unrelated Chrome
  updater/GCM background noise even after writing the screenshot successfully — check the
  output file exists before assuming the whole invocation failed, then `pkill`/clean up the
  temp profile dir).
- **Always check `git branch -a` and `git log --all --oneline` for unmerged work** before
  starting — precedent: a fully-built, tested, unmerged branch sat untouched for 5 days
  earlier in this project's history with zero mention anywhere.
