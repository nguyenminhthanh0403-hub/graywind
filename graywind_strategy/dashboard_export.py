"""Writes one cycle's dashboard update -- a new equity point, any new
trades, and a refreshed per-symbol status -- to a local scratch directory.
This module knows nothing about the graywind-dashboard repo; it only
writes files. merge_dashboard_export.py folds this directory's contents
into a checkout of that repo (see that module for the append-vs-overwrite
distinction between equity_curve.csv/trade_log.csv and status.csv).
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
