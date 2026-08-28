"""Writes one cycle's dashboard update -- a new equity point, any new
trades, and a refreshed per-symbol status -- to a local scratch directory.
This module knows nothing about where the dashboard data ultimately lands;
it only writes files. merge_dashboard_export.py folds this directory's
contents into graywind's own dashboard-data/ directory (see that module
for the append-vs-overwrite distinction between equity_curve.csv/
trade_log.csv and status.csv).
"""
import csv
import os

EQUITY_POINT_FIELDS = ["timestamp", "equity"]
TRADE_FIELDS = ["timestamp", "symbol", "side", "qty", "price", "reason"]
STATUS_FIELDS = [
    "last_cycle_timestamp", "account_equity", "today_pnl", "symbol",
    "position_open", "shares", "entry_price", "current_price", "action", "reason",
]

_UNEVALUATED_STATUS = {
    "position_open": "", "shares": "", "entry_price": "", "current_price": "",
    "action": "unknown", "reason": "cycle did not evaluate this symbol",
}

# The FINAL destination directory ("dashboard-data") -- distinct from
# write_cycle_export's `export_dir` parameter above, which is a scratch
# directory ("dashboard_export") that a separate step (merge_dashboard_
# export.py) later merges into this final destination. Two similarly-named
# but opposite-ends-of-the-pipeline concepts living in this same file.
DEFAULT_DASHBOARD_DIR = "dashboard-data"
NEWS_DEBATE_LOG_FILENAME = "news_debate_log.csv"
NEWS_DEBATE_LOG_FIELDS = [
    "timestamp", "symbol", "vader_score", "vader_gate_result",
    "debate_score", "debate_reasoning",
]


def _fmt(value):
    return "" if value is None else str(value)


def write_cycle_export(export_dir, timestamp, symbols, equity, today_pnl, symbol_statuses, cycle_trades):
    os.makedirs(export_dir, exist_ok=True)

    with open(os.path.join(export_dir, "new_equity_point.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EQUITY_POINT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerow({"timestamp": timestamp, "equity": _fmt(equity)})

    with open(os.path.join(export_dir, "new_trades.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_FIELDS, lineterminator="\n")
        writer.writeheader()
        for trade in cycle_trades:
            writer.writerow({field: trade[field] for field in TRADE_FIELDS})

    with open(os.path.join(export_dir, "status.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=STATUS_FIELDS, lineterminator="\n")
        writer.writeheader()
        for symbol in symbols:
            status = symbol_statuses.get(symbol, _UNEVALUATED_STATUS)
            writer.writerow({
                "last_cycle_timestamp": timestamp,
                "account_equity": _fmt(equity),
                "today_pnl": _fmt(today_pnl),
                "symbol": symbol,
                "position_open": _fmt(status["position_open"]),
                "shares": _fmt(status["shares"]),
                "entry_price": _fmt(status["entry_price"]),
                "current_price": _fmt(status["current_price"]),
                "action": status["action"],
                "reason": status["reason"],
            })


def log_news_debate(rows, dashboard_dir=DEFAULT_DASHBOARD_DIR):
    """Appends shadow-mode news-debate rows to
    <dashboard_dir>/news_debate_log.csv, accumulating across every cycle
    ever run -- same append-forever semantics as append_decision_log in
    state_store.py (list of rows, no-op on empty, header written once),
    just targeting dashboard-data/ directly instead of state/ (this data
    is dashboard-facing history like trade_log.csv/equity_curve.csv, not
    operational state). Written directly here rather than through the
    scratch-dir-then-merge_dashboard_export.py two-step used for
    trade_log.csv/equity_curve.csv/status.csv, since live-trading.yml's
    final `git add -A dashboard-data` step picks up any file in that
    directory regardless of how it got there -- no workflow change needed.
    """
    if not rows:
        return
    os.makedirs(dashboard_dir, exist_ok=True)
    path = os.path.join(dashboard_dir, NEWS_DEBATE_LOG_FILENAME)
    file_exists = os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=NEWS_DEBATE_LOG_FIELDS, lineterminator="\n")
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)
