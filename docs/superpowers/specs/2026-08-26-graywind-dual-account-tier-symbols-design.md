# Graywind Dual-Account Rollout + Tier Symbol Guardrails — Design Spec

**Written:** 2026-08-26 · Bundles two pieces of work the user chose to scope into one spec:
multi-account infrastructure (new $2k paper account alongside the existing ~$100k one) and
**sub-project 2c** of [[project-graywind-capital-redesign]] (memory) — populating
`graywind_strategy/tier_config.py`, currently inert (`SYMBOL_TIER` and
`TIER1_SYMBOL_WEIGHTS` both empty), per
`docs/superpowers/specs/2026-08-26-graywind-tier-allocation-design.md`.

## Goal

The user created a second Alpaca paper account with $2,000, alongside the existing ~$100k
default paper account. The $100k account is a "test at larger capital" control; the $2k
account is "the realistic one." Both should run Graywind's 70/20/10 portfolio-tier split with
real symbols in every tier — today it's plumbing with nothing in it.

Two pieces, bundled into one spec at the user's explicit choice:

1. **Multi-account infrastructure.** `live_loop.py`, `state/`, `dashboard-data/`, and
   `.github/workflows/live-trading.yml` all hardcode single-account assumptions today.
2. **Tier symbol guardrails (2c).** Populate `tier_config.py` with real symbols, driven by an
   objective guardrail mechanism (not an ad hoc list) since the user intends to keep adding
   symbols — including niche/small-cap ones — over time.

**Explicitly out of scope:**
- An active-discovery/screener system for candidate symbols — declined as more effort/API
  dependency than wanted. The user picks candidate tickers manually; the guardrail only
  validates them.
- Crypto — this repo is stocks-only end to end (`StockHistoricalDataClient`/
  `StockBarsRequest` only; market-hours gating, PDT throttle, and day-trade rules all assume
  equities). Alpaca-the-platform supports paper crypto, but wiring it in is separate future
  work.
- The "stock advisor / investor" product pivot the user floated — parked, needs its own fresh
  `superpowers:brainstorming` session if pursued later. Not folded into this spec.

## Tier symbol guardrails (2c)

### Guardrail bands

`validate_symbol_addition(symbol, tier)` in `tier_config.py`, same file as the existing
`SYMBOL_TIER`/`TIER1_SYMBOL_WEIGHTS` disjointness `assert` (same pattern: a guard that raises
on violation, not a UI):

| Tier | Market cap floor | Min avg daily volume | Sector cap |
|---|---|---|---|
| 1 (buy-and-hold) | n/a — ETF-only by design | n/a | n/a |
| 2 (predicted-profitable) | $2B | 500k shares | max 3 symbols/sector |
| 3 (gamble) | $300M (deliberately low — where niche/small-cap names belong) | 100k shares | max 3 symbols/sector |

Data sources — both already available, no new secrets:
- **Market cap:** Finnhub `/stock/profile2` (`FINNHUB_API_KEY` already exists and is already
  called via plain `requests.get`, no SDK, against a different endpoint in
  `graywind_strategy/gates/earnings_gate.py`). **Unverified this session:** whether Finnhub's
  free tier includes `/stock/profile2` with a `marketCapitalization` field — confirm with a
  real request early in implementation; it's load-bearing for the whole guardrail.
- **Avg daily volume:** Alpaca historical bars via the existing `fetch_bars()`.
- **Sector, for the cap:** `SYMBOL_SECTOR` in `sector_config.py` (existing module). A symbol
  with no sector tag can't have its sector cap enforced — this is a **new soft requirement**
  the guardrail introduces (every tier-2/3 addition needs a sector tag going forward);
  `sector_gates.py`'s existing "no tag = pass" behavior elsewhere is unchanged.

### Starter symbols

Confirmed against live data this session (stockanalysis.com, checked 2026-08-26):

- **Tier 2:** `AAPL` — already tagged `tech` in `sector_config.py`. Trivially clears the band
  (multi-trillion market cap).
