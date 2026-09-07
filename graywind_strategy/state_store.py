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
import tempfile
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
TIER1_HOLDINGS_FILENAME = "tier1_holdings.csv"
TIER1_HOLDINGS_FIELDS = ["symbol", "qty"]
EQUITY_HISTORY_FILENAME = "equity_history.csv"
EQUITY_HISTORY_FIELDS = ["day", "equity"]
DECISION_LOG_FILENAME = "decision_log.csv"
DECISION_LOG_FIELDS = [
    "timestamp", "symbol", "action", "reason", "rsi", "sma_fast", "sma_slow",
    "vix", "sentiment", "days_to_earnings", "macro_breaches", "sector_gates",
]
PENDING_TRADES_FILENAME = "pending_trades.csv"
PENDING_TRADES_FIELDS = [
    "symbol", "issue_number", "side", "qty", "price_at_proposal",
    "stop_price", "target_price", "tier", "proposed_date",
]


def _atomic_write_csv(path, fieldnames, rows):
    """Writes `rows` to `path` as a CSV via a temp file + os.replace, mirroring
    the pattern already used by backtest_gate.py's _append_trial. A process
    killed mid-write (cron timeout, OOM, SIGTERM) can otherwise leave a
    truncated file in a plain open(path, "w") -- the load_* functions below
    read these files on every cycle, and several of them raise on a
    malformed row, so a truncated snapshot used to crash every cycle
    thereafter. Writing to a sibling temp file first means the swap either
    lands completely or not at all -- the original file is never touched
    until the new content is fully written.
    """
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".state_store_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


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
        try:
            positions = {}
            with open(positions_path, newline="") as f:
                for row in csv.DictReader(f):
                    positions[row["symbol"]] = {
                        "entry_price": float(row["entry_price"]),
                        "shares": float(row["shares"]),
                        "stop": float(row["stop"]),
                        "target": float(row["target"]),
                        "opened_date": row["opened_date"],
                    }
            state["open_positions"] = positions
        except (ValueError, KeyError, TypeError) as exc:
            # Degrades like load_equity_history rather than raising: this sits
            # above live_loop's try/finally, so an unguarded raise would abort
            # the whole cycle, including the stop/target exit checks. Falling
            # back to {} is safe -- reconcile_positions() (live_loop.py) already
            # treats a broker position missing from local state as "unmanaged,
            # warn loudly" rather than fabricating one.
            print(
                f"positions at {positions_path} are unreadable ({exc}); continuing with no "
                "locally tracked open positions -- reconcile_positions will flag any broker "
                "position this drops as unmanaged rather than crashing the whole cycle",
                file=sys.stderr,
            )

    return state


def save_state(state, state_dir=DEFAULT_STATE_DIR):
    os.makedirs(state_dir, exist_ok=True)

    _atomic_write_csv(
        os.path.join(state_dir, OPERATIONAL_FILENAME), OPERATIONAL_FIELDS,
        [{
            "day": state["day"] or "",
            "starting_equity": state["starting_equity"] if state["starting_equity"] is not None else "",
            "day_trade_dates": ";".join(state["day_trade_dates"]),
        }],
    )

    _atomic_write_csv(
        os.path.join(state_dir, POSITIONS_FILENAME), POSITIONS_FIELDS,
        [{"symbol": symbol, **position} for symbol, position in state["open_positions"].items()],
    )


def load_tier_pools(state_dir=DEFAULT_STATE_DIR):
    defaults = {1: 0.0, 2: 0.0, 3: 0.0}
    path = os.path.join(state_dir, TIER_POOLS_FILENAME)
    if os.path.exists(path):
        try:
            tier_pools = dict(defaults)
            with open(path, newline="") as f:
                for row in csv.DictReader(f):
                    tier_pools[int(row["tier"])] = float(row["cash"])
            return tier_pools
        except (ValueError, KeyError, TypeError) as exc:
            # See load_state's positions handling above for why this degrades
            # instead of raising. Zeroed tier pools is the same fallback a
            # brand-new deploy starts from, not a novel state.
            print(
                f"tier pools at {path} are unreadable ({exc}); continuing with zeroed tier "
                "pools rather than crashing the whole cycle", file=sys.stderr,
            )
    return dict(defaults)


