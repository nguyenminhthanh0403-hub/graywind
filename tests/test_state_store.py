import csv
import os

from graywind_strategy.state_store import load_state, save_state


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
