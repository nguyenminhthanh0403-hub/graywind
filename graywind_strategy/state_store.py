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
                    "shares": int(row["shares"]),
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
