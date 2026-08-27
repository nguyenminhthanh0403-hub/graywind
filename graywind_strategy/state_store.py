"""Persists PDT-throttle, drawdown-breaker, and open-position state as two
CSV files in a directory between live_loop.py invocations, since each run
is a fresh process (a cron-invoked script, not a long-running one).

Two files instead of one nested blob because the two halves have different
overwrite semantics once this state also feeds the dashboard export
(dashboard_export.py): positions.csv is a snapshot of CURRENT holdings
(fully overwritten every save), and so is operational.csv (a single scalar
row) -- neither accumulates history, unlike the dashboard's own
equity_curve.csv/trade_log.csv.
"""
import csv
import os

DEFAULT_STATE_DIR = "state"
OPERATIONAL_FILENAME = "operational.csv"
POSITIONS_FILENAME = "positions.csv"
OPERATIONAL_FIELDS = ["day", "starting_equity", "day_trade_dates"]
POSITIONS_FIELDS = ["symbol", "entry_price", "shares", "stop", "target", "opened_date"]
TIER_POOLS_FILENAME = "tier_pools.csv"
TIER_POOLS_FIELDS = ["tier", "cash"]
REBALANCE_FILENAME = "tier1_rebalance.csv"
REBALANCE_FIELDS = ["last_rebalance_month"]
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
