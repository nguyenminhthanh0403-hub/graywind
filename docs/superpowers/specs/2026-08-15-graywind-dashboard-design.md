# Graywind Dashboard — Design

**Date:** 2026-08-15
**Status:** approved, pending implementation plan
**Prior art referenced:** Bullion's live-data pipeline (`financial-map.html`,
`.github/workflows/daily-data.yml`, `_config.yml` in
`/Users/thanhnguyen/minhthanh0403/claude-projects/claudekit`)

## Goal

A public-facing (but unlisted) dashboard for the Graywind trading bot's paper-trading
burn-in: current status, an equity curve across the whole burn-in period, and a scrollable
trade log. Built on the same "cron does the work, static site reads committed data" pattern
Bullion already proved out, adapted for two repos instead of one and CSV instead of JSON.

Graywind Phase 1 (the bot itself) is complete and merged to `main` (`1682e85`). This is a
follow-on feature, independent of the still-unstarted burn-in clock (see
`docs/superpowers/burn-in-decision.md` — real Alpaca/FRED/Finnhub credentials are still
needed before burn-in starts; that is tracked separately from this dashboard work).

## Repo Structure — two repos (Approach B)

- **`graywind`** (existing, this repo) — private. Bot code + strategy logic stays here,
  isolated from anything public-facing.
- **`graywind-dashboard`** (new) — private, unlisted GitHub Pages URL (same privacy model
  as originally considered for a single-repo approach: keeps it out of search engines and
  repo listings, but the exact URL is reachable by anyone — GitHub's free tier has no login
  wall for Pages; true access control needs GitHub Pro). Contains only sanitized
  position/P&L/trade data, no strategy source.

Two repos over one: more isolation if the unlisted dashboard URL ever leaks (bot's strategy
source stays fully separate), accepted as worth the extra setup despite the project's tight
time budget.

## Data Format — CSV everywhere, no JSON

Applies to both the bot's internal operational state and the dashboard's display data.
Rationale: this data is small (thousands of rows/year at most), accumulates via git commits
every cycle, and needs clean single-line diffs plus zero-dependency parsing in vanilla
browser JS. Heavier "market-leading" formats (Parquet, Arrow, DuckDB-wasm) are built for
large-scale analytics workloads this project will never reach, and would add real
dependency/load-time cost for no benefit. SQLite was rejected because binary diffs defeat
the point of a git-committed accumulating log. NDJSON was rejected because it's still JSON
syntax, which doesn't address the underlying preference against JSON.

### `graywind` repo — internal operational state (replaces `live_state.json`)

Not read by any browser; Python-internal only. Decomposed into two small tabular files
instead of one nested JSON object:

- **`state/positions.csv`** — one row per open position: `symbol,qty,entry_price,entry_time`.
  **Overwritten** each cycle (reflects current holdings, not history).
- **`state/operational.csv`** — single header + single data row:
  `cash,day_trade_count,day_trade_window_start,drawdown_baseline,last_cycle_timestamp`.
  **Overwritten** each cycle.

Both paths come out of `.gitignore` and are committed by the bot's workflow every cycle —
required because GitHub Actions runners are ephemeral and nothing survives between separate
scheduled runs except what's committed to the repo. This is a real change to already-shipped
Phase 1 code (`graywind_strategy/state_store.py`, `.gitignore`), not just new dashboard code.

### `graywind-dashboard` repo — display data

- **`data/equity_curve.csv`** — `timestamp,equity`. **Append-only.**
- **`data/trade_log.csv`** — `timestamp,symbol,side,qty,price,reason`. **Append-only.**
- **`data/status.csv`** — open positions, today's P&L, last-cycle timestamp, per-symbol
  gate/decision reasoning. **Overwritten** each cycle (a snapshot, not history).

## Execution Model

- Bot execution moves from local cron to **GitHub Actions**, scheduled every 15 minutes,
  9:30am–4:00pm ET, Monday–Friday. Local cron only fires if the Mac is awake/logged
  in/unlocked at that exact moment; a missed cycle silently gaps the 4-week burn-in record.
  Actions runs regardless of the Mac's state.
