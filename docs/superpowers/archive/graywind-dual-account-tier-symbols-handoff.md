# Graywind Dual-Account Rollout + Tier Symbol Guardrails — Session Handoff

**Written:** 2026-08-25 · **For:** whoever resumes this brainstorm (still pre-spec, nothing
implemented) to finish the design, write the spec, and hand off to
`superpowers:writing-plans`.

## Goal

The user created a **second Alpaca paper account with $2,000**, alongside the existing
~$100k default paper account. Intent: the $100k account becomes a "test at larger capital"
control, and the $2k account is "the realistic one" — both should run Graywind's 70/20/10
portfolio-tier split (`graywind_strategy/tier_config.py`, shipped 2026-08-26 at `03fb9d3`,
see [[project-graywind-capital-redesign]] and `docs/superpowers/graywind-tier-allocation-handoff.md`)
which is currently **inert** — `SYMBOL_TIER` and `TIER1_SYMBOL_WEIGHTS` both ship empty.

Making that true requires two separate pieces of work, both scoped into one spec per the
user's explicit choice (see decision 3 below):

1. **Multi-account infrastructure** Graywind doesn't have today — `live_loop.py`, `state/`,
   `dashboard-data/`, and `.github/workflows/live-trading.yml` all hardcode single-account
   assumptions (one set of secrets, one state directory, one dashboard).
2. **Sub-project 2c** (populating `tier_config.py` with real symbols) — the user wants this
   driven by an objective guardrail mechanism, not an ad hoc list of popular mega-caps, since
   they intend to keep adding (including niche/small-cap) symbols over time.

- Spec: **none yet** — not written. Next session should finish the design in chat first.
- Plan: none yet.
- Progress ledger: none — this is pre-implementation, pre-spec.

This handoff exists purely to carry forward brainstorming decisions so a fresh session
doesn't have to re-ask the same questions the user already answered.

## How to resume (do this first)

