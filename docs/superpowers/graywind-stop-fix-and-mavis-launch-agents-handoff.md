# Graywind Stop Fix + MAVIS Launch-at-Login — Session Handoff

**Written:** 2026-09-24 · **For:** whoever resumes either thread. Two independent things
landed: a **live trading bug fixed on `main`**, and **launch-at-login for Johnny** on
`feat/mavis-avatar`. The wake-word model still does not exist and is still the owner's
top complaint — start at "What's next".

This **supersedes** two files for current state:
- `graywind-mavis-latency-and-grounding-handoff.md` (2026-09-23) — for MAVIS. Still the
  authority on the **latency arithmetic, the grounding hole's two-problem split, and the
  chunked-VC caveats**; fall back to it for that detail.
- `graywind-tier-rebalance-and-split-fix-handoff.md` (2026-09-18) — for Graywind. Still the
  authority on the **tier-rebalance math and the AAPL/SERV validation finding**.

Do not read the older pile; it is tracked in git.

## Goal

Two threads, no shared code:

1. **Graywind** — a de-watchlisted holding had its stop written to state every cycle and
   never compared against a price. Fixed.
2. **MAVIS/Johnny** — the owner does not want to run a script; he wants to say the phrase
   and have Johnny wake. That needs a wake-word model **and** launch-at-login. This session
   did the second half.

- Avatar spec: `docs/superpowers/specs/2026-09-19-mavis-avatar-design.md`
- Avatar plan (the ledger): `docs/superpowers/plans/2026-09-19-mavis-avatar.md`
  — ⚠️ **the ledger under-reports; trust `git log` and the files over its checkboxes.**
- Voice spec/plan: `specs/2026-09-20-mavis-canned-voice-design.md`, `plans/2026-09-20-mavis-canned-voice.md`

## How to resume (do this first)

1. `cd ~/Projects/graywind && git rev-parse --abbrev-ref HEAD` — expect **`feat/mavis-avatar`**,
   **46 commits** ahead of base `bde13f3`, **pushed to origin** (it was local-only before this
   session; that risk is closed).
2. `git fetch origin && git log origin/main --oneline | grep "Enforce stops"` — expect
   **`ebd105f`**. That is the trading fix; it is on `main` and live.
3. `cd mavis && .venv/bin/python -m pytest -q` — expect **180 passed**.
   Root suite is separate and **its count depends on which branch you are on**:
   **592 on `main`**, but **585 on `feat/mavis-avatar`** — that branch is ~160 commits behind
   `main` and does not contain `ebd105f`'s 7 new tests. Both numbers are correct; a 585 on the
   avatar branch is **not** a regression. Don't "fix" it by merging `main` in unasked.
4. **Immediate next action:** the **openWakeWord Colab run** for phrase `wake up johnny`
   (~1hr, mostly unattended). Nothing else the owner asked for unblocks without it.

## Current state (active files)

**Branch:** `feat/mavis-avatar`, 46 commits ahead of `bde13f3`, pushed. Tree clean apart from
pre-existing untracked junk.

**Committed in `ebd105f` (on `main`, NOT on the avatar branch):**
- `live_loop.py` — `main()` now iterates `WATCHLIST + held_off_watchlist`; `process_symbol`
  gained `entries_enabled`; `reconcile_positions` no longer gates its warning on `WATCHLIST`.
- `fetch_alpaca_data.py` — `fetch_bars` returns `list(response.data.get(symbol, []))`.
- `tests/test_live_loop.py`, `tests/test_fetch_alpaca_data.py` — +7 tests. **592 passing.**

**Committed in `7039e62` (on `feat/mavis-avatar`):**
- `mavis/scripts/install_launch_agents.sh` — writes `~/.mavis/env` (mode 600) + both plists,
  loads them. Supports `--dry-run` and `--uninstall`.
- `mavis/scripts/mavis-backend.sh` — uvicorn wrapper; sources the env file.
- `mavis/scripts/mavis-avatar.sh` — avatar wrapper; **waits for the backend port** first.

**Files later work will modify (untouched so far):**
- `mavis/assets/wakeword/` — **still does not exist.** The model goes at exactly
  `wake_up_johnny.onnx`; `avatar/wake.py` looks for that literal filename.
- `mavis/data/graywind_grounding.json` — the 6-fact corpus. Never hand-edit; regenerate with
  `cd mavis && .venv/bin/python scripts/extract_graywind_grounding.py` (but see caveats —
  regenerating does **not** fix it).

**Scratch workspace / traps:**
- ⚠️ **`mavis/assets/avatar/keanu.bam` is gitignored and absent on a fresh clone.** The local
  build is dated **2026-09-22 21:51** (~93MB), which is the **good** one — it carries both
  retarget fixes. Any build older than 2026-09-22 is wrong twice over. Don't rebuild it
  without reason; it needs Blender.
