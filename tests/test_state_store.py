import csv
import os

from datetime import date

from graywind_strategy.state_store import (
    load_state, save_state, load_tier_pools, save_tier_pools,
    load_rebalance_state, save_rebalance_state, append_decision_log,
    load_equity_history, save_equity_history,
)


def test_load_equity_history_returns_empty_list_when_no_file_exists(tmp_path):
    assert load_equity_history(state_dir=str(tmp_path / "nonexistent")) == []


def test_save_then_load_round_trips_equity_history(tmp_path):
    state_dir = str(tmp_path)
    rows = [(date(2024, 1, 8), 10000.0), (date(2024, 1, 9), 9950.5)]
    save_equity_history(rows, state_dir=state_dir)
    assert load_equity_history(state_dir=state_dir) == rows


def test_save_equity_history_overwrites_rather_than_appends(tmp_path):
    state_dir = str(tmp_path)
    save_equity_history([(date(2024, 1, 8), 10000.0)], state_dir=state_dir)
    save_equity_history([(date(2024, 1, 9), 9950.0)], state_dir=state_dir)
    assert load_equity_history(state_dir=state_dir) == [(date(2024, 1, 9), 9950.0)]


def test_save_equity_history_accepts_an_empty_list(tmp_path):
    state_dir = str(tmp_path)
    save_equity_history([], state_dir=state_dir)
    assert load_equity_history(state_dir=state_dir) == []


def test_load_equity_history_degrades_to_empty_on_a_truncated_file(tmp_path, capsys):
    # A cron cancelled mid-write leaves a partial final line. Raising here would
    # abort live_loop above its try/finally and wedge every later cycle.
    state_dir = str(tmp_path)
    save_equity_history([(date(2024, 1, 8), 10000.0)], state_dir=state_dir)
    with open(os.path.join(state_dir, "equity_history.csv"), "a") as f:
        f.write("2024-01-09,not-a-num")
    assert load_equity_history(state_dir=state_dir) == []
    assert "unreadable" in capsys.readouterr().err


def test_load_equity_history_degrades_to_empty_on_a_malformed_date(tmp_path):
    state_dir = str(tmp_path)
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, "equity_history.csv"), "w") as f:
        f.write("day,equity\nnot-a-date,10000.0\n")
    assert load_equity_history(state_dir=state_dir) == []


def test_equity_history_respects_a_per_account_state_dir(tmp_path):
    main_dir = str(tmp_path / "state")
    small_dir = str(tmp_path / "state" / "small")
    save_equity_history([(date(2024, 1, 8), 100000.0)], state_dir=main_dir)
    save_equity_history([(date(2024, 1, 8), 2000.0)], state_dir=small_dir)
    assert load_equity_history(state_dir=main_dir) == [(date(2024, 1, 8), 100000.0)]
    assert load_equity_history(state_dir=small_dir) == [(date(2024, 1, 8), 2000.0)]


def test_load_state_returns_empty_defaults_when_no_files_exist(tmp_path):
    state = load_state(state_dir=str(tmp_path / "nonexistent"))
    assert state == {"day_trade_dates": [], "day": None, "starting_equity": None, "open_positions": {}}


def test_save_then_load_round_trips_operational_fields(tmp_path):
    state_dir = str(tmp_path)
    save_state(
        {
            "day_trade_dates": ["2024-01-08", "2024-01-09"],
            "day": "2024-01-09",
            "starting_equity": 10000.0,
            "open_positions": {},
        },
        state_dir=state_dir,
    )
    state = load_state(state_dir=state_dir)
    assert state["day_trade_dates"] == ["2024-01-08", "2024-01-09"]
    assert state["day"] == "2024-01-09"
    assert state["starting_equity"] == 10000.0


def test_save_then_load_round_trips_open_positions(tmp_path):
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": [], "day": "2024-01-08", "starting_equity": 10000.0,
        "open_positions": {"AAPL": {"entry_price": 150.0, "shares": 10, "stop": 147.0, "target": 154.5, "opened_date": "2024-01-08"}},
    }, state_dir=state_dir)
    state = load_state(state_dir=state_dir)
    assert state["open_positions"]["AAPL"] == {
        "entry_price": 150.0, "shares": 10, "stop": 147.0, "target": 154.5, "opened_date": "2024-01-08",
    }


