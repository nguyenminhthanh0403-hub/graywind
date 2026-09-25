# Graywind Trade-Approval Notifications + Tier-2/3 Auto-Approve — Session Handoff

**Written:** 2026-09-24 · **For:** a fresh session resuming the approval-gate work — to decide
the merge, release tier 1's idle ~$21.5k, and (separately) plan the MAVIS→SILVERHAND rename.

## Goal

The trade-approval gate was not filtering bad trades — it was silently discarding **every**
trade. Between 2026-09-04 and 2026-09-24, **30 consecutive proposals expired unapproved (a 100%
rejection-by-silence rate)** and no buy executed on either account for 16 days, while the
strategy kept producing buy signals on 10 separate trading days. Root cause was not the trading
logic: a bot-authored GitHub issue with no assignee and no `@mention` generates no notification
at all, and proposals expire at market close, so the owner never knew they existed.

This branch fixes both halves: proposals now reach the owner, and the tiers that never needed a
human no longer ask one.

- Spec (amended by this work, read the SUPERSEDED banner at the top first):
  `docs/superpowers/specs/2026-08-26-graywind-trade-approval-advisor-design.md`
- Tier policy constant: `graywind_strategy/tier_config.py` → `AUTO_APPROVE_TIERS`
- Prior handoff for the gate itself: `docs/superpowers/graywind-manual-trade-panel-handoff.md`

## How to resume (do this first)

1. **Re-orient on the branch.** `git log --oneline 548d196..HEAD` should show exactly 2 commits
   (`0c8b533`, `10d7544`) on `feat/approval-notifications`.
2. **⚠️ Do not trust the local checkout or local `main`.** Local `main` is stale (Sep 19).
   `origin/main` receives an automated state commit every ~15 minutes during market hours. Read
   live state with `git show origin/main:<path>`, never from the working tree.
3. **Set up a runnable test env** (see Verification idioms — the system Python cannot collect
   the suite).
