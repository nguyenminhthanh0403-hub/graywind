# MAVIS Graywind Grounding + Auth — Session Handoff

**Written:** 2026-09-15 · **For:** whoever picks up the MAVIS backend next — either to run the (skipped) final whole-branch review and land this branch, or to plan the original avatar plan's next nights (MCP wrapper, Three.js frontend).

## Goal

MAVIS is a small FastAPI backend (`mavis/`, inside the `graywind` repo) meant to eventually power a browser-based 3D avatar and an MCP tool, answering questions grounded in real data rather than improvising. This session extended its `/ask` endpoint to pull from two grounding sources — the existing Bullion financial-system map, and (new this session) Graywind's own trading state (watchlist, latest per-symbol decisions, pending trade proposals) — and locked the endpoint down with API-key auth and per-key rate limiting before it becomes reachable from anywhere but localhost.

- Plan: `docs/superpowers/plans/2026-09-15-mavis-graywind-grounding-and-auth.md` (no separate spec — scope was set directly with the user in-session; the plan document records why)
- Progress ledger (recovery map — trust this over memory): `.superpowers/sdd/2026-09-15-mavis-graywind-grounding-and-auth/progress.md`
- Original 6-night avatar plan (partially superseded, corrected in place this session): `~/Downloads/mavis-cloud-avatar-plan_1.md` — **outside the repo, not tracked by git**

## How to resume (do this first)

1. Confirm you're on `feat/mavis-grounding-and-auth` and see 6 commits: `git log --oneline $(git merge-base main HEAD)..HEAD` should show `98a48c5` down to `25e8b31`. **Do not diff against local `main`** — see the trap below.
2. Read the ledger in full (`.superpowers/sdd/2026-09-15-mavis-graywind-grounding-and-auth/progress.md`) — it has the complete task-by-task history, every review finding, and every ruling made (including several honest self-corrections). This handoff summarizes it; the ledger is the authority.
3. Run the suite to confirm nothing has drifted: `cd mavis && .venv/bin/python -m pytest -q` — expect 36/36 passing.
4. **Immediate next action:** decide between (a) running the SDD-mandated final whole-branch review (skipped this session, see "What has failed" below) before finishing the branch, or (b) going straight to `superpowers:finishing-a-development-branch` to decide how this branch lands. Nothing is blocking either path — the plan's 4 tasks are fully implemented and tested.

## Current state (active files)

**Branch:** `feat/mavis-grounding-and-auth`, 6 commits ahead of `origin/main` (based on a fresh fetch, not local `main` — see trap below).

**Files created/changed:**
- `f050df6` — baseline commit: MAVIS's pre-existing Night 1-2 scaffold (`app.py`, `grounding.py`, `providers.py`, `requirements.txt`, `data/bullion_grounding.json`, `scripts/extract_bullion_grounding.js`) was sitting entirely uncommitted at session start — committed as-is. Also fixed the repo root `.gitignore`: `data/` and `alpaca_data/` had no leading slash and were silently also ignoring `mavis/data/`; anchored to `/data/` and `/alpaca_data/`.
- `1a19a68` — `mavis/scripts/extract_graywind_grounding.py` (new): build-time snapshot script reading `state/decision_log.csv`, `state/pending_trades.csv` (both accounts) and `live_loop.py`'s `WATCHLIST`, writing `mavis/data/graywind_grounding.json`. Deliberately excludes `state/tier_pools.csv` — the 100k account's pool balances are known-wrong (see the separate, unrelated Graywind punch-list handoff below).
- `b461f7c` — `mavis/graywind_grounding.py` (new): keyword-retrieval over the Graywind snapshot. `mavis/app.py` modified to merge Bullion + Graywind grounding into one context and one citations list.
- `fde04d5` — `mavis/auth.py` (new): `X-API-Key` dependency, constant-time comparison, fails closed (500) if `MAVIS_API_KEY` isn't set server-side. Wired into `/ask` only (`/status` stays open).
- `98a48c5` — `mavis/rate_limit.py` (new): fixed-window limiter, 20 req/min/key by default (`MAVIS_RATE_LIMIT_PER_MINUTE`). Also: `mavis/text_scoring.py` (new, shared `tokenize`/`score_overlap` extracted out of `grounding.py` and `graywind_grounding.py` after their copies drifted twice), and several real bug fixes discovered mid-review — see "What has changed" below.