def test_save_then_load_round_trips_multiple_open_positions(tmp_path):
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": [], "day": "2024-01-08", "starting_equity": 10000.0,
        "open_positions": {
            "AAPL": {"entry_price": 150.0, "shares": 10, "stop": 147.0, "target": 154.5, "opened_date": "2024-01-08"},
            "SPY": {"entry_price": 400.0, "shares": 5, "stop": 392.0, "target": 410.0, "opened_date": "2024-01-08"},
        },
    }, state_dir=state_dir)
    state = load_state(state_dir=state_dir)
    assert set(state["open_positions"].keys()) == {"AAPL", "SPY"}
    assert state["open_positions"]["SPY"]["shares"] == 5


def test_save_then_load_round_trips_fractional_shares(tmp_path):
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": [], "day": "2024-01-08", "starting_equity": 1000.0,
        "open_positions": {"AAPL": {"entry_price": 150.0, "shares": 3.4567, "stop": 147.0, "target": 154.5, "opened_date": "2024-01-08"}},
    }, state_dir=state_dir)
    state = load_state(state_dir=state_dir)
    assert state["open_positions"]["AAPL"]["shares"] == 3.4567


def test_save_then_load_round_trips_empty_open_positions(tmp_path):
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": ["2024-01-08"], "day": "2024-01-08", "starting_equity": 9500.0,
        "open_positions": {},
    }, state_dir=state_dir)
    state = load_state(state_dir=state_dir)
    assert state["open_positions"] == {}


def test_save_then_load_round_trips_empty_day_trade_dates(tmp_path):
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": [], "day": "2024-01-08", "starting_equity": 9500.0,
        "open_positions": {},
    }, state_dir=state_dir)
    state = load_state(state_dir=state_dir)
    assert state["day_trade_dates"] == []


def test_save_then_load_round_trips_none_day_and_starting_equity(tmp_path):
    # main()'s very first-ever cycle (no prior state) passes day=None,
    # starting_equity=None through save_state before any account read has
    # succeeded -- must round-trip back to None, not "" or 0.0.
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": [], "day": None, "starting_equity": None,
        "open_positions": {},
    }, state_dir=state_dir)
    state = load_state(state_dir=state_dir)
    assert state["day"] is None
    assert state["starting_equity"] is None


def test_save_writes_two_separate_csv_files(tmp_path):
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": ["2024-01-08"], "day": "2024-01-08", "starting_equity": 9500.0,
        "open_positions": {"AAPL": {"entry_price": 150.0, "shares": 10, "stop": 147.0, "target": 154.5, "opened_date": "2024-01-08"}},
    }, state_dir=state_dir)
    assert os.path.exists(os.path.join(state_dir, "operational.csv"))
    assert os.path.exists(os.path.join(state_dir, "positions.csv"))
    with open(os.path.join(state_dir, "positions.csv"), newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows == [{"symbol": "AAPL", "entry_price": "150.0", "shares": "10", "stop": "147.0", "target": "154.5", "opened_date": "2024-01-08"}]


def test_save_overwrites_previous_positions_rather_than_appending(tmp_path):
    # positions.csv reflects CURRENT holdings, not history -- a position
    # closed since the last save must disappear from the file, not linger
    # as a stale row alongside the new state.
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": [], "day": "2024-01-08", "starting_equity": 10000.0,
        "open_positions": {"AAPL": {"entry_price": 150.0, "shares": 10, "stop": 147.0, "target": 154.5, "opened_date": "2024-01-08"}},
    }, state_dir=state_dir)
    save_state({
        "day_trade_dates": [], "day": "2024-01-08", "starting_equity": 10000.0,
        "open_positions": {},
    }, state_dir=state_dir)
    state = load_state(state_dir=state_dir)
    assert state["open_positions"] == {}