- **Tier 3:** `SERV` (Serve Robotics — AI delivery robots). Market cap ~$423M, 20-day avg
  volume ~5.2M shares — clears the $300M/100k floor with room to spare, well under the $2B
  tier-2 line. New `SYMBOL_SECTOR["SERV"] = "robotics"` tag (new sector — the user chose this
  over lumping it into `tech`, since SERV's small-cap-hardware/logistics risk profile doesn't
  track AAPL/NVDA/MSFT's earnings-cycle correlation).
  - `SOUN` (SoundHound AI) was the original candidate but was dropped after a live check
    showed it's grown to ~$3.1B market cap / ~32M avg volume — no longer fits "small-cap
    gamble" in spirit even though it still clears the guardrail numerically.
  - Also checked and rejected for the tier-3 slot: `RGTI` ($5.72B), `QUBT` ($1.91B), `BBAI`
    ($1.48B), `POET` ($1.40B) — all have run up past what "small-cap" means for this
    guardrail's purpose; `QUIK` ($208M) and `MVIS` ($43M) fail the $300M floor outright.
- **Tier 1:** `TIER1_SYMBOL_WEIGHTS = {"SPY": 1.0}`. **Not explicitly discussed in the prior
  brainstorming session** — the earlier handoff only worked out tiers 2/3 starter picks, but
  tier 1 (70% of every account's capital) needs at least one symbol or
  `tier1_rebalance.run_tier1_rebalance()` early-returns forever and 70% of capital sits in
  cash indefinitely. `WATCHLIST` in `live_loop.py` already had `SPY` in it pre-tiers (as a
  second intraday symbol alongside `AAPL`) and the original handoff already said SPY "moves to
  tier 1 buy-and-hold" — this makes that explicit and complete rather than introducing a new
  decision.

Resulting `graywind_strategy/tier_config.py`:

```python
SYMBOL_TIER = {"AAPL": 2, "SERV": 3}
TIER1_SYMBOL_WEIGHTS = {"SPY": 1.0}
```

And `live_loop.py`'s `WATCHLIST` becomes `["AAPL", "SERV"]` — `SPY` moves out of the intraday
`WATCHLIST` loop entirely (tier 1 is handled by the separate monthly `tier1_rebalance` path,
not `decide_trade`).

## Multi-account infrastructure

### State and dashboard-data layout

The existing `state` account's files (`state/`, `dashboard-data/`) stay exactly where they
are, untouched. The new $2k account gets nested subdirectories: `state/small/` and
`dashboard-data/small/`. Chosen over a symmetric rename (`state/100k/` + `state/2k/`) to avoid
migrating the working $100k pipeline's live paths — zero risk to what's already running.

`state_store.py` (`load_state`/`save_state`/`load_tier_pools`/`save_tier_pools`/
`load_rebalance_state`/`save_rebalance_state`) and `dashboard_export.write_cycle_export`
already accept `state_dir`/`export_dir` parameters with defaults — **no refactor needed in
either module.** `merge_dashboard_export.py` already takes `src dest` as positional CLI args
(confirmed in the existing workflow invocation) — pointing it at `dashboard-data/small` for
the second account needs no code change either.

The only code change needed is in `live_loop.py`'s `main()`, which currently calls all of the
above with no arguments (hardcoded to the defaults) and has a module-level
`DASHBOARD_EXPORT_DIR = "dashboard_export"` constant. Add a `GRAYWIND_STATE_DIR` environment
variable, defaulting to `"state"` (preserves today's behavior exactly for the $100k job):

```python
STATE_DIR = os.environ.get("GRAYWIND_STATE_DIR", "state")
...
state = load_state(state_dir=STATE_DIR)
tier_pools = load_tier_pools(state_dir=STATE_DIR)
rebalance_state = load_rebalance_state(state_dir=STATE_DIR)
...
save_state(..., state_dir=STATE_DIR)
save_tier_pools(tier_pools, state_dir=STATE_DIR)
save_rebalance_state(rebalance_state, state_dir=STATE_DIR)
```

`DASHBOARD_EXPORT_DIR` (the scratch `dashboard_export/` directory `write_cycle_export` writes
before the workflow's merge step) stays a fixed name — it's per-job-run scratch space on a
fresh checkout, not a collision risk between the two jobs since they run sequentially (see
below), each on its own runner.

Which Alpaca account a run trades against is decided entirely by which secrets the workflow
job injects as `ALPACA_API_KEY`/`ALPACA_API_SECRET` env vars — `live_loop.py` itself doesn't
need to know which account it's talking to beyond that.

### Workflow: two sequential jobs, not two files

One workflow file (`live-trading.yml`), not two — a single place to maintain the strategy
code and cron schedule, per the user's explicit choice.

**Design gap found and closed this session:** the existing job's last step does
`git add` → `commit` → `push`, and the workflow's `concurrency: group: live-cycle` block
exists specifically to stop two *overlapping workflow runs* from racing that push (documented
inline in the current YAML). Naively adding a second job or matrix entry would run both jobs
in parallel by GitHub's default — each with its own fresh checkout — and hit the exact same
non-fast-forward push race, just inside one workflow run instead of across two. Fix: the
second job depends on the first via `needs:`, forcing strict sequential execution:

```yaml
jobs:
  live-cycle:          # unchanged: $100k account, ALPACA_API_KEY/_SECRET, state, dashboard-data
    runs-on: ubuntu-latest
    steps: [... existing steps, unchanged ...]

  live-cycle-small:    # new: $2k account
    needs: live-cycle
    runs-on: ubuntu-latest
    env:
      ALPACA_API_KEY: ${{ secrets.ALPACA_API_KEY_SMALL }}
      ALPACA_API_SECRET: ${{ secrets.ALPACA_API_SECRET_SMALL }}
      FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
      FINNHUB_API_KEY: ${{ secrets.FINNHUB_API_KEY }}
      GRAYWIND_STATE_DIR: state/small
    steps:
      - [checkout, setup-python, install deps — same as live-cycle]
      - run: python3 live_loop.py
      - [same ran=true/false detection]
      - run: python3 merge_dashboard_export.py dashboard_export dashboard-data/small
      - [same commit+push step, staging state/small and dashboard-data/small]
      - [same alarm-issue steps]
```

Each job gets a fresh `actions/checkout`, so `live-cycle-small`'s checkout already includes
whatever `live-cycle` just pushed — no explicit `git pull` needed between jobs. Trade-off
accepted: total workflow wall-clock roughly doubles (two sequential live-loop cycles instead
of one), well within the 15-minute cron interval.

`FRED_API_KEY`/`FINNHUB_API_KEY` are shared macro/guardrail data sources, not
account-specific — both jobs use the same secrets for those.

### New GitHub secrets

`ALPACA_API_KEY_SMALL` / `ALPACA_API_SECRET_SMALL` for the $2k account. The existing
unsuffixed `ALPACA_API_KEY`/`ALPACA_API_SECRET` stay pointed at the $100k account, untouched.
The user generates the $2k account's keys in the Alpaca dashboard and runs
`gh secret set ALPACA_API_KEY_SMALL` / `gh secret set ALPACA_API_SECRET_SMALL` themselves —
the raw key/secret never passes through an implementation session.

### Dashboard: side-by-side columns

`index.html`'s `loadCSV(path)` already takes a path parameter (currently called three times
against `dashboard-data/equity_curve.csv`, `dashboard-data/trade_log.csv`,
`dashboard-data/status.csv`). Extend to also fetch the `dashboard-data/small/*.csv`
equivalents, and render both accounts' equity curve, trade log, and status side by side as two
columns on desktop, stacking vertically on narrow/mobile viewports. Chosen over a tabs/toggle
(hides the comparison the user actually wants) or fully stacked sections (more scrolling to
compare) — side-by-side directly serves the stated goal of comparing the $100k control against
the $2k "realistic" account at a glance.

## Error handling

- Guardrail failures (`validate_symbol_addition` raising) are a hard stop at symbol-addition
  time, same spirit as `tier_config.py`'s existing disjointness `assert` — not a live_loop.py
  runtime concern, since tier assignment happens by editing `SYMBOL_TIER` directly, not
  through a live code path.
- If Finnhub's `/stock/profile2` call fails or lacks the expected field when
  `validate_symbol_addition` runs, it should raise clearly rather than silently treating a
  missing market cap as passing — a guardrail that fails open on a missing data source isn't a
  guardrail.
- `live-cycle-small`'s failure must not block `live-cycle` (already true — `needs:` only
  blocks the dependent job from starting, it doesn't roll back the one it depends on) and must
  independently report to the same `pipeline-alarm` issue mechanism, same as today.
- `write_cycle_export`'s `DASHBOARD_EXPORT_DIR` scratch directory: unaffected by the second
  job since each job runs on its own fresh runner/checkout — no shared filesystem.

## Testing

- `validate_symbol_addition`: unit tests per band (cap pass/fail at the boundary, volume
  pass/fail at the boundary, sector-cap pass/fail at exactly 3 vs 4 same-sector symbols in a
  tier), mocking the Finnhub/Alpaca calls — same mocking style as `earnings_gate.py`'s
  existing tests.
- `live_loop.py`: `GRAYWIND_STATE_DIR` env var round-trips correctly into every
  `state_store`/`dashboard_export` call — unit test with the env var set vs. unset (unset must
  reproduce today's exact default paths, a regression guard for the $100k job).
- Workflow YAML: no automated test (matches this project's existing precedent of not
  testing `.yml` directly) — verify via `workflow_dispatch` manual run after merge, checking
  both jobs' logs and that `state/small/`, `dashboard-data/small/` appear correctly in the
  resulting commit.
- `index.html`: manual verification in a browser after deploy — both accounts' data loads and
  renders side by side, and a missing `dashboard-data/small/*.csv` (before the first successful
  small-account cycle) fails gracefully rather than breaking the $100k account's rendering.

## Deferred, not forgotten

- Screener/active-discovery system for candidate symbols — explicitly declined, guardrails
  only.
- Tier-scoped PDT/drawdown-breaker semantics remain account-wide (carried over from the
  tier-allocation spec's own deferred list, unchanged by this work).
- Lowering the existing $100k account's starting balance — a separate, still-open manual step
  from the earlier capital-redesign conversation, unrelated to standing up the new $2k
  account. `state/operational.csv` on `origin/main` showed `starting_equity: 100148.97` as of
  2026-08-25.
- Crypto support — out of scope, see Goal section.
- The "stock advisor / investor" product pivot — parked, needs its own fresh
  `superpowers:brainstorming` session.