4. **Immediate next action:** get the owner's explicit yes/no on merging
   `feat/approval-notifications` to `main`. Everything else is blocked behind it —
   **including the tier-1 unstamp, which must not be done first** (see What's next #2).

## Current state (active files)

**Branch:** `feat/approval-notifications`, 2 commits ahead of base `548d196`, pushed to origin.
**Not merged.** Working tree is clean apart from pre-existing untracked files.

**Files changed (committed in `0c8b533` — notifications + auto-approve):**
- `graywind_strategy/trade_approval.py` — `propose_trade` gained `owner_username` / `ntfy_topic`;
  adds `assignees` + a `cc @owner` line; new `notify_ntfy()`; `close_issue()` early-returns on
  `issue_number is None`
- `graywind_strategy/tier_config.py` — new `AUTO_APPROVE_TIERS = {2, 3}` + subset assert
- `graywind_strategy/state_store.py` — `load/save_pending_trades` tolerate an empty
  `issue_number`
- `live_loop.py` — tier branch before `propose_trade`; settle-path approval branch; `NTFY_TOPIC`
  read in `main()`; params threaded through `process_symbol` / `run_tier1_rebalance`
- `.github/workflows/live-trading.yml` — `NTFY_TOPIC` added to **both** account env blocks
- `docs/superpowers/specs/2026-08-26-graywind-trade-approval-advisor-design.md` — SUPERSEDED-IN-PART banner
- `tests/test_trade_approval.py`, `tests/test_state_store.py`, `tests/test_live_loop.py`

**Files changed (committed in `10d7544` — tier-1 credit fix, a *pre-existing* bug):**
- `live_loop.py` — `tier` now falls back to `1` for a `TIER1_SYMBOL_WEIGHTS` symbol
- `tests/test_live_loop.py` — regression test, confirmed to fail without the fix

**Files later work will modify (untouched so far):**
- `state/tier1_rebalance.csv` — holds `2026-09`; must be set to `2026-08` to release tier 1's
  idle cash. **Edit against `origin/main`, push between cycles** (they fire ~:01/:16/:31/:46 ET).
- `mavis/` (22 files on `main`, **64 on `feat/mavis-avatar`**) — the SILVERHAND rename target

**Scratch workspace / traps:**
- ⚠️ **`NTFY_TOPIC` is a bearer secret.** It was generated and set as a repo secret on 9/24.
  ntfy.sh topics are an unauthenticated public namespace — anyone holding the topic can read
  proposals and publish fakes. **Never commit the value to this repo or any doc.** Read it with
  `gh secret list` (existence only); rotate by setting a new random value if it ever leaks.
- ⚠️ **ntfy JSON must POST to the ROOT url** (`https://ntfy.sh/`) with `topic` as a *field*.
  Posting the same payload to `https://ntfy.sh/<topic>` returns **200** while delivering the raw
  JSON as the message body and silently dropping title/click/priority. Unit tests cannot catch
  this; only hitting the live service does. There is a comment in `notify_ntfy` saying so — do
  not "simplify" it back.
- ⚠️ `dashboard-data/performance_report.json` and `dashboard-data/small/performance_report.json`
  are untracked local artifacts. Not part of this work.

**Not mine — leave alone:** `.DS_Store`, `.claude/`, `mavis/assets/`, `mavis/__pycache__`,
and everything under `mavis/` (that's the SILVERHAND thread, a different branch).

## What has changed

- **`0c8b533`** — Tiers 2/3 auto-approve (no issue created; `pending_trades` row carries
  `issue_number = None`). Tier 1 stays manual, gated on **size** not discretion (~70% of capital,
  one rebalance order is an order of magnitude larger). Proposals now assign + `@mention` the
  owner and push an ntfy notification with a tappable issue link.
  - Auto-approved buys **still route through `process_pending_trades`**, so price-staleness
    re-validation, both drawdown breakers and the `tier_pools` debit all still apply. Only the
    "did a human react" question is skipped. Cost: the fill lands one cycle (~15 min) later.
    Benefit: breakers are re-checked against fresher equity than the signal saw. Executing
    inline was rejected deliberately — it would mean duplicating the settlement path to save one
    cycle, on a strategy with 4 round trips of history.
  - A row with no issue number whose tier is **not** auto-approved **fails closed and loudly**.
- **`10d7544`** — Tier-1 pool credit fix (see risks below).
- **604 tests passing** (was 594 at base: 10 added, 3 stale ones updated to assert the new
  behavior rather than to pass).
- **Live, independent of this branch:** all 4 open proposals (#39–#42) were approved manually on
  9/24 and executed cleanly — AAPL @337.32/337.38, SERV @4.425 on both accounts. First trades in
  16 days. Equity $101,875.06, +$242.12 that day. This proves the gate *mechanism* was always
  sound and the blocker was purely notification.

## What has failed / risks / caveats

- **Nothing has failed.** Both commits are green at 604 tests.
- **UNVERIFIED — the notification path has never run in CI.** `notify_ntfy` was verified
  end-to-end against live ntfy.sh by direct invocation, and issue assignment/@mention was
  verified only by unit test. The full path (workflow → `propose_trade` → assignee + ntfy) has
  **never executed in a real GitHub Actions run**, because tier 1 is the only remaining caller
  and it fires ~monthly. The tier-1 unstamp is the first real test of it — that is why the
  ordering in What's next matters.
- **UNVERIFIED — auto-approve has never run live.** No cycle has executed an auto-approved
  tier-2/3 buy yet; it is committed but unmerged.
- **`10d7544` fixes a bug that was NOT introduced by this branch.** `held_off_watchlist` came
  from commit `ebd105f` (2026-09-23). A tier-1 symbol is absent from `SYMBOL_TIER` by design, so
  `tier` resolved to `None` and `_settle_sell_fill`'s `if tier is not None` guard **discarded the
  entire proceeds** of a tier-1 stop exit — SPY is 65 shares (~$49k, about half the account),
  stop 754.75, and its low on 2026-09-16 was 749.60. Armed, not hypothetical.
- **OPEN TRADING JUDGEMENT, deliberately not decided:** should the buy-and-hold SPY core carry an
  intraday stop at all? Its stop/target are a legacy artifact from when SPY was a `WATCHLIST`
  symbol (bought 2026-08-19; tiers shipped 8/26). Stopping out 100% of the sleeve on a dip and
  re-entering at the next monthly rebalance is neither buy-and-hold nor intraday. `10d7544` only
  fixed the unambiguous accounting bug underneath it. **This needs the owner, not a subagent.**
- **Two LOW review findings left unfixed (both pre-existing):**
  1. A held, off-watchlist symbol is stop-managed but invisible on the dashboard —
     `write_cycle_export(symbols=WATCHLIST, …)` omits it, so SPY appears nowhere in
     `status.csv`. Cosmetic; fix by passing `list(WATCHLIST) + held_off_watchlist`.
  2. No cash-sufficiency check before `tier_pools[tier] -= qty * price`. Unreachable while each
     tier holds one symbol; **becomes reachable the moment a second tier-2/3 symbol is added**,
     and `tier_config.py` calls `SYMBOL_TIER` "a living list."
- **`DEEPSEEK_API_KEY` is still unset**, so proposal issues carry only the mechanical reason
  (`all checks passed`) with no advisor analysis to judge them on. Plausibly a real contributor
  to the 100% expiry rate: the owner was asked to approve a bare price-and-quantity stub.

## What's next (ordered)

1. **Get an explicit merge decision.** Merging flips live trading behavior, so it needs the
   owner's yes — do not infer it. Then:
   `git checkout main && git pull && git merge feat/approval-notifications && git push`
2. **Then, and only then, unstamp tier 1.** Set `state/tier1_rebalance.csv` to `2026-08`.
   ~$21.5k (~21% of the account) is idle and will not self-correct until October.
   **Order matters:** tier 1 is not auto-approved, so if you unstamp *before* merging, the
   resulting proposal has no notification and will expire exactly like the other 30.
   Verify after: next cycle should emit a **tier-1** proposal for ~28 SPY shares (there has
   never been one — every issue #1–#42 is tier 2 or 3), and the phone should buzz.
3. **Confirm the first auto-approved trade executes live** — watch
   `git show origin/main:dashboard-data/trade_log.csv` for a row whose reason is
   `approved via GitHub issue` arriving without any issue having existed, and confirm
   `status.csv` shows `auto-approved` rather than `pending`.
4. **Ask the owner the SPY-stop question** (risks section). It is a trading decision.
5. **MAVIS → SILVERHAND rename — DO NOT START YET.** `feat/mavis-avatar` has **55 unmerged
   commits and 64 files under `mavis/`** vs 22 on `main`, and still carries the owner's
   top-priority item (Task 6 wake word, "Wake up, Johnny"). Renaming now means git sees ~42 new
   files under a path that no longer exists plus ~124 text references conflicting. **Merge
   `feat/mavis-avatar` first, then rename in one sweep.** Before renaming, scope whether any
   deployed infrastructure has the name baked in (worker names, URLs, secrets) — a repo-only
   find-replace would break a live deployment. The name itself is good: Johnny Silverhand fits
   the existing wake word and the `johnny-persona` skill.
6. **Optional cleanup:** the two LOW findings above; add `yfinance`/`openai` to whatever the
   local dev-install path is so the suite runs without a hand-built venv.

## Verification idioms used in this project (for the resuming session)

- **The system Python cannot collect the suite.** `python` does not exist (`python3` does), and
  `yfinance` + `openai` are missing while PEP 668 blocks installing into Homebrew Python. Build
  a venv that inherits system packages:
  ```
  python3 -m venv --system-site-packages /tmp/gw-venv
  /tmp/gw-venv/bin/pip install yfinance openai
  /tmp/gw-venv/bin/python -m pytest -q        # expect 604 passed
  ```
- **Read live state from origin, never the working tree:**
  `git show origin/main:dashboard-data/status.csv | tr -d '\r'` (the CSVs carry CRLF).
- **`:s` is a zsh history modifier** — `git show $c:state/foo.csv` mangles the path. Use
  `bash -c` or assign the whole ref to one variable first.
- **Prove a regression test actually catches its bug**: revert the fix, confirm the test fails,
  restore. A passing test alone is not evidence. (Done for `10d7544`.)
- **Approval reactions must come from the repo owner** — `get_owner_reaction` matches
  `login == repo.split("/")[0]`. Confirm with `gh api user --jq .login`.
- **Check scheduled runs actually succeeded**, not just that the code looks right:
  `gh run list --workflow="Graywind Live Trading Cycle" --limit 10`.
