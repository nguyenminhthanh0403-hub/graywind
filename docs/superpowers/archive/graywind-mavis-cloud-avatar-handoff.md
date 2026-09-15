# Graywind × MAVIS Cloud Avatar — Session Handoff

**Written:** 2026-09-14 · **For:** whoever resumes the MAVIS Cloud Avatar build (Night 3 onward). Supersedes the 2026-09-14 00:28 handoff of the same name — that version was written under a mistaken premise about the $70 credit, corrected below.

## Goal

Build a cloud-backed 3D avatar ("MAVIS") that answers questions using Bullion's audited financial-system data as grounding, reachable from a browser and from Claude CLI (via an MCP wrapper). MAVIS now lives inside the Graywind repo, at `~/Projects/graywind/mavis/`, as a real subdirectory (moved this session — previously stood alone at `~/Projects/mavis`, ungitted).

- Plan: `~/Downloads/mavis-cloud-avatar-plan.md` — **read the correction below before trusting it.** Its architecture (backend + MCP wrapper + Three.js frontend) still stands; its Fable-escalation mechanism does not.
- Progress ledger: none — this handoff is the only record. Nights 1–2 were done inline, not via subagent-driven-development.

## ⚠️ Correction — read before doing anything

The prior handoff (and the plan itself) assumed the "$70 Fable 5.1 credit, expiring ~2026-09-19" was an **Anthropic Console API credit** — something MAVIS's backend could spend by calling the Messages API directly with `ANTHROPIC_API_KEY`. **This was wrong**, confirmed with the user this session:

