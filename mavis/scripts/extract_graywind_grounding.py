"""Build-time snapshot of Graywind grounding data.

This script creates `mavis/data/graywind_grounding.json` from Graywind's
CSV state files. It deliberately excludes `tier_pools.csv` because the
100k account's pool balances are known-wrong as of 2026-09-15.
"""
import ast
import csv
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "graywind_grounding.json"
ACCOUNTS = [
    ("100k", REPO_ROOT / "state"),
    ("small", REPO_ROOT / "state" / "small"),
]


def latest_decision_per_symbol(csv_path: Path) -> dict[str, dict]:
    """Return the most recent decision row per symbol from a decision log.

    Unlike read_pending_trades, a missing file is not a normal empty state
    here -- it means the account/path is misconfigured -- so this
    deliberately does not guard against it and lets FileNotFoundError
    propagate.
    """
    decisions: dict[str, dict] = {}
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row["symbol"]
            decisions[symbol] = row
    return decisions


def read_pending_trades(csv_path: Path) -> list[dict]:
    """Read pending trades CSV; return empty list if the file does not exist."""
    if not csv_path.is_file():
        return []
    with csv_path.open(newline="") as f:
        return list(csv.DictReader(f))


def extract_watchlist(live_loop_path: Path) -> list[str]:
    """Extract the WATCHLIST assignment from a live_loop.py file.

    Non-greedy up to the first "]" -- correct as long as no ticker symbol
    or inline comment before the list's real closing bracket contains a
    literal "]". live_loop.py is this same project's own source, not
    adversarial input, so that holds in practice.
    """
    text = live_loop_path.read_text()
    match = re.search(r"^WATCHLIST\s*=\s*(\[.*?\])", text, re.MULTILINE | re.DOTALL)
    if not match:
        raise ValueError(f"WATCHLIST assignment not found in {live_loop_path}")
    return ast.literal_eval(match.group(1))


def build_facts(accounts_data: list[tuple[str, dict, list[dict]]], watchlist: list[str]) -> list[dict]:
    """Compose fact dictionaries from account decisions, pending trades and the watchlist."""
    facts: list[dict] = []

    watchlist_tags = ["watchlist", "graywind"] + [s.lower() for s in watchlist]
    facts.append(
        {
            "id": "watchlist",
            "tags": watchlist_tags,
            "text": f"Graywind's active trading watchlist is {', '.join(watchlist)}.",
        }
    )

    for account_name, latest_decisions, pending_trades in accounts_data:
        for symbol in sorted(latest_decisions):
            row = latest_decisions[symbol]
            fact_id = f"decision-{account_name}-{symbol}"
            tags = ["decision", "graywind", account_name.lower(), symbol.lower()]
            text = (
                f"[Graywind, {account_name} account] Most recent decision for {symbol}: "
                f"{row['action']} — \"{row['reason']}\" (as of {row['timestamp']})."
            )
            facts.append({"id": fact_id, "tags": tags, "text": text})

        for row in pending_trades:
            fact_id = f"pending-{account_name}-{row['issue_number']}"
            tags = ["pending", "graywind", account_name.lower(), row["symbol"].lower()]
            qty = float(row["qty"])
            text = (
                f"[Graywind, {account_name} account] Pending trade proposal: {row['side']} "
                f"{qty:.4f} shares of {row['symbol']} (tier {row['tier']}), proposed "
                f"{row['proposed_date']}, GitHub issue #{row['issue_number']} — awaiting manual approval."
            )
            facts.append({"id": fact_id, "tags": tags, "text": text})

    return facts


def main() -> None:
    accounts_data = []
    for account_name, state_dir in ACCOUNTS:
        latest_decisions = latest_decision_per_symbol(state_dir / "decision_log.csv")
        pending_trades = read_pending_trades(state_dir / "pending_trades.csv")
        accounts_data.append((account_name, latest_decisions, pending_trades))

    watchlist = extract_watchlist(REPO_ROOT / "live_loop.py")
    facts = build_facts(accounts_data, watchlist)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w") as f:
        json.dump({"facts": facts}, f, indent=2)
        f.write("\n")
    print(f"wrote {len(facts)} facts to {OUT_PATH}")


if __name__ == "__main__":
    main()