def test_saved_csvs_use_bare_lf_not_crlf(tmp_path):
    # Regression test for the final whole-branch review's Critical #1.
    # Byte-level check: csv.DictReader (used by load_state and every other
    # test here) transparently absorbs CRLF, hiding the bug from round-trip
    # tests -- only reading the raw bytes catches it.
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": ["2024-01-08"], "day": "2024-01-08", "starting_equity": 9500.0,
        "open_positions": {"AAPL": {"entry_price": 150.0, "shares": 10, "stop": 147.0, "target": 154.5, "opened_date": "2024-01-08"}},
    }, state_dir=state_dir)
    for filename in ("operational.csv", "positions.csv"):
        content = open(os.path.join(state_dir, filename), "rb").read()
        assert b"\r\n" not in content, f"{filename} contains CRLF line endings"


def test_load_tier_pools_returns_zero_defaults_when_no_file_exists(tmp_path):
    tier_pools = load_tier_pools(state_dir=str(tmp_path / "nonexistent"))
    assert tier_pools == {1: 0.0, 2: 0.0, 3: 0.0}


def test_save_then_load_round_trips_tier_pools(tmp_path):
    state_dir = str(tmp_path)
    save_tier_pools({1: 700.0, 2: 200.0, 3: 100.0}, state_dir=state_dir)
    tier_pools = load_tier_pools(state_dir=state_dir)
    assert tier_pools == {1: 700.0, 2: 200.0, 3: 100.0}


def test_load_rebalance_state_returns_none_when_no_file_exists(tmp_path):
    rebalance_state = load_rebalance_state(state_dir=str(tmp_path / "nonexistent"))
    assert rebalance_state == {"last_rebalance_month": None}


def test_save_then_load_round_trips_rebalance_state(tmp_path):
    state_dir = str(tmp_path)
    save_rebalance_state({"last_rebalance_month": "2026-08"}, state_dir=state_dir)
    rebalance_state = load_rebalance_state(state_dir=state_dir)
    assert rebalance_state == {"last_rebalance_month": "2026-08"}


def test_append_decision_log_writes_header_and_row_on_first_call(tmp_path):
    state_dir = str(tmp_path)
    append_decision_log([{
        "timestamp": "2026-01-08T09:35:00-05:00", "symbol": "AAPL", "action": "buy",
        "reason": "all checks passed", "rsi": 45.2, "sma_fast": 101.0, "sma_slow": 99.0,
        "vix": 15.0, "sentiment": 0.1, "days_to_earnings": 12, "macro_breaches": 0, "sector_gates": "[]",
    }], state_dir=state_dir)
    with open(os.path.join(state_dir, "decision_log.csv"), newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["action"] == "buy"
    assert rows[0]["rsi"] == "45.2"


def test_append_decision_log_appends_across_multiple_calls(tmp_path):
    state_dir = str(tmp_path)
    row = {
        "timestamp": "t1", "symbol": "AAPL", "action": "hold", "reason": "no buy signal",
        "rsi": "", "sma_fast": "", "sma_slow": "", "vix": "", "sentiment": "",
        "days_to_earnings": "", "macro_breaches": "", "sector_gates": "",
    }
    append_decision_log([row], state_dir=state_dir)
    append_decision_log([{**row, "timestamp": "t2"}], state_dir=state_dir)
    with open(os.path.join(state_dir, "decision_log.csv"), newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["timestamp"] for r in rows] == ["t1", "t2"]


def test_append_decision_log_writes_multiple_rows_from_one_call(tmp_path):
    state_dir = str(tmp_path)
    row = {
        "timestamp": "t1", "symbol": "AAPL", "action": "hold", "reason": "no buy signal",
        "rsi": "", "sma_fast": "", "sma_slow": "", "vix": "", "sentiment": "",
        "days_to_earnings": "", "macro_breaches": "", "sector_gates": "",
    }
    append_decision_log([row, {**row, "symbol": "SERV"}], state_dir=state_dir)
    with open(os.path.join(state_dir, "decision_log.csv"), newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["symbol"] for r in rows] == ["AAPL", "SERV"]


def test_append_decision_log_is_a_noop_on_empty_rows(tmp_path):
    state_dir = str(tmp_path)
    append_decision_log([], state_dir=state_dir)
    assert not os.path.exists(os.path.join(state_dir, "decision_log.csv"))