- The `graywind` workflow runs `live_loop.py`, then:
  1. Writes/commits `state/positions.csv` + `state/operational.csv` to **its own repo** first,
     independent of anything dashboard-related — this must succeed or fail on its own.
  2. Computes the incremental dashboard update (one new equity point, any new trade rows,
     a refreshed status row) and pushes it into `graywind-dashboard` using a fine-grained
     PAT (scoped to only that repo) stored as a secret in `graywind`
     (`DASHBOARD_REPO_PAT`).
- `graywind-dashboard` has **no workflow of its own** — it's a pure push target. Its only
  content is the committed CSVs plus `index.html`.

## Dashboard Frontend

Single static `index.html` in `graywind-dashboard`, vanilla JS + D3, no build step, no
framework — same pattern as `financial-map.html`. `fetch()`s the three CSVs at load time,
parses them client-side (plain string splitting, no CSV library needed at this scale),
renders:
- An equity curve chart across the full burn-in period.
- A scrollable trade log table.
- A status panel: open positions, today's P&L, last-cycle timestamp, per-symbol
  gate/decision reasoning.

Served via GitHub Pages from `graywind-dashboard`, reusing Bullion's `_config.yml`
Jekyll-exclude workaround if needed.

## Error Handling

- **Cross-repo push failure** (bad PAT, network blip, conflict) must never block the bot's
  own operational continuity — `graywind`'s own state commit happens first and
  independently. If the dashboard push fails, the trading cycle still completed safely; the
  dashboard just misses one refresh and catches up next cycle (it reads committed history,
  not a live feed).
- **A failed trading cycle** (gate rejection, broker API error) still writes a `status.csv`
  row reflecting that outcome — "last cycle failed / no trade" is a real status, not a
  missing file.
- Reuse Bullion's existing failure-alert pattern (`.github/workflows/daily-data.yml`'s
  auto-filed GitHub issue on workflow failure) for both repos' workflows, so a silent cron
  failure — the exact failure mode already seen once on Bullion — gets surfaced instead of
  going quiet.

## Testing

- **Two-run round-trip simulation**: actually execute the workflow logic twice in sequence
  against a scratch copy of the CSVs, and confirm the second run correctly *appends* (not
  overwrites) `equity_curve.csv`/`trade_log.csv` while correctly *overwriting*
  `status.csv`/`positions.csv`/`operational.csv`. Verified by running it, not by reading the
  code, per this project's standing discipline (Phase 1 caught real bugs this way in nearly
  every task).
- **Cross-repo push dry run**: verify the PAT has write access and the push mechanism works
  against a throwaway commit before wiring it into the live schedule.
- `pytest tests/` gets new cases for the CSV read/write paths in `state_store.py`, replacing
  whatever covered the old JSON path.

## Manual Setup Required (not automatable, human-only steps)

`graywind` currently has **no git remote at all** — it has been 100% local since Phase 1.
Before implementation can wire up either workflow, the user must, outside of Claude Code:

1. Create the `graywind` GitHub repo (private) and add it as this local repo's remote.
2. Create the `graywind-dashboard` GitHub repo (private).
3. Generate a fine-grained PAT scoped to write-access on `graywind-dashboard` only, and add
   it as the `DASHBOARD_REPO_PAT` secret in `graywind`'s repo settings.
4. Enable GitHub Pages on `graywind-dashboard` (serving from the branch/folder the
   implementation plan settles on).

The implementation plan should surface these as explicit checkpoints, not assume they've
silently happened.

## Explicitly Out of Scope

- Any authentication/access-control layer on the dashboard (accepted tradeoff of the
  unlisted-URL privacy model).
- Starting the burn-in clock itself, or obtaining real Alpaca/FRED/Finnhub credentials —
  tracked separately in `docs/superpowers/burn-in-decision.md`, independent of this feature.
- Any change to the strategy/decision logic in `graywind_strategy/` beyond the state
  persistence format.
