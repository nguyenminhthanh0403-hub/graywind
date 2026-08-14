import json

from graywind_strategy.state_store import load_state, save_state


def test_load_state_returns_empty_defaults_when_no_file_exists(tmp_path):
    state = load_state(path=str(tmp_path / "nonexistent.json"))
    assert state == {"day_trade_dates": [], "day": None, "starting_equity": None, "open_positions": {}}


def test_save_then_load_round_trips_state(tmp_path):
    path = str(tmp_path / "state.json")
    save_state(
        {"day_trade_dates": ["2024-01-08", "2024-01-09"], "day": "2024-01-09", "starting_equity": 10000.0},
        path=path,
    )
    state = load_state(path=path)
    assert state["day_trade_dates"] == ["2024-01-08", "2024-01-09"]
    assert state["day"] == "2024-01-09"
    assert state["starting_equity"] == 10000.0


def test_load_state_backfills_open_positions_for_old_state_files(tmp_path):
    path = str(tmp_path / "state.json")
    with open(path, "w") as f:
        json.dump({"day_trade_dates": [], "day": None, "starting_equity": None}, f)  # no open_positions key
    state = load_state(path=path)
    assert state["open_positions"] == {}


def test_save_then_load_round_trips_open_positions(tmp_path):
    path = str(tmp_path / "state.json")
    save_state({
        "day_trade_dates": [], "day": "2024-01-08", "starting_equity": 10000.0,
        "open_positions": {"AAPL": {"entry_price": 150.0, "shares": 10, "stop": 147.0, "target": 154.5, "opened_date": "2024-01-08"}},
    }, path=path)
    state = load_state(path=path)
    assert state["open_positions"]["AAPL"]["shares"] == 10