- ⚠️ **The avatar LaunchAgent starts immediately on install** (`RunAtLoad` + `bootstrap`) —
  a Panda3D window appears and the mic opens *at that moment*, not just at next login.
  **It was deliberately NOT installed this session**; the owner picks the moment.
- ⚠️ **Testing the installer without `--dry-run` pollutes the real login session.** With
  `HOME` pointed at a temp dir the plists land in temp, but `launchctl bootstrap gui/$UID`
  still registers `com.mavis.backend`/`com.mavis.avatar` for real. This happened once during
  the session and was cleaned up with `launchctl bootout gui/$UID/<label>`. **Always use
  `--dry-run`.**
- ⚠️ **The plan ledger under-reports.** Task 5 and Task 7 steps are unticked with the code
  committed and tested. Trust `git log`.
- ⚠️ **`origin/fix/cron-watchdog-and-live-bugs` was DELETED this session** after its two
  fixes were re-applied. Commit **`c6b9ffe`** is still reachable in the local clone
  (`git show c6b9ffe`) until GC — that is the only remaining copy of the 218-line
  `cron-watchdog.yml`, which was deliberately dropped (see caveats).
- ⚠️ **`MAVIS_API_KEY` is NOT in the shell environment** and does not need to be anymore —
  the installer generates one into `~/.mavis/env`. `GROQ_API_KEY` **is** in the environment
  and the installer reads it from there.

**Not mine — leave alone:** `.DS_Store`, `.claude/`, `dashboard-data/performance_report.json`,
`dashboard-data/small/performance_report.json` (all untracked, pre-existing).

## What has changed

- **A real, live trading bug was found and fixed.** `process_symbol` is the only code that
  evaluates stop/target, and `main()` iterated `WATCHLIST` alone. **SPY (65 sh, ~$50k, stop
  754.75)** was bought 2026-08-19 when `WATCHLIST` was `["AAPL","SPY"]` and had its stop
  rewritten to `state/positions.csv` every cycle without ever being checked, from the moment
  `695abd0` changed the watchlist. **It already fired: SPY's low on 2026-09-16 was 749.60**,
  through the stop, and nothing sold. Verified against Yahoo daily lows, not assumed.
- **The miss was profitable by luck, and that framing matters.** Exiting at 754.75 =
  $49,058.75; SPY at 767.67 on 2026-09-23 = ~$49,898. Not stopping out was ~$840 *better*.
  The honest statement is "the control did not exist," not "it cost money" — this was
  surfaced to the owner explicitly before the fix, because of
  `feedback-graywind-accept-investing-risk`. He ruled it a correctness fix. Merged.
- **`fetch_bars` KeyError fixed.** alpaca-py's `BarSet.__getitem__` raises for a symbol with
  no bars rather than returning `[]` — routine for a thin symbol on the IEX feed. That
  propagated past four separate "no bars, skip" guards, making all four unreachable.
- **`feat/mavis-avatar` was pushed** (it existed only on this Mac — ~42 commits plus 8
  unpushed `main` commits). Before pushing, the **full branch history** was scanned, not just
  HEAD: the only binary blob is the **CC-BY** `jonny.glb`. The CDPR model was never committed.
  The repo is public and that constraint holds.
- **Launch-at-login built** (see "Current state"). Two agents because there are two
  processes: the avatar spawns its own warm voice worker, but nothing started the backend,
  and `brain.py` talks to `http://localhost:8000`.
- **Owner decision: always-resident model.** Both agents start at login, window stays up, mic
  listens continuously. ~300MB idle plus the 2-3GB voice worker once he speaks, on an 8GB
  machine, in exchange for an instant wake from a cold desktop. He was shown the alternatives
  and picked this.

## What has failed / risks / caveats

- **Nothing has failed.** 592 root / 180 MAVIS passing.
- **UNVERIFIED — the LaunchAgents have never actually been installed.** Every component was
  tested (see verification idioms) but the end state — Johnny appearing at login — has not
  been observed once. The avatar wrapper in particular was never run to completion, because
  it opens a window and takes the mic.
- **UNVERIFIED — carried forward, the owner has still not judged:** the 200-char latency fix,
  lipsync against real speech, the dismissal path end to end, the transparent undecorated
  window, and the cigarette in the right hand. All shipped after his last look.
- **UNRESOLVED and still blocking any voice tuning:** it was never confirmed whether the
  answer he judged "doesn't fit his character" was ChatterboxVC output or the plain
  `say -v Tom` fallback. **Check `voice.degraded` / `last_error` on the next run BEFORE
  tuning anything.**
- **The watchdog from `c6b9ffe` was deliberately NOT ported, and this overrides that commit's
  own stated plan.** Its 25-minute threshold was written against a `*/15` GitHub cron. The
  **Cloudflare cron trigger shipped 2026-09-03** (`cron-trigger/` in the repo) now dispatches
  `workflow_dispatch` every 15 min reliably — verified in run history, where GitHub's native
  `schedule:` barely fires. The watchdog would be a third trigger layer requiring a
  `WATCHDOG_PAT` that does not exist, firing duplicate runs on a healthy cadence. Its
  `13-20 → 13-21` cron widening is moot for the same reason. **Do not re-port it without
  re-checking the cadence first.**
