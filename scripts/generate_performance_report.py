#!/usr/bin/env python3
"""One-off script: reads trade_log.csv/equity_curve.csv (dashboard-data/)
and decision_log.csv (state/) for both the $100k and $2k paper accounts,
computes P&L/Sharpe/max-drawdown/win-rate with the backtester's
already-tested pure functions, builds a per-trade "why" narrative by
pairing each trade with its nearest decision_log.csv row, and writes
dashboard-data/performance_report.json (+ dashboard-data/small/... when
that account has data). Run with:

    python3 scripts/generate_performance_report.py

Gracefully skips an account entirely if its dashboard-data/trade_log.csv
or equity_curve.csv doesn't exist yet (matches index.html's own "couldn't
load this account's data" handling) -- decision_log.csv missing is a
softer, per-account fallback: metrics still compute from trade_log.csv/
equity_curve.csv alone, trades just get a generic narrative instead of a
real one, same honest-gap handling as the 6 pre-existing trades that
predate this feature entirely.
"""
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graywind_strategy.backtester import PERIODS_PER_YEAR_15MIN, max_drawdown, sharpe_ratio, win_rate

ACCOUNTS = [
    {"label": "100k", "state_dir": "state", "dashboard_dir": "dashboard-data"},
    {"label": "small", "state_dir": "state/small", "dashboard_dir": "dashboard-data/small"},
]


def _load_csv_rows(path):
    if not os.path.exists(path):
        return None
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_account_data(state_dir, dashboard_dir):
    trades = _load_csv_rows(os.path.join(dashboard_dir, "trade_log.csv"))
    equity_points = _load_csv_rows(os.path.join(dashboard_dir, "equity_curve.csv"))
    if trades is None or equity_points is None:
        return None
    decision_rows = _load_csv_rows(os.path.join(state_dir, "decision_log.csv")) or []
    return {"trades": trades, "equity_points": equity_points, "decision_rows": decision_rows}


def per_symbol_pnl(trades):
    breakdown = {}
    open_by_symbol = {}
    for trade in trades:
        symbol = trade["symbol"]
        if trade["side"] == "buy":
            open_by_symbol[symbol] = trade
        elif trade["side"] == "sell":
            opened = open_by_symbol.pop(symbol, None)
            if opened is not None:
                pnl = (float(trade["price"]) - float(opened["price"])) * float(trade["qty"])
                entry = breakdown.setdefault(symbol, {"trades": 0, "pnl": 0.0})
                entry["trades"] += 1
                entry["pnl"] += pnl
    return breakdown


def _nearest_decision_row(rows_for_symbol, trade_timestamp):
    if not rows_for_symbol:
        return None
    trade_dt = datetime.fromisoformat(trade_timestamp)
    return min(
        rows_for_symbol,
        key=lambda row: abs((datetime.fromisoformat(row["timestamp"]) - trade_dt).total_seconds()),
    )


def build_trade_narratives(trades, decision_rows):
    by_symbol = {}
    for row in decision_rows:
        by_symbol.setdefault(row["symbol"], []).append(row)

    narratives = []
    for trade in trades:
        match = _nearest_decision_row(by_symbol.get(trade["symbol"], []), trade["timestamp"])
        narrative = {
            "timestamp": trade["timestamp"], "symbol": trade["symbol"], "side": trade["side"],
            "qty": trade["qty"], "price": trade["price"], "reason": trade["reason"],
        }
        if match is None:
            narrative["rsi"] = None
            narrative["gate_summary"] = "no decision-log detail available for this trade"
        else:
            narrative["rsi"] = match["rsi"]
            narrative["gate_summary"] = (
                f"vix={match['vix']}, sentiment={match['sentiment']}, "
                f"days_to_earnings={match['days_to_earnings']}, "
                f"macro_breaches={match['macro_breaches']}, sector={match['sector_gates']}"
            )
        narratives.append(narrative)
    return narratives


def build_block_frequency_notes(decision_rows):
    total = len(decision_rows)
    if total == 0:
        return []
    blocked_counts = {}
    for row in decision_rows:
        if row["action"] == "blocked":
            blocked_counts[row["reason"]] = blocked_counts.get(row["reason"], 0) + 1
    notes = []
    for reason, count in sorted(blocked_counts.items(), key=lambda kv: -kv[1]):
        pct = count / total * 100
        notes.append(f"blocked by {reason} on {pct:.0f}% of cycles this period")
    return notes


def build_account_report(data):
    equity_curve = [float(row["equity"]) for row in data["equity_points"] if row["equity"]]
    sharpe = sharpe_ratio(equity_curve, periods_per_year=PERIODS_PER_YEAR_15MIN)
    max_dd = max_drawdown(equity_curve) if equity_curve else 0.0
    mapped_trades = [
        {"symbol": t["symbol"], "action": t["side"], "price": float(t["price"]), "shares": float(t["qty"])}
        for t in data["trades"]
    ]
    win = win_rate(mapped_trades)
    total_pnl = (equity_curve[-1] - equity_curve[0]) if len(equity_curve) >= 2 else 0.0

    return {
        "total_pnl": total_pnl,
        "win_rate": win,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "trade_count": len(data["trades"]),
        "per_symbol": per_symbol_pnl(data["trades"]),
        "trade_narratives": build_trade_narratives(data["trades"], data["decision_rows"]),
        "block_frequency_notes": build_block_frequency_notes(data["decision_rows"]),
    }


def generate_report():
    generated_at = datetime.now(timezone.utc).isoformat()
    report = {"generated_at": generated_at, "accounts": {}}
    for account in ACCOUNTS:
        data = load_account_data(account["state_dir"], account["dashboard_dir"])
        if data is None:
            continue
        account_report = build_account_report(data)
        report["accounts"][account["label"]] = account_report
        os.makedirs(account["dashboard_dir"], exist_ok=True)
        with open(os.path.join(account["dashboard_dir"], "performance_report.json"), "w") as f:
            json.dump({"generated_at": generated_at, **account_report}, f, indent=2)
    return report


def main():
    report = generate_report()
    if not report["accounts"]:
        print("no account data available yet")
        return
    for label, data in report["accounts"].items():
        print(
            f"{label}: {data['trade_count']} trades, P&L ${data['total_pnl']:.2f}, "
            f"win rate {data['win_rate']:.1%}, Sharpe {data['sharpe']:.2f}"
        )


if __name__ == "__main__":
    main()