def save_tier_pools(tier_pools, state_dir=DEFAULT_STATE_DIR):
    os.makedirs(state_dir, exist_ok=True)
    _atomic_write_csv(
        os.path.join(state_dir, TIER_POOLS_FILENAME), TIER_POOLS_FIELDS,
        [{"tier": tier, "cash": cash} for tier, cash in tier_pools.items()],
    )


def load_tier1_holdings(state_dir=DEFAULT_STATE_DIR):
    path = os.path.join(state_dir, TIER1_HOLDINGS_FILENAME)
    if os.path.exists(path):
        try:
            holdings = {}
            with open(path, newline="") as f:
                for row in csv.DictReader(f):
                    holdings[row["symbol"]] = float(row["qty"])
            return holdings
        except (ValueError, KeyError, TypeError) as exc:
            # See load_state's positions handling above for why this degrades
            # instead of raising. run_tier1_rebalance (live_loop.py) treats a
            # symbol missing from last_known_holdings as "not decreased since
            # last observed" (defaults to its current qty), so this never
            # fabricates a phantom credit -- it just re-establishes tracking
            # from the next cycle's fresh broker read.
            print(
                f"tier1 holdings at {path} are unreadable ({exc}); continuing with no known "
                "holdings rather than crashing the whole cycle", file=sys.stderr,
            )
    return {}


def save_tier1_holdings(holdings, state_dir=DEFAULT_STATE_DIR):
    os.makedirs(state_dir, exist_ok=True)
    _atomic_write_csv(
        os.path.join(state_dir, TIER1_HOLDINGS_FILENAME), TIER1_HOLDINGS_FIELDS,
        [{"symbol": symbol, "qty": qty} for symbol, qty in holdings.items()],
    )


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


def load_pending_trades(state_dir=DEFAULT_STATE_DIR):
    path = os.path.join(state_dir, PENDING_TRADES_FILENAME)
    if os.path.exists(path):
        try:
            pending_trades = {}
            with open(path, newline="") as f:
                for row in csv.DictReader(f):
                    pending_trades[row["symbol"]] = {
                        "issue_number": int(row["issue_number"]),
                        "side": row["side"],
                        "qty": float(row["qty"]),
                        "price_at_proposal": float(row["price_at_proposal"]),
                        "stop_price": float(row["stop_price"]) if row["stop_price"] else None,
                        "target_price": float(row["target_price"]) if row["target_price"] else None,
                        "tier": int(row["tier"]) if row["tier"] else None,
                        "proposed_date": row["proposed_date"],
                    }
            return pending_trades
        except (ValueError, KeyError, TypeError) as exc:
            # See load_state's positions handling above for why this degrades
            # instead of raising. A proposal's GitHub issue still exists even
            # if this local row is dropped -- worst case, process_symbol's
            # `symbol in pending_trades` dedup misses it and a duplicate
            # proposal issue gets opened next cycle, which is recoverable;
            # crashing the whole cycle over stops going unchecked is not.
            print(
                f"pending trades at {path} are unreadable ({exc}); continuing with no locally "
                "tracked proposals rather than crashing the whole cycle", file=sys.stderr,
            )
    return {}


def save_pending_trades(pending_trades, state_dir=DEFAULT_STATE_DIR):
    os.makedirs(state_dir, exist_ok=True)
    _atomic_write_csv(
        os.path.join(state_dir, PENDING_TRADES_FILENAME), PENDING_TRADES_FIELDS,
        [
            {
                "symbol": symbol,
                "issue_number": trade["issue_number"],
                "side": trade["side"],
                "qty": trade["qty"],
                "price_at_proposal": trade["price_at_proposal"],
                "stop_price": trade["stop_price"] if trade["stop_price"] is not None else "",
                "target_price": trade["target_price"] if trade["target_price"] is not None else "",
                "tier": trade["tier"] if trade["tier"] is not None else "",
                "proposed_date": trade["proposed_date"],
            }
            for symbol, trade in pending_trades.items()
        ],
    )