- **`ebd105f` changes live trading behavior.** SPY's stop is enforced again from the next
  cycle. At 767.67 it sits inside its 754.75/793.25 band, so nothing sells immediately — but
  a future breach will now actually exit.
- **⚠️ Graywind grounding is still nearly empty and gates the "Johnny reads Bullion and
  Graywind" direction.** 6 facts; `retrieve()` returns 0 hits for "macro gate", "tier 1",
  "tier pools" against 5 for "gold". Ungrounded answers look identical to grounded ones —
  "how much capital does tier 1 get?" returns **Basel III bank capital ratios**.
  **Re-running the extractor does not fix it**: `extract_graywind_grounding.py` reads live
  trading state only; Graywind's *mechanics* were never in its scope. This needs a **new fact
  source**. Untouched this session.
- **Still open from 2026-09-18, needs an owner decision, no code should change without it:**
  AAPL clears 2/4 folds and SERV 1/4 against the project's own current validation bar. Both
  predate the DSR gate by design. Informational only; nothing was acted on.

## What's next (ordered)

1. **Train the wake word.** openWakeWord's `automatic_model_training.ipynb` in Colab, phrase
   **`wake up johnny`** (settled — not "johnny boy"). Drop at
   `mavis/assets/wakeword/wake_up_johnny.onnx`. ⚠️ **Do not `pip install` the training deps
   into `mavis/.venv`** — they pull torch and the runtime venv must stay torch-free.
2. **Install the agents** — `mavis/scripts/install_launch_agents.sh`. Undo with
   `--uninstall`. Logs at `~/Library/Logs/mavis-{backend,avatar}.log`. **This can be done
   before step 1**: the `W` key fallback means a launched Johnny is fully usable without the
   model, so the two halves land independently.
3. **Finish the live acceptance run** with the owner at the keyboard: wake, a real question,
   voice, lipsync, dismissal, the transparent window, the cigarette — and whether 200 chars
   is short enough. Confirm the VC-vs-Tom question in the same run.
4. **Only if he still says it is slow: chunked VC.** Needs his explicit yes — it breaks the
   spec's "audio is finished before the renderer animates" rule. Two caveats in the
   2026-09-23 handoff.
5. **Fix the grounding corpus** — prerequisite for the post-Johnny direction.
6. **Tick the plan's Task 5/6/7 checkboxes** to match reality.
7. Then `superpowers:finishing-a-development-branch`. Two things to settle first: the stray
   other-thread docs swept into `d306f45`, and the owner's username still hard-coded in
   `voice_client.py`, `pregen_lines.py` and `bullion_grounding.json`. (The three new scripts
   are clean — verified zero occurrences.)

## Verification idioms used in this project (for the resuming session)

- `cd mavis && .venv/bin/python -m pytest -q` — **180**. `keanu` tests skip when the
  gitignored model is absent. Root suite is separate (`pytest.ini` excludes `mavis/`):
  `.venv/bin/python -m pytest -q` from the repo root — **592 on `main`, 585 on
  `feat/mavis-avatar`** (see "How to resume" step 3 — both are correct). **Two suites, two
  commands; a green root run does not cover MAVIS, and a green MAVIS run does not cover the
  trading code.**
- **Read pushed live state, never the local checkout** — it goes stale fast (the cron commits
  every ~15 min): `git show origin/main:state/tier_pools.csv`, `:state/positions.csv`,
  `:dashboard-data/trade_log.csv`.
- **Mutation-test any wiring change.** `ebd105f`'s `main()` wiring was proven by reverting the
  loop to `WATCHLIST` only, and separately dropping the `entries_enabled` kwarg — each must
  fail `test_main_processes_held_off_watchlist_symbol_in_exit_only_mode`. This repo has
  already shipped a feature that was dead code because `main()`'s call site was never updated
  while every task-scoped test passed by calling the function directly.
- **Test the installer with `--dry-run` only.** Then `plutil -lint` the generated plists and
  confirm `launchctl list | grep mavis` is empty.
- **Prove the backend wrapper serves, don't read it:** run it with `MAVIS_PORT=8077`, then
  `curl -X POST :8077/ask -H 'X-API-Key: <key>' -d '{"query":"what is gold"}'` — expect
  **200** with citations, and **401** with the header omitted. Kill it afterwards.
- `gh issue list -R nguyenminhthanh0403-hub/graywind --label pending-trade --state open` —
  in-flight trade proposals awaiting an owner 👍.
- **Check both alarm labels**, not just one: `pipeline-alarm` **and** `macro-alarm` and
  `tier-pool-alarm`. "No open pipeline-alarm" no longer means nothing is wrong.
