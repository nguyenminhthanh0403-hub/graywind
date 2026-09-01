"""Persists PDT-throttle, drawdown-breaker, and open-position state as a set
of CSV files in a directory between live_loop.py invocations, since each run
is a fresh process (a cron-invoked script, not a long-running one).

Separate files rather than one nested blob because they have different
overwrite semantics once this state also feeds the dashboard export
(dashboard_export.py):

- SNAPSHOT, fully overwritten every save: positions.csv (current holdings),
  operational.csv (a single scalar row), tier_pools.csv, tier1_rebalance.csv.
- APPEND-FOREVER: decision_log.csv, matching the dashboard's own
  equity_curve.csv/trade_log.csv semantics.
- WINDOWED, overwritten every save but spanning days: equity_history.csv,
  which backs RollingDrawdownBreaker. It is neither a pure snapshot (it
  needs cross-day memory) nor append-forever (it is pruned to the breaker's
  window), and it holds one row per calendar day rather than one per cycle so
  the file stays bounded by window length instead of growing with cycle count.

Note for schema changes: load_state reads operational.csv fields by direct
dict indexing, so adding a column to OPERATIONAL_FIELDS would KeyError on the
already-committed state file at the next live cycle. New state belongs in a
new file (as equity_history.csv does) unless a migration path is written.
"""
import csv
import os
import sys
from datetime import date

DEFAULT_STATE_DIR = "state"
OPERATIONAL_FILENAME = "operational.csv"
POSITIONS_FILENAME = "positions.csv"
OPERATIONAL_FIELDS = ["day", "starting_equity", "day_trade_dates"]
POSITIONS_FIELDS = ["symbol", "entry_price", "shares", "stop", "target", "opened_date"]
TIER_POOLS_FILENAME = "tier_pools.csv"
TIER_POOLS_FIELDS = ["tier", "cash"]
REBALANCE_FILENAME = "tier1_rebalance.csv"
REBALANCE_FIELDS = ["last_rebalance_month"]
EQUITY_HISTORY_FILENAME = "equity_history.csv"
EQUITY_HISTORY_FIELDS = ["day", "equity"]
DECISION_LOG_FILENAME = "decision_log.csv"
DECISION_LOG_FIELDS = [
    "timestamp", "symbol", "action", "reason", "rsi", "sma_fast", "sma_slow",
    "vix", "sentiment", "days_to_earnings", "macro_breaches", "sector_gates",
]


def load_state(state_dir=DEFAULT_STATE_DIR):
    state = {"day_trade_dates": [], "day": None, "starting_equity": None, "open_positions": {}}

    operational_path = os.path.join(state_dir, OPERATIONAL_FILENAME)
    if os.path.exists(operational_path):
        with open(operational_path, newline="") as f:
            row = next(csv.DictReader(f), None)
        if row is not None:
            state["day"] = row["day"] or None
            state["starting_equity"] = float(row["starting_equity"]) if row["starting_equity"] else None
            state["day_trade_dates"] = row["day_trade_dates"].split(";") if row["day_trade_dates"] else []

    positions_path = os.path.join(state_dir, POSITIONS_FILENAME)
    if os.path.exists(positions_path):
        with open(positions_path, newline="") as f:
            for row in csv.DictReader(f):
                state["open_positions"][row["symbol"]] = {
                    "entry_price": float(row["entry_price"]),
                    "shares": float(row["shares"]),
                    "stop": float(row["stop"]),
                    "target": float(row["target"]),
                    "opened_date": row["opened_date"],
                }

    return state


def save_state(state, state_dir=DEFAULT_STATE_DIR):
    os.makedirs(state_dir, exist_ok=True)

    with open(os.path.join(state_dir, OPERATIONAL_FILENAME), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OPERATIONAL_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerow({
            "day": state["day"] or "",
            "starting_equity": state["starting_equity"] if state["starting_equity"] is not None else "",
            "day_trade_dates": ";".join(state["day_trade_dates"]),
        })

    with open(os.path.join(state_dir, POSITIONS_FILENAME), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=POSITIONS_FIELDS, lineterminator="\n")
        writer.writeheader()
        for symbol, position in state["open_positions"].items():
            writer.writerow({"symbol": symbol, **position})


def load_tier_pools(state_dir=DEFAULT_STATE_DIR):
    tier_pools = {1: 0.0, 2: 0.0, 3: 0.0}
    path = os.path.join(state_dir, TIER_POOLS_FILENAME)
    if os.path.exists(path):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                tier_pools[int(row["tier"])] = float(row["cash"])
    return tier_pools


def save_tier_pools(tier_pools, state_dir=DEFAULT_STATE_DIR):
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, TIER_POOLS_FILENAME), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TIER_POOLS_FIELDS, lineterminator="\n")
        writer.writeheader()
        for tier, cash in tier_pools.items():
            writer.writerow({"tier": tier, "cash": cash})


