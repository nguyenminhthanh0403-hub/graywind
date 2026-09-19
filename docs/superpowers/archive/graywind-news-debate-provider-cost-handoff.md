# Graywind News-Debate — LLM Provider/Cost Decision — Session Handoff

**Written:** 2026-08-28 · **For:** a fresh session (or the user later) picking up an
**undecided** question: which LLM provider/tier should back the news-debate shadow-mode
feature going forward. No code was touched this session — this is a decision-pending
handoff, not a work-in-progress one.

## Goal

Sub-project 3 of 3 (news-debate shadow mode) is fully built, tested, merged, and pushed —
see the sibling handoff below for that status. It is blocked only on a human adding
`ANTHROPIC_API_KEY` as a GitHub Actions secret. Before doing that, the user opened a
side conversation: is paying for Anthropic (`claude-sonnet-5`) actually the right call here,
or should this shadow-mode-only feature run on a free/cheaper provider instead? That
question is still open. This doc exists so that decision isn't lost, and so whoever
resumes doesn't have to re-derive the pricing research from scratch.

- Sibling handoff (shipped-code status, still the deployment authority):
  `docs/superpowers/graywind-news-debate-shadow-mode-handoff.md`
- Spec (unchanged, binding): `docs/superpowers/specs/2026-08-25-graywind-news-debate-shadow-mode-design.md`
- Plan (fully executed): `docs/superpowers/plans/2026-08-27-graywind-news-debate-shadow-mode.md`
- The code being discussed: `graywind_strategy/gates/news_debate.py` (see its own docstring
  for the shadow-mode boundary and model-choice rationale)

## How to resume (do this first)

1. `git status` — confirm nothing code-related changed since this handoff (see "Current
   state" below for what's *already* sitting uncommitted from before this conversation —
   none of it is from this decision thread).
2. Re-read this file's "What's next" section — it lists the three options as presented to
   the user, with real numbers. Don't re-research pricing from memory; the numbers below
   were verified via WebFetch against `platform.claude.com` and WebSearch against current
   OpenRouter docs this session (2026-08-28).
3. Ask the user (if not already answered elsewhere in conversation) which option they
   picked. If they haven't decided, present the three options again — don't re-derive them.
4. **Immediate next action:** there is no code to write until the user picks an option.
   Once they do, jump to the matching bullet under "What's next."

## Current state (active files)

**Branch:** `main`, 0 commits ahead of `origin/main` (fully in sync, confirmed via
`git fetch origin main` — no new commits from this conversation).

**Files created / changed by this conversation:** none. This was a research/decision
conversation only — no edits to `news_debate.py`, `live_loop.py`, workflow files, or
secrets.

**Pre-existing uncommitted state (NOT from this conversation — inherited from a prior
session, left as found):**
- ⚠️ `docs/superpowers/graywind-news-debate-shadow-mode-handoff.md` has an **uncommitted
  working-tree diff** against the last commit (`1f82cba`) — 122 insertions / 213 deletions.
  The file on disk already contains the "Written: 2026-08-28 (supersedes the 2026-08-27
  handoff...)" corrected-verification content; the committed version at `1f82cba` is the
  older 2026-08-27 text. A resuming session should trust **what's on disk**, not the last
  commit, when reading that file — and should be aware it hasn't been committed yet.
- Untracked: `docs/superpowers/graywind-performance-reports-handoff.md`,
  `docs/superpowers/archive/graywind-dual-account-advisor-plans-handoff.md`,
  `docs/superpowers/archive/graywind-dual-account-tier-symbols-handoff.md`,
  `docs/superpowers/archive/graywind-quant-discipline-brainstorm-handoff.md`,
  `.claude/`, `scripts/fetch_serv_bars.py` — all pre-existing, unrelated to this thread,
  left alone.

**Not mine — leave alone:** everything in "Pre-existing uncommitted state" above, and
anything under `.claude/worktrees/`.

## What has changed

Nothing on disk. This handoff documents a **research conclusion and an open decision**,
reached via conversation only:

