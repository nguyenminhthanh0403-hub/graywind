#!/usr/bin/env python3
"""Merges one cycle's local export directory (graywind_strategy/dashboard_export.py's
output) into a checkout of graywind-dashboard's data/ directory: equity_curve.csv and
trade_log.csv are APPENDED to (they accumulate history across every cycle ever run),
status.csv is fully OVERWRITTEN (it's a snapshot of the most recent cycle only).

Invoked by .github/workflows/live-trading.yml after cloning graywind-dashboard, and
directly by tests against scratch directories -- never against a real clone in a test.
"""
import csv
import os
import shutil
import sys

EQUITY_CURVE_FILENAME = "equity_curve.csv"
TRADE_LOG_FILENAME = "trade_log.csv"
STATUS_FILENAME = "status.csv"
EQUITY_POINT_FIELDS = ["timestamp", "equity"]
TRADE_FIELDS = ["timestamp", "symbol", "side", "qty", "price", "reason"]


def _append_csv(source_path, target_path, fieldnames):
    with open(source_path, newline="") as f:
        new_rows = list(csv.DictReader(f))
    if not new_rows:
        # Still ensure the target file exists with a header even on a
        # zero-row cycle, so the dashboard's fetch() never 404s.
        if not os.path.exists(target_path):
            os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
            with open(target_path, "w", newline="") as f:
                csv.DictWriter(f, fieldnames=fieldnames).writeheader()
        return

    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
    file_exists = os.path.exists(target_path)
    with open(target_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(new_rows)


def merge_export(export_dir, target_data_dir):
    os.makedirs(target_data_dir, exist_ok=True)

    _append_csv(
        os.path.join(export_dir, "new_equity_point.csv"),
        os.path.join(target_data_dir, EQUITY_CURVE_FILENAME),
        EQUITY_POINT_FIELDS,
    )
    _append_csv(
        os.path.join(export_dir, "new_trades.csv"),
        os.path.join(target_data_dir, TRADE_LOG_FILENAME),
        TRADE_FIELDS,
    )
    shutil.copyfile(
        os.path.join(export_dir, "status.csv"),
        os.path.join(target_data_dir, STATUS_FILENAME),
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: merge_dashboard_export.py <export_dir> <target_data_dir>", file=sys.stderr)
        sys.exit(1)
    merge_export(export_dir=sys.argv[1], target_data_dir=sys.argv[2])