def load_rebalance_state(state_dir=DEFAULT_STATE_DIR):
    path = os.path.join(state_dir, REBALANCE_FILENAME)
    if os.path.exists(path):
        with open(path, newline="") as f:
            row = next(csv.DictReader(f), None)
        if row is not None:
            return {"last_rebalance_month": row["last_rebalance_month"] or None}
    return {"last_rebalance_month": None}


def save_rebalance_state(rebalance_state, state_dir=DEFAULT_STATE_DIR):
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, REBALANCE_FILENAME), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REBALANCE_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerow({"last_rebalance_month": rebalance_state["last_rebalance_month"] or ""})


def load_equity_history(state_dir=DEFAULT_STATE_DIR):
    """Returns [(date, equity)] for RollingDrawdownBreaker, oldest first. An
    absent file returns [] rather than raising -- the breaker is permissive on
    empty history by design (see risk/drawdown_breaker.py), which is what lets
    this ship into a live cron whose state dir has no history yet.

    A MALFORMED file also degrades to [] rather than raising, unlike the other
    loaders here, because this file's risk profile is different: it is rewritten
    every cycle and committed, so a run cancelled mid-write leaves a truncated
    final line. live_loop calls this ABOVE its try/finally, so raising would not
    just fail the cycle -- it would skip save_state/save_tier_pools/
    append_decision_log too, losing that cycle's open-position and day-trade
    progress, and would then fail identically forever until hand-repaired.
    Degrading to empty costs at most a temporarily permissive rolling breaker
    (the daily breaker is unaffected); raising costs the live loop. Warned, not
    silent, so a persistently corrupt file is still visible in the job log.
    """
    path = os.path.join(state_dir, EQUITY_HISTORY_FILENAME)
    if not os.path.exists(path):
        return []
    rows = []
    try:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                rows.append((date.fromisoformat(row["day"]), float(row["equity"])))
    except (ValueError, KeyError, TypeError) as exc:
        print(
            f"equity history at {path} is unreadable ({exc}); continuing with empty "
            "history -- the rolling drawdown breaker is permissive until it refills",
            file=sys.stderr,
        )
        return []
    return sorted(rows)


def save_equity_history(rows, state_dir=DEFAULT_STATE_DIR):
    """Overwrites equity_history.csv with `rows`. The caller (the breaker) has
    already pruned to its window, so this must overwrite rather than append --
    appending would defeat the pruning and grow the file forever.
    """
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, EQUITY_HISTORY_FILENAME), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EQUITY_HISTORY_FIELDS, lineterminator="\n")
        writer.writeheader()
        for day, equity in rows:
            writer.writerow({"day": day.isoformat(), "equity": equity})


def append_decision_log(rows, state_dir=DEFAULT_STATE_DIR):
    """Appends one cycle's decision rows to <state_dir>/decision_log.csv,
    accumulating across every cycle ever run (same append-forever semantics
    as dashboard-data's equity_curve.csv/trade_log.csv, not an overwritten
    snapshot like operational.csv/positions.csv). A no-op on an empty list
    -- most cycles evaluate at least one symbol, but a cycle where every
    symbol is already held (the skip-if-holding guard in live_loop.py)
    legitimately produces zero rows. Any write failure (permissions, full
    disk) propagates -- a missing decision row would produce a misleading
    report later (a trade with no explainable "why"), so this must never
    fail silently.
    """
    if not rows:
        return
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, DECISION_LOG_FILENAME)
    file_exists = os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DECISION_LOG_FIELDS, lineterminator="\n")
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)
