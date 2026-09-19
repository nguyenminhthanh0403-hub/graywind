# MAVIS MCP Wrapper (Night 3) — Session Handoff

**Written:** 2026-09-18 · **For:** whoever resumes MAVIS next — specifically to build Night 3 of the original avatar plan (the MCP wrapper). Written because the user is about to spend a promotional Fable 5.1 credit on this specific task tonight before it expires, and wants a fresh, reliable starting point rather than working from memory.

## Goal

MAVIS is a small FastAPI backend (`mavis/`, inside the `graywind` repo) that answers questions grounded in Bullion's financial-system map and Graywind's own live trading state. It's meant to eventually be reachable three ways: browser, a Three.js avatar frontend, and Claude CLI via an MCP wrapper. Nights 1, 2, and 2.5 (Groq `/ask` + `/status`, Bullion grounding, Graywind grounding, API-key auth, rate limiting) are done and merged to `main`. **Tonight's task is Night 3 only: wrap the existing `/ask` endpoint as an MCP server** exposing tools (`ask_graywind`, `query_bullion` per the original plan) so it's callable from Claude CLI, not just curl.

- Original plan: `~/Downloads/mavis-cloud-avatar-plan.md` — **read the correction note below first.** Its architecture (Section 2, the MCP wrapper layer) still stands. Its Fable-escalation/budget sections (Section 2's "escalation" tier, Section 5) are dead — do not build against them.
- No plan file exists yet for Night 3 specifically — the last two handoffs (archived, see below) both explicitly said a **new plan is needed** before touching the MCP wrapper. This repo's convention for feature work is `superpowers:writing-plans` → `superpowers:subagent-driven-development` (or `executing-plans`), with a progress ledger under `.superpowers/sdd/<date>-<name>/progress.md`. Follow that convention here rather than freehanding it, given tonight's session is time-boxed and you want a real ledger if you have to stop mid-way.
- Progress ledger: none yet for this task — write one if you use SDD, per above.

## ⚠️ Correction — read before doing anything with "the credit"

The plan's "$70 Fable 5.1 credit" is an **in-app Claude Code/claude.ai product credit**, spent only by a human manually switching to the Fable 5.1 model inside a client session — **not** an API credit any backend code (MAVIS's or otherwise) can call. This was already tried and reverted once (commit history shows `providers.py`'s `fable_answer()`/`ANTHROPIC_API_KEY`/`FABLE_MODEL` were all removed on 2026-09-14). **Do not reintroduce any Fable/Anthropic API call into MAVIS.** MAVIS stays Groq-only. The credit is being spent simply by this session running under the Fable 5.1 model — no code should try to "wire it in."

## How to resume (do this first)

1. `cd ~/Projects/graywind && git status` — as of this writing the working tree has several unrelated untracked files (see "Not mine" below); `mavis/` itself should show clean (all of Nights 1–2.5 are committed and merged to `main`).
2. `cd mavis && .venv/bin/python -m pytest -q` — expect **36/36 passing**. If this fails, stop and figure out why before writing new code; something has drifted from this handoff.
3. Read the two archived handoffs if you want deeper history (don't need to for the task itself): `docs/superpowers/archive/graywind-mavis-cloud-avatar-handoff.md` (Nights 1–2) and `docs/superpowers/archive/graywind-mavis-grounding-and-auth-handoff.md` (Night 2.5 — grounding widened, auth + rate limiting added). Both explicitly defer Night 3 to "a new plan."
4. **Immediate next action:** write a short plan for the MCP wrapper via `superpowers:writing-plans` (scope: one new file, wraps the *existing* `/ask` endpoint, no changes to grounding/auth/rate-limiting logic), then implement it. Don't skip straight to code — this repo's last two MAVIS sessions both used a written plan + ledger, and tonight's session is credit/time-boxed, so a ledger is what makes a partial session resumable.

## Current state (active files)

**Branch:** `main`, MAVIS fully merged (last MAVIS commit: `98a48c5`, "feat(mavis): add per-key rate limiting to /ask"). No open MAVIS branch exists — start a new one for tonight's work rather than committing straight to `main` (check this repo's own convention: prior MAVIS work landed via `feat/mavis-grounding-and-auth`, merged).

**Files that exist and are done (don't rebuild):**
- `mavis/app.py` — `FastAPI` app, `GET /status` (open), `POST /ask` (requires `X-API-Key`, rate-limited, merges Bullion + Graywind grounding into context, calls `groq_answer()`).
- `mavis/auth.py` — `require_api_key` dependency, fails closed (500) if `MAVIS_API_KEY` unset.
- `mavis/rate_limit.py` — fixed-window limiter, 20 req/min, single global bucket (documented limitation, not a bug).
- `mavis/grounding.py`, `mavis/graywind_grounding.py`, `mavis/text_scoring.py` — retrieval logic over Bullion + Graywind snapshots.
- `mavis/providers.py` — Groq-only; `GROQ_MODEL`, `groq_answer()`. No Anthropic/Fable code path — keep it that way (see correction above).
- `mavis/data/bullion_grounding.json`, `mavis/data/graywind_grounding.json` — point-in-time snapshots, gitignored. Both may be stale (see traps).

**Files tonight's work will create (don't exist yet):**
- The MCP server itself — no file exists. Plan suggests `mavis/mcp_server.py`. Decide: does it import `app.py`'s functions directly (in-process), or call the running `/ask` HTTP endpoint via `httpx` (already a dependency, already used in tests)? The plan's diagram (Section 2) implies the MCP wrapper sits *in front of* the VPS backend over HTTPS — i.e. call `/ask` over HTTP with the API key, don't re-implement the grounding/auth logic in-process. Confirm this call shape as the first step of whatever plan you write.
- Whatever Python MCP SDK dependency this needs — not yet in `requirements.txt`. Check current PyPI package name/version for an MCP server SDK before adding it; none of this repo's other subprojects use MCP yet, so there's no existing convention to copy.

**Scratch workspace / traps:**
- ⚠️ **`MAVIS_API_KEY` is not set anywhere** (repo `.env`, shell env, nowhere). `/ask` will 500 until you set one. Pick a value and export it locally for testing — nothing is deployed to a VPS yet, everything is local-only.
- ⚠️ **`GROQ_API_KEY` is set in `~/.zshrc`** and available in normal shells — but do **not** print or paste its value into any file, commit, or this handoff. Just confirm `env | grep GROQ_API_KEY` shows something before testing.
- ⚠️ **Never move or copy the `mavis/.venv` directory** — it has absolute paths baked in. If you ever relocate the project, rebuild the venv in place (`rm -rf .venv && python3 -m venv .venv && pip install -r requirements.txt`).
- ⚠️ **Source `~/.zshrc` before activating the venv, not after** — the reverse order lets `.zshrc` clobber `$PATH` and drop the venv's `bin/` prepend. Use: `source ~/.zshrc && source .venv/bin/activate`.
- ⚠️ **`mavis/data/graywind_grounding.json` and `bullion_grounding.json` are snapshots, not live data.** Both go stale as Graywind's live loop and Bullion update. Not relevant to building the MCP wrapper itself, but if you smoke-test with a Graywind- or Bullion-specific query and the answer looks stale, regenerate before assuming something's broken: `python scripts/extract_graywind_grounding.py` (from `mavis/`) and `node scripts/extract_bullion_grounding.js <path> data/bullion_grounding.json`.
- ⚠️ **MAVIS is local-only** — nothing is deployed to a VPS despite the plan's "lives on your VPS" framing. The MCP wrapper you build tonight should be tested against a locally-running `uvicorn` instance, same as prior nights. Deployment is out of scope for tonight unless you explicitly decide otherwise.
- ⚠️ **Bullion's grounding data is not audited** — the plan's own open risk (Section 6), never addressed. Not blocking for the MCP wrapper itself, but don't let a resuming session assume it's been handled.

**Not mine — leave alone:** the repo's `git status` currently shows several untracked files unrelated to MAVIS — `.DS_Store`, `.claude/`, `dashboard-data/performance_report.json` and `dashboard-data/small/performance_report.json` (generated this session while writing an unrelated Graywind performance report), and a handful of `docs/superpowers/**handoff*.md`/`plans/*.md` files from other Graywind efforts (punch-list, dashboard reskin, etc.). None of these are part of tonight's task.

## What has changed

- Nothing yet for Night 3 — this handoff is written *before* tonight's session starts, to give it a clean, verified starting point. Nights 1–2.5 are done, merged, and re-verified live as of this write-up: `.venv/bin/python -m pytest -q` → 36/36 passing.

## What has failed / risks / caveats

- **Nothing has failed** — there's no Night 3 work yet to have failed.
- **UNVERIFIED (carried forward from the prior handoff):** the plan's own manual end-to-end smoke test (`uvicorn` + real `curl` against `/ask` with `MAVIS_API_KEY`/`GROQ_API_KEY` both set) was never run for Night 2.5's grounding/auth work either — only `TestClient`-based tests. Worth doing once, live, before building the MCP wrapper on top of it, so you know the layer underneath is actually solid and not just unit-tested.
- **Decision carried forward, not a bug:** rate limiting is a single global bucket (one shared `MAVIS_API_KEY` today), not per-caller. If the MCP wrapper becomes a second "caller" alongside a future browser frontend, they'll share the same 20 req/min budget — worth knowing, not necessarily worth fixing tonight.
- **Time-box reality check:** tonight's session is bounded by a promotional credit, not a deadline on the project. If the MCP SDK integration turns out to need more exploration than expected, it's fine to land a smaller, real slice (e.g., server scaffold + one working tool, tested) rather than force-finishing both `ask_graywind` and `query_bullion` in one sitting. Write the ledger so a normal-model session can finish cleanly later.

## What's next (ordered)

1. `superpowers:writing-plans` — scope a short plan for the MCP wrapper: one new file (likely `mavis/mcp_server.py`), calls the existing `/ask` endpoint (confirm HTTP-over-existing-endpoint vs. in-process import as the first decision), exposes `ask_graywind`/`query_bullion` tools per the original plan's Section 3b.
2. Implement via `superpowers:subagent-driven-development` or `superpowers:executing-plans`, whichever this session prefers — either keeps a ledger, which matters given the time-box.
3. Manual smoke test: run `uvicorn app:app --reload` locally with `MAVIS_API_KEY` and `GROQ_API_KEY` set, then actually add this MCP server to a Claude CLI config and call it live — not just unit tests. This is the same "hit it live, don't trust code review alone" discipline the prior two MAVIS sessions both used and both caught real bugs with.
4. Once verified, `superpowers:finishing-a-development-branch` to decide how it lands (this repo's convention so far: feature branch, pushed via `gh`, merged to `main`).
5. Not part of tonight, but next after this: Night 4 (Three.js avatar frontend) needs its own plan too — don't start it tonight if Night 3 runs long; a clean, tested MCP wrapper is a better stopping point than two half-finished nights.

## Verification idioms used in this project (for the resuming session)

- `cd mavis && .venv/bin/python -m pytest -q` — full suite, 36/36 as of this handoff.
- Fast retrieval sanity check without a server: `.venv/bin/python -c "import grounding; print(grounding.retrieve('...'))"` (or `graywind_grounding`).
- Always hit a **running server** with real `curl` (or, tonight, a real MCP client call) before trusting anything — every prior MAVIS session's real bugs were caught this way, not by unit tests alone.
- `source ~/.zshrc && source .venv/bin/activate` — in that order, every time, in a fresh shell.