1. Confirm branch: `git log --oneline -3` should show `d7e1676` ("docs: add session handoff
   for portfolio-tier allocation work") at or near the top — possibly with newer live-cron
   auto-commits above it, which is normal (see "Verification idioms").
2. **This is a live `superpowers:brainstorming` conversation, not an approved design.** Do
   not skip to writing a plan or code. Continue the brainstorm from "What's next" below.
3. Trust the decisions captured in "What has changed" as confirmed working assumptions — but
   if the user's intent seems to have shifted since this was written, re-confirm rather than
   assume staleness.
4. **Immediate next action:** get explicit user sign-off (or a swap) on the proposed starter
   tickers — `AAPL` (tier 2) and `SOUN` (tier 3) — which were proposed but not yet confirmed
   when this session ended. Then finish the remaining undecided infra details (see "What's
   next") and write the actual spec file.

## Current state (active files)

**Branch:** `main`, 0 commits ahead — **this session made zero code changes.** Everything
below is a decision captured in conversation only, not on disk anywhere else.

**Files created/changed:** none.

**Files later work will touch (once a plan exists — none are touched yet):**
- `graywind_strategy/tier_config.py` — 2c's target: populate `SYMBOL_TIER` +
  `TIER1_SYMBOL_WEIGHTS`, add a `validate_symbol_addition(symbol, tier)` guardrail function
  (same pattern as the file's existing disjointness `assert`).
- `graywind_strategy/sector_config.py` — any tier-2/3 addition (e.g. `SOUN`) needs a
  `SYMBOL_SECTOR` tag for the guardrail's per-sector cap to be enforceable — this is a **new
  soft requirement** the guardrail work introduces; `sector_gates.py`'s existing "no tag =
  pass" behavior elsewhere is unchanged.
- `live_loop.py` — `WATCHLIST` (currently `["AAPL", "SPY"]`) needs `SPY` dropped (moves to
  tier 1 buy-and-hold) and tier-2/3 symbols added; also needs `state_dir`/dashboard-export-dir
  parameterization for the second account — **not designed in detail yet**, just flagged as
  necessary.
- `.github/workflows/live-trading.yml` — needs a second job/matrix entry for the $2k account
  with its own secrets.
- `index.html` / `dashboard-data/` — needs to render both accounts side by side — **not
  designed in detail yet**.
- **New GitHub secrets** — the $2k account's Alpaca API key/secret don't exist as secrets
  yet. Naming convention proposed but **not confirmed**: keep the existing unsuffixed
  `ALPACA_API_KEY`/`ALPACA_API_SECRET` pointed at the $100k account as-is (avoid touching a
  working pipeline), add a new `*_SMALL`-suffixed pair for the $2k account.

**Scratch workspace / traps:**
- ⚠️ **No spec file exists.** Don't look for one under `docs/superpowers/specs/` for this
  effort — it hasn't been written.
- ⚠️ `tier_config.py`'s `SYMBOL_TIER` and `TIER1_SYMBOL_WEIGHTS` are confirmed empty as of
  this session's own `Read` — the 70/20/10 plumbing has zero live effect until this work
  populates them.
- ⚠️ `state/operational.csv` on `origin/main` showed `starting_equity: 100148.97` as of
  2026-08-25 — the **existing $100k account's balance has not been manually lowered**. That's
  a separate, still-open item from the earlier capital-redesign conversation, unrelated to
  standing up the new $2k account.

**Not mine — leave alone:** `docs/superpowers/graywind-news-debate-shadow-mode-handoff.md` is
untracked and belongs to a different, concurrent session's sub-project-3 (news-interpretation)
work — this warning is carried forward from `graywind-tier-allocation-handoff.md`. Deliberately
**not archived** despite being older than the 2-most-recent-by-mtime rule: that rule is for
superseded handoffs in the same lineage, not unrelated concurrent work in progress.

## What has changed

Nothing shipped — this entire session was a `superpowers:brainstorming` conversation
(architectural path: it touches the workflow, secrets, state layout, and the dashboard's data
contract, so it was classified as architectural rather than bounded). No code, no commits.

**Decisions reached (treat as confirmed unless the user says otherwise):**

1. Both accounts run the 70/20/10 tier split — this pulls sub-project 2c into scope alongside
   the multi-account infra, rather than deferring it.
2. Deployment shape: **one workflow, two jobs/matrix entries** in `live-trading.yml` — not two
   separate workflow files. One place to maintain strategy code.
3. Dashboard: **both accounts shown side by side**, not just the $2k one.
4. `tier_config.py` is meant to be a **living list**, not a one-time fixed roster — explicitly
   should support niche/small-cap names being added over time, not just mega-caps.
5. Screening depth: **guardrails only** (chosen over an active-discovery/screener system,
   which was explicitly declined as more effort/API dependency than wanted). The user still
   picks candidate tickers manually; a `validate_symbol_addition()` check enforces objective
   bands before a symbol is accepted.
6. Proposed guardrail bands (**not yet locked into a spec**):
   - Tier 2 (predicted-profitable): market cap floor $2B, min avg daily volume 500k shares.
   - Tier 3 (gamble): market cap floor $300M (deliberately low — where niche names belong),
     min avg daily volume 100k shares.
   - Both tiers: max 3 symbols sharing one sector tag, per tier.
   - Tier 1 excluded — ETF-only by design, market cap doesn't apply.
7. Data sources for the guardrail — **both already available, no new secrets needed**: market
   cap via Finnhub's `/stock/profile2` endpoint (`FINNHUB_API_KEY` already exists and is
   already called via plain `requests.get`, no SDK, against a different endpoint in
   `graywind_strategy/gates/earnings_gate.py`); avg volume via Alpaca historical bars
   (`fetch_bars()`, already used everywhere).
8. **Crypto is explicitly out of scope.** Confirmed by reading the code: this repo is
   stocks-only end to end (`StockHistoricalDataClient`/`StockBarsRequest` only, no
   `CryptoHistoricalDataClient` anywhere); market-hours gating, PDT throttle, and day-trade
   rules all assume equities. Alpaca-the-platform supports paper crypto trading, but wiring it
   in is separate future work, not part of this effort.
9. **"Stock advisor / investor" pivot — explicitly parked, not in scope.** The user floated
   eventually turning parts of Graywind into a stock advisor / investor product. This needs
   its own fresh `superpowers:brainstorming` session later if pursued. **Do not fold it into
   2c or the multi-account work** — it's a different, much larger idea.
10. Starter tickers **proposed, not yet confirmed**: Tier 2 → `AAPL` (already tagged `tech` in
    `sector_config.py`, trivially clears the band). Tier 3 → `SOUN` (SoundHound AI — small-cap,
    volatile, deliberately not a mega-cap name; would need `SYMBOL_SECTOR["SOUN"] = "tech"`).
    Flagged explicitly to the user: exact current market cap/volume for `SOUN` is unverified
    against live data (the assistant's knowledge cutoff is 2026-01, ~7 months stale relative
    to session date) — **the guardrail code's own live check is the actual verification**, not
    this proposal.

## What has failed / risks / caveats

- **Nothing has failed** — nothing was attempted yet.
- **UNVERIFIED:** whether `AAPL`/`SOUN` actually clear the proposed guardrail bands against
  live data — never checked against a real API this session. Pending both user sign-off on
  the tickers and the guardrail code's own live verification once built.
- **UNVERIFIED:** that Finnhub's free tier includes `/stock/profile2` with a
  `marketCapitalization` field — inferred from Finnhub's general API shape and the fact that
  `earnings_gate.py` already successfully calls a *different* Finnhub endpoint on the same
  key, not confirmed by an actual request this session. Check this early in implementation —
  it's load-bearing for the whole guardrail design.
- **Open, not decided:** how the new $2k account's Alpaca API key/secret actually get into
  GitHub secrets — whether the user runs `gh secret set` themselves after generating keys in
  the Alpaca dashboard, or hands the raw value to a session to set on their behalf. Not
  discussed; don't assume either way.
- **Unrelated but still pending:** lowering the existing $100k account's balance (from an
  earlier conversation, separate from this effort) was never done and remains an open manual
  step — irrelevant here since the user is deliberately keeping $100k as-is for the
  larger-capital test, but worth not confusing with the *new* $2k account setup.

## What's next (ordered)

1. Resume the brainstorm: get the user's explicit confirmation (or a swap) on the `AAPL`/
   `SOUN` starter-ticker proposal — this was the open thread when the session ended.
2. Finish the remaining undecided infra details before writing the spec:
   - GitHub secrets naming (proposed: unsuffixed pair stays on the $100k account, new
     `*_SMALL`-suffixed pair for the $2k account — not yet confirmed with the user).
   - `state/`/`dashboard-data/` directory layout for the second account (proposed: leave the
     existing flat `state/` + `dashboard-data/` as the $100k account untouched, add nested
     `state/small/` + `dashboard-data/small/` for the new account — not yet confirmed).
   - How `index.html` actually renders two accounts side by side — not designed at all yet.
3. Write the design doc to
   `docs/superpowers/specs/2026-08-25-graywind-dual-account-tier-symbols-design.md` (or
   similar), covering multi-account infra + the tier-symbol guardrail mechanism together, per
   the user's explicit choice to bundle both into one spec.
4. Run the spec self-review checklist (placeholders, internal consistency, scope, ambiguity)
   per `superpowers:brainstorming`.
5. Get user approval on the written spec file.
6. Hand off to `superpowers:writing-plans` — no other implementation skill directly from
   brainstorming.
7. Separately, later: if the user wants to revisit the "stock advisor / investor" idea, that
   needs its own fresh `superpowers:brainstorming` session — do not retrofit it onto this spec.

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
  `backtester.py`/`risk/`/`live_loop.py` changes, and uses `superpowers:brainstorming` →
  `superpowers:writing-plans` → `superpowers:subagent-driven-development` for multi-step
  Python implementation work.
- **Always check `git branch -a` and `git log --all --oneline` for unmerged work** before
  starting a new sizing/risk-related change — precedent: a fully-built, tested, unmerged
  branch sat untouched for 5 days earlier in this same capital-redesign effort with zero
  mention anywhere.