**Files later work will modify (untouched so far):**
- No MCP wrapper or avatar frontend exists yet (original plan's Nights 3-4) — this plan explicitly excluded them (see its Global Constraints). A new plan is needed before touching them.

**Scratch workspace / traps:**
- ⚠️ **Local `main` is stale and not this branch's real base.** Local `main` sits 25 commits behind `origin/main` (Graywind's live trading cron pushes state/dashboard-data commits every ~15 min) and has 2 of its own unpushed commits from an unrelated effort (manual-trade-panel spec/plan docs). This branch was deliberately created off a fresh `origin/main` fetch (`e666b10` at the time), not local `main` — use `git merge-base main HEAD` to compute the real diff range, and re-fetch before trusting "ahead/behind" counts.
- ⚠️ **`feat/manual-trade-panel` is a separate, unrelated branch** that had uncommitted Task 5 work at the start of this session. That work was reviewed and committed this same session (commits `69bc519`, `edf7e79`) at the user's explicit approval — entirely separate from MAVIS. Don't conflate the two efforts if you see both in `git branch -a`.
- ⚠️ **`scripts/fetch_serv_bars.py`** (repo root) is an unrelated one-off script from an earlier Aug-26 effort, intent-to-added (`git add -N`) by a prior session. It's been deliberately left alone (never staged) throughout this entire session — don't sweep it into a future commit by accident.
- ⚠️ **`mavis/data/graywind_grounding.json` is a snapshot, not live data** — it goes stale as Graywind's live loop appends to `decision_log.csv`/`pending_trades.csv` every ~15 minutes. Re-run `python scripts/extract_graywind_grounding.py` (from `mavis/`) before demoing if it looks old.
- ⚠️ **Neither `MAVIS_API_KEY` nor `GROQ_API_KEY` is set anywhere** — this is all local dev/test so far, nothing is deployed to a VPS. `/ask` will 500 by design until an operator sets `MAVIS_API_KEY`.

**Not mine — leave alone:** `docs/superpowers/graywind-critical-review-punch-list-execution-handoff.md` and `docs/superpowers/graywind-dashboard-viego-reskin-and-cron-fix-handoff.md` document a separate, unrelated Graywind effort from earlier the same day — don't confuse with this handoff.

## What has changed

- MAVIS went from a fully-uncommitted Groq-only scaffold to a tested, committed, 4-task feature branch (6 commits total including baseline).
- Full mavis suite: **36/36 passing** (`cd mavis && .venv/bin/python -m pytest -q`), up from 0 tests at session start.
- Fixed the repo-root `.gitignore` bug (see above).
- Fixed several real bugs surfaced by review during the fix loops, all live-verified:
  - `grounding.py`: a substring-match bug in the label bonus (`"gold"` matching inside `"goldfish"`; `"sec"` matching inside `"second"`); then a follow-on bug where the fix's replacement (unordered token-subset match) could be tricked by a multi-word label's words appearing anywhere unordered in the query (confirmed live-reproducible on 29 of ~39 real node labels); then an underscore-splitting bug where the real node id `dxy_fx` could never register as a strong-term match. All three fixed and regression-tested.
  - `graywind_grounding.py`: a "universal namespace tag" bug (the `"graywind"` tag, present on every fact, defeated its own anti-false-positive scoring); then a follow-on edge case where the general fix for that would wrongly demote a symbol's own tag if the watchlist ever held only one symbol.
  - `extract_graywind_grounding.py`: a regex that only matched a single-line `WATCHLIST` assignment; a round-trip mistake where "fixing" a reviewer-flagged asymmetry (no missing-file guard) was reverted after a later review correctly pointed out it converted a loud, correct failure into a silent, wrong one.