- The $70 is an **in-app Claude Code / claude.ai usage credit** (see `~/.claude.json`'s `announcementImpressions` — `fable-5-promo-2`/`-2-2`/`-2-3` — and `additionalModelOptionsCache`, which lists Fable as a directly-selectable model inside Claude Code).
- It is spent by the **user personally switching to the Fable 5.1 model inside Claude Code/claude.ai** (e.g. via `/model`) whenever they hit a genuinely hard task — not by any backend service calling the API.
- **No `ANTHROPIC_API_KEY` exists anywhere on this machine** (checked `~/.zshrc`, env, every project `.env` — Graywind's own `.env` still has the literal placeholder `your_anthropic_key_here`), which is consistent with this being a product-level credit rather than a console API credit.
- Consequence, decided with the user this session: **MAVIS's Fable-escalation feature is dropped, not blocked.** Even a real Anthropic API key would not have drawn down the $70 — that credit and the Messages API are billed separately. Building it out would require its own, separately-funded API key, which is out of scope now.
- **Practical takeaway for "using the $70 to its fullest potential":** there is no code path for this. It happens by the user manually picking Fable 5.1 in their Claude Code/claude.ai client when a task is hard enough to warrant it, before it expires ~2026-09-19.

## How to resume (do this first)

1. `cd ~/Projects/graywind && git status` — confirm `mavis/` and this handoff still show as untracked (they are, as of this writing; nothing has been committed yet).
2. `cd mavis && ls` — confirm `app.py`, `providers.py`, `grounding.py`, `data/`, `scripts/` are present. **`routing.py` no longer exists** — it was deleted this session (see below).
3. Read `~/Downloads/mavis-cloud-avatar-plan.md` for architecture context, but treat its Fable-escalation/budget sections (Sections 2's "escalation" tier, Section 5) as superseded by the correction above.
4. **Immediate next action:** decide whether to `git add mavis/ docs/superpowers/graywind-mavis-cloud-avatar-handoff.md` and commit — nothing has been committed yet. Then proceed to Night 3 (MCP wrapper) per the plan's remaining architecture.

## Current state (active files)

**Branch:** `main`, 0 commits ahead — all of this session's work is uncommitted in the working tree.

**Files created / changed this session (all uncommitted):**
- `mavis/` — the whole directory, moved from `~/Projects/mavis` (no history to preserve; it was never a git repo).
- `mavis/app.py` — rewritten: no more tier routing. `/ask` always calls `groq_answer()`; response no longer has `provider`/`reasons` fields on `/ask` (still present on `/status`, simplified to a single `provider` string).
- `mavis/providers.py` — `fable_answer()`, `ANTHROPIC_API_KEY`, `FABLE_MODEL`, `ANTHROPIC_URL`, `FABLE_MAX_CALLS_PER_SESSION`, and `_fable_call_count` all removed. Only `groq_answer()` remains.
- `mavis/routing.py` — **deleted.** Its sole purpose was cheap-vs-Fable tier classification; with one provider there was nothing left for it to do.
- `mavis/grounding.py` — untouched except a stale docstring line referencing `routing.py`, fixed to describe citations instead.
- `mavis/.venv/` — **recreated from scratch.** The original venv was created at `~/Projects/mavis/.venv` and has absolute paths baked into `bin/activate` and script shebangs; moving the directory left it pointing at a now-nonexistent path (`uvicorn: No such file or directory` until rebuilt). Fresh venv installed from `requirements.txt`.
- `mavis/data/bullion_grounding.json` — untouched, still the 2026-09-13/14 snapshot (39 nodes / 93 links). Graywind's top-level `.gitignore` already ignores any `data/` directory repo-wide, so this stays untracked by design, same as Graywind's own `data/`.

**Files later work will create (don't exist yet):**
- Anything for the MCP wrapper (Night 3) — no file yet. Decide where it lives: probably `mavis/mcp_server.py` or similar, now that MAVIS is a Graywind subdirectory rather than a separate repo.
- Anything for the Three.js avatar frontend (Night 4) — no file, no existing HUD to extend.
- Any auth/rate-limiting middleware (Night 5).

**Scratch workspace / traps:**
- ⚠️ **If you ever recreate or copy this venv again, rebuild it in place** (`rm -rf .venv && python3 -m venv .venv && pip install -r requirements.txt`) rather than moving/copying the directory — venvs are not relocatable.
- ⚠️ The background `uvicorn` process used for this session's verification was killed at the end. Nothing is currently running. Start fresh: `source ~/.zshrc && source .venv/bin/activate && uvicorn app:app --host 127.0.0.1 --port 8420` (source the shell profile *before* activating the venv, not after — sourcing `~/.zshrc` second overwrites `$PATH` and drops the venv's `bin/` prepend, which is what caused the first restart attempt this session to fail with `uvicorn: No such file or directory`).
- ⚠️ `data/bullion_grounding.json` is a point-in-time snapshot. Bullion is under active, frequent development (see `[[project-bullion-live-map]]` memory) — regenerate via `node scripts/extract_bullion_grounding.js <path-to-bullion_mkultra.html> data/bullion_grounding.json` if answers look stale.
- ⚠️ `data/bullion_grounding.json` is not audited third-party data (Claude-honesty-passed only) — grounded answers could confidently repeat unverified causal claims. No disclaimer has been added anywhere in MAVIS's responses yet (plan's open risk, still unaddressed).

**Not mine — leave alone:** the pre-existing untracked files in Graywind's `git status` (`.DS_Store`, `.claude/`, several `docs/superpowers/archive/*handoff*.md`, `docs/superpowers/plans/2026-09-03-*.md`, `scripts/fetch_serv_bars.py`) predate this session and are unrelated to MAVIS.

## What has changed

- **Night 1 (DONE, verified live, carried forward):** `/status` and `/ask` built and hit with real `curl` calls against Groq's free tier.
- **Night 2, routing + grounding (DONE, verified live, carried forward):** Bullion-grounding retrieval logic, including the earlier houseplant/FDIC false-positive fix.
- **This session: structural move + simplification.** MAVIS relocated into `~/Projects/graywind/mavis/`. Fable-escalation code path fully removed (not just disabled) per the corrected understanding of the $70 credit. Re-verified live after the change:
  - `GET /status` → `{"ok":true,"provider":"openai/gpt-oss-120b"}`
  - Non-grounded query ("good name for a houseplant") → real Groq answer, `citations: []`
  - Bullion-grounded query ("How does the Fed relate to repo markets?") → real Groq answer, 5 correct citations (repo, mmf, hf nodes + fed→repo, repo→banks links)

## What has failed / risks / caveats

- **Nothing has failed** as of this handoff — Night 1, Night 2's Groq/grounding path, the directory move, and the simplification are all verified live, not just code review.
- **The venv relocation issue above was a real failure this session, now fixed** — worth keeping in the traps list since it will recur if MAVIS ever moves directories again.
- MAVIS has never been committed to git. `git add mavis/` + a commit is a deliberate open action, not yet done.
- No API key auth or rate limiting exists yet (Night 5); MAVIS is local-only, not internet-reachable, so this is low urgency for now.
- The plan's open risk about unaudited Bullion grounding data still applies and is still unaddressed (see traps above).

## What's next (ordered)

1. Decide on committing: `git add mavis/ docs/superpowers/graywind-mavis-cloud-avatar-handoff.md && git commit`. Nothing forces this, but MAVIS has no other backup right now.
2. Night 3 per the plan: wrap `/ask` as an MCP server (`ask_graywind`, `query_bullion` tools), test calling it from Claude CLI locally. No file exists yet for this.
3. Night 4: build the Three.js avatar frontend from scratch (no existing HUD to extend).
4. Night 5: add API key auth + rate limiting before this is ever exposed off localhost.
5. Separately, and not gated on any of the above: **the user should personally switch to Fable 5.1 in Claude Code/claude.ai for genuinely hard tasks** before the $70 credit expires ~2026-09-19 — this is unrelated to MAVIS's codebase and needs no engineering.

## Verification idioms used in this project (for the resuming session)

- **Always hit the running server with real `curl` calls**, not just "server started cleanly" — this caught the houseplant/FDIC false positive earlier, and would catch a broken venv/PATH issue like this session's.
- **Source the shell profile before activating the venv, not after**: `source ~/.zshrc && source .venv/bin/activate && uvicorn app:app --host 127.0.0.1 --port 8420` — reversing this order lets `~/.zshrc` clobber `$PATH` and silently drop the venv.
- **Never move a venv directory** — recreate it (`rm -rf .venv && python3 -m venv .venv && pip install -r requirements.txt`) after moving the project itself.
- **Re-run `scripts/extract_bullion_grounding.js` after any Bullion map change**, and sanity-check the printed node/link counts (39/93 as of this session) against `[[project-bullion-live-map]]` memory before trusting the output.
- Kill the background `uvicorn` process after each test round — nothing should be left running between sessions.
