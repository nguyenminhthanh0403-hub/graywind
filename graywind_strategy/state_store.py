"""Persists PDT-throttle, drawdown-breaker, and open-position state to a
local JSON file between live_loop.py invocations, since each run is a
fresh process (a cron-invoked script, not a long-running one)."""
import json
import os

DEFAULT_STATE_PATH = "state/live_state.json"


def load_state(path=DEFAULT_STATE_PATH):
    if not os.path.exists(path):
        return {"day_trade_dates": [], "day": None, "starting_equity": None, "open_positions": {}}
    with open(path) as f:
        state = json.load(f)
        state.setdefault("day_trade_dates", [])
        state.setdefault("day", None)
        state.setdefault("starting_equity", None)
        state.setdefault("open_positions", {})
        return state


def save_state(state, path=DEFAULT_STATE_PATH):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f)