- The original `~/Downloads/mavis-cloud-avatar-plan_1.md` was corrected in place: struck the dead Fable-5.1-escalation architecture and its budget section (Fable credit turned out to be an in-app product credit, not something backend code can call), marked Nights 1-2 done, and inserted "Night 2.5" (this session's work) ahead of the still-unstarted MCP wrapper/avatar frontend.

## What has failed / risks / caveats

**Nothing has failed** — all 4 planned tasks shipped, reviewed, and tested.

- **UNVERIFIED:** no end-to-end manual smoke test was run against a live `uvicorn` server with real `GROQ_API_KEY`/`MAVIS_API_KEY` set (the plan's Task 4 Step 8 describes this exact test). Only `TestClient`-based unit/integration tests ran this session.
- **UNVERIFIED:** the SDD process's mandatory final whole-branch review (most-capable-model, cross-task pass) was **not run** — the user asked to move to this handoff right after Task 4's own 5-round fix loop closed. Per-task review was unusually thorough (5 rounds each on Tasks 3 and 4, ~10 review passes total across the whole plan), but a genuine cross-task pass hasn't happened.
- **Decision carried forward, not a bug:** rate limiting is a single global bucket in practice, not truly "per caller" — `auth.require_api_key` only ever validates one shared `MAVIS_API_KEY`, so every legitimate caller draws from the same 20-req/min bucket. Documented in `rate_limit.py`'s docstring, not coded around.
- **Decision carried forward, not fully solved:** the grounding label-match fix (word-boundary contiguous phrase) closes the specific reported bug, but a deeper, structural characteristic remains — a node's label is always part of its own searchable text, so ordinary bag-of-words overlap can independently reach the citation threshold whenever 2+ of a label's words appear anywhere in a query, through a different code path than the one fixed. Full precision was never achievable within this task's scope; see ledger Task 4 round 5 for the complete reasoning and the isolated regression test that actually locks in what was fixed.
- **Explicitly declined (not deferred), with reasoning in the ledger:**
  - IP-based anti-brute-force throttling for unauthenticated `/ask` traffic (never scoped in this plan; real gap if the threat model ever changes for this personal project).
  - `grounding.py`'s link-text rendering literal `"None"` when `why`/`stat` are null (dormant today, confirmed via the real data; pre-existing Bullion module, not touched by any task).
  - Reusing `graywind_strategy/state_store.py`'s `load_pending_trades()` instead of `extract_graywind_grounding.py`'s own reader — different return shape (dict-keyed-by-symbol, typed fields) and different error philosophy (silently degrades) than this script's deliberately-chosen list-of-raw-dicts / raise-on-missing-file design.
- **External, unrelated but relevant:** the same-day Graywind punch-list handoff (`docs/superpowers/graywind-critical-review-punch-list-execution-handoff.md`) queued a docs-only item to redirect Graywind's own "personal advising UI" sub-project to MAVIS instead of building it inside Graywind. **That redirect has not been acted on or reflected in MAVIS's scope yet** — worth reading before deciding whether MAVIS's grounding should widen beyond decision logs to Graywind's backtest/performance-report data.

## What's next (ordered)

1. Decide: run the SDD final whole-branch review now (`superpowers:requesting-code-review`'s code-reviewer, most capable model, over `git merge-base main HEAD`..`HEAD`), or skip straight to `superpowers:finishing-a-development-branch` to decide how this branch lands. Either is reasonable — the plan is fully implemented.
2. Run the plan's Task 4 Step 8 manual smoke test: set `MAVIS_API_KEY` and a real `GROQ_API_KEY`, `uvicorn app:app --reload` from `mavis/`, curl `/ask` with and without the key.
3. `superpowers:finishing-a-development-branch` once satisfied — check this repo's own recent convention (feature branches pushed via `gh`, per the `feat/manual-trade-panel` precedent) before assuming how it should land.
4. Only after that: a **new** plan (via `superpowers:writing-plans`) for the original avatar plan's Nights 3-4 (MCP wrapper, Three.js frontend) — not a continuation of this one.
5. Read `docs/superpowers/graywind-critical-review-punch-list-execution-handoff.md` before starting step 4, to settle whether MAVIS's grounding scope should widen per the redirect decision noted above.

## Verification idioms used in this project (for the resuming session)

- `cd mavis && .venv/bin/python -m pytest -q` — full suite, 36/36 as of this handoff.
- `cd mavis && .venv/bin/python scripts/extract_graywind_grounding.py` — regenerate the Graywind grounding snapshot from current `state/` CSVs.
- Fast retrieval sanity check without a server: `.venv/bin/python -c "import grounding; print(grounding.retrieve('...'))"` (or `graywind_grounding`) — used throughout this session to live-verify every fix against real data before trusting a test alone.
- `git merge-base main HEAD` — the actual base of this branch; local `main`'s tip is not it (see trap above).
- `delegate` (`~/.local/bin/delegate`) was used to draft each task's initial code from the plan's exact spec; always redirect stdin (`< /dev/null`) or it hangs — see the global `delegate` skill for the full required sequence (integrate → code-review → explain → wait for approval, followed exactly this session).
