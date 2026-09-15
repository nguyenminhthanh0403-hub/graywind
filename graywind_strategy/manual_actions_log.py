"""Appends to and reads dashboard-data/manual_actions.csv, the audit trail
for every manual trade-panel action (close/sell_partial/buy_more/
set_stop_target) dispatched from index.html's position action panel.

A GitHub Actions workflow_dispatch is fire-and-forget from the browser's
side -- the Worker that triggers it returns as soon as the dispatch is
accepted, long before the script actually runs. This file is the only
place a later rejection (market closed, breaker block, Alpaca error)
becomes visible again: read back by the dashboard's "Recent actions" feed
(see index.html's buildManualActionsFeed).

No locking around the check-then-act reads/writes below -- correctness
depends on manual-trade.yml sharing live-trading.yml's `concurrency: group:
live-cycle` (cancel-in-progress: false), which serializes every writer to
this file at the GitHub Actions level, one run at a time. Same convention
already relied on by merge_dashboard_export.py's _append_csv for
trade_log.csv/equity_curve.csv.
"""
import csv
import os

MANUAL_ACTIONS_FILENAME = "manual_actions.csv"
MANUAL_ACTIONS_FIELDS = [
    "timestamp", "symbol", "action", "qty", "status", "reason", "idempotency_key",
]


def append_manual_action(dashboard_dir, row):
    os.makedirs(dashboard_dir, exist_ok=True)
    path = os.path.join(dashboard_dir, MANUAL_ACTIONS_FILENAME)
    file_exists = os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANUAL_ACTIONS_FIELDS, lineterminator="\n")
        if not file_exists:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in MANUAL_ACTIONS_FIELDS})


def read_recent_manual_actions(dashboard_dir, limit=10):
    path = os.path.join(dashboard_dir, MANUAL_ACTIONS_FILENAME)
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    return rows[-limit:]


def has_idempotency_key(dashboard_dir, idempotency_key):
    # 500 is generous for a personal-project action log's realistic size;
    # revisit only if this file ever grows large enough to make this slow.
    return any(
        row["idempotency_key"] == idempotency_key
        for row in read_recent_manual_actions(dashboard_dir, limit=500)
    )