- Confirmed (via WebFetch of `platform.claude.com/docs/en/about-claude/pricing`): Anthropic
  has no ongoing free API tier — only a one-time signup credit, plus the token-counting
  endpoint being free (irrelevant here since this feature doesn't call it).
- Estimated current shipped-code cost if `ANTHROPIC_API_KEY` is added as-is: `claude-sonnet-5`,
  3 calls/symbol/cycle × 2 symbols × ~26 market-hours cycles/day ≈ **156 calls/day**, roughly
  **$10–20/month** at Sonnet 5 rates ($2/$10 per MTok).
- Corrected a wrong assumption made earlier in this same conversation: OpenRouter's free-model
  quota is **per-account** (50 requests/day on a free account, or 1,000/day after a one-time
  $10 lifetime credit top-up), **not per-model**. Splitting bull/bear/judge across three
  different free models does NOT give three separate quota pools — it's still one shared
  bucket. At 156 calls/day, the pure-free 50/day tier cannot cover this feature at all.
- Identified DeepSeek V4 Flash (via OpenRouter, paid but very cheap: $0.44/$1.32 per MTok)
  as a live option: roughly **$2–3/month** at this call volume — an order of magnitude
  cheaper than Sonnet 5, reputed to be close in quality to frontier proprietary models, with
  better native tool-calling reliability than small free-tier models.

## What has failed / risks / caveats

- **Nothing has failed** — no code was run or changed.
- **Real risk flagged for any free/cheap-model swap:** `news_debate.py::_tool_call()` forces
  `tool_choice` + `additionalProperties: false` and reads required fields via direct dict
  indexing (raises loudly on anything malformed — this is deliberate per the spec's testing
  requirements, not a bug). Free/small open-weight models are less reliable at honoring
  forced strict tool schemas than Anthropic/OpenAI-tier models, which risks **silent gaps**
  in `dashboard-data/news_debate_log.csv` (live_loop's fail-open catch swallows the failure,
  so a cycle just doesn't get a row — it doesn't raise an alert). This directly weakens the
  feature's own stated purpose: building comparison history to eventually judge whether the
  debate deserves promotion to authoritative.
- **UNVERIFIED / not yet decided:** which of the three options below the user wants. Do not
  assume Anthropic-as-shipped is still the default just because it's what's currently coded —
  the user was actively reconsidering it when this handoff was written.
- The existing blocker from the sibling handoff (`ANTHROPIC_API_KEY` missing as a GitHub
  secret) is **still accurate and still the only blocker** if the user ultimately chooses to
  stick with Anthropic.

## What's next (ordered)

Present these three options (already given to the user once, in these exact terms) and
implement whichever they pick — no option has been started:

1. **Keep Anthropic (`claude-sonnet-5`), no code change.** ~$10–20/month. Only remaining
   step: add `ANTHROPIC_API_KEY` as a GitHub Actions repo secret (manual, human-only —
   see the sibling handoff). Best reliability/quality, highest cost.
2. **Fully free via OpenRouter.** Requires: a one-time $10 credit top-up to OpenRouter
   (unlocks 1,000 free-model requests/day; the raw free tier's 50/day cannot cover this
   feature's ~156 calls/day). Then rewrite `news_debate.py::_tool_call()` and the injected
   `llm_client` in `live_loop.py` for OpenRouter's request/response shape (different from
   Anthropic's), pick specific free-tagged models for bull/bear/judge (e.g. Llama, Mistral,
   GLM-4.5 Air — verify current tool-calling support against
   `openrouter.ai/models?supported_parameters=tools` before committing to specific models,
   since the free catalog changes). $0/month ongoing after the one-time top-up, but carries
   the schema-reliability/log-gap risk above.
3. **Switch to DeepSeek V4 Flash via OpenRouter (paid, cheap).** ~$2–3/month. Same code
   rewrite as option 2 (OpenRouter request/response shape), but a single reliable paid model
   instead of juggling several free ones — best quality-per-dollar identified, and likely
   better schema reliability than option 2's free models. The user already has an OpenRouter
   account/key wired into this repo's GitHub secrets (per this conversation), so no new
   provider account is needed for either option 2 or 3.

Once the user picks: this becomes either (a) a manual secret-add with zero code changes
(option 1), or (b) a bounded code change to `news_debate.py`'s `_tool_call()` +
`live_loop.py`'s client wiring (options 2/3) — small enough to scope and implement directly
without a new spec/plan, per the brainstorming skill's "bounded" classification already
applied to this in conversation.

## Verification idioms used in this project (for the resuming session)

- Test suite: `.venv/bin/python -m pytest tests/ -q` — 384 passing as of the last shipped
  commit (`1f82cba`). If `anthropic` isn't installed in `.venv`, install it first
  (`pip install -r requirements.txt`).
- Checking real repo secrets (names only): requires `gh secret list` (needs `gh` CLI + auth,
  not available in this sandboxed environment) or the user reading the GitHub UI directly —
  the unauthenticated REST API returns 401 for the secrets-list endpoint.
- Before starting any provider-swap implementation, re-verify current OpenRouter free-model
  tool-calling support and rate-limit numbers live (both changed enough during this session's
  own research to require correction once already) rather than trusting this handoff's
  numbers as permanent.
