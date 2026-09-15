import csv
import os

from datetime import date

import pytest

from graywind_strategy.state_store import (
    load_state, save_state, load_tier_pools, save_tier_pools,
    load_rebalance_state, save_rebalance_state, append_decision_log,
    load_equity_history, save_equity_history, load_pending_trades, save_pending_trades,
    load_tier1_holdings, save_tier1_holdings,
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


def test_save_then_load_round_trips_a_pending_sell_order_id(tmp_path):
    # A position with a sell submitted but not yet confirmed settled
    # persists its order id across cycles (live_loop.py is a fresh process
    # each run) so a later cycle can resolve it via get_order_by_id.
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": [], "day": "2024-01-08", "starting_equity": 10000.0,
        "open_positions": {
            "AAPL": {
                "entry_price": 150.0, "shares": 10, "stop": 147.0, "target": 154.5,
                "opened_date": "2024-01-08", "pending_sell_order_id": "order-123",
            },
        },
    }, state_dir=state_dir)
    state = load_state(state_dir=state_dir)
    assert state["open_positions"]["AAPL"]["pending_sell_order_id"] == "order-123"


def test_load_state_omits_pending_sell_order_id_when_never_set(tmp_path):
    # An ordinary position (the overwhelming common case) must round-trip to
    # EXACTLY its original shape -- no stray key with an empty-string or
    # None value -- so every pre-existing caller/test that doesn't know
    # about pending sells is unaffected.
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": [], "day": "2024-01-08", "starting_equity": 10000.0,
        "open_positions": {"AAPL": {"entry_price": 150.0, "shares": 10, "stop": 147.0, "target": 154.5, "opened_date": "2024-01-08"}},
    }, state_dir=state_dir)
    state = load_state(state_dir=state_dir)
    assert "pending_sell_order_id" not in state["open_positions"]["AAPL"]


def test_save_then_load_round_trips_a_pending_sell_order_covers(tmp_path):
    # A single-leg stop/target order (execute_manual_trade.py's
    # handle_set_stop_target) records which leg it covers so live_loop.py
    # can keep watching the other one across cycles -- this must survive
    # the fresh-process reload the same way pending_sell_order_id does.
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": [], "day": "2024-01-08", "starting_equity": 10000.0,
        "open_positions": {
            "AAPL": {
                "entry_price": 150.0, "shares": 10, "stop": 147.0, "target": 154.5,
                "opened_date": "2024-01-08", "pending_sell_order_id": "order-123",
                "pending_sell_order_covers": "stop",
            },
        },
    }, state_dir=state_dir)
    state = load_state(state_dir=state_dir)
    assert state["open_positions"]["AAPL"]["pending_sell_order_covers"] == "stop"


def test_load_state_omits_pending_sell_order_covers_when_never_set(tmp_path):
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": [], "day": "2024-01-08", "starting_equity": 10000.0,
        "open_positions": {"AAPL": {"entry_price": 150.0, "shares": 10, "stop": 147.0, "target": 154.5, "opened_date": "2024-01-08"}},
    }, state_dir=state_dir)
    state = load_state(state_dir=state_dir)
    assert "pending_sell_order_covers" not in state["open_positions"]["AAPL"]


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
    assert rows == [{
        "symbol": "AAPL", "entry_price": "150.0", "shares": "10", "stop": "147.0",
        "target": "154.5", "opened_date": "2024-01-08", "pending_sell_order_id": "",
        "pending_sell_order_covers": "",
    }]


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


def test_save_state_writes_atomically_leaving_no_stray_temp_files(tmp_path):
    # save_state used to write operational.csv/positions.csv directly with
    # plain open(path, "w"), so a process killed mid-write (cron timeout,
    # OOM, SIGTERM) could leave a truncated file in place. Writing via a
    # temp file + os.replace means the write either lands completely or not
    # at all -- this checks the temp file doesn't leak on a normal save.
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": [], "day": "2024-01-08", "starting_equity": 9500.0,
        "open_positions": {"AAPL": {"entry_price": 150.0, "shares": 10, "stop": 147.0, "target": 154.5, "opened_date": "2024-01-08"}},
    }, state_dir=state_dir)
    assert sorted(os.listdir(state_dir)) == ["operational.csv", "positions.csv"]


def test_save_pending_trades_preserves_prior_file_when_write_fails_partway(tmp_path, monkeypatch):
    # The real point of atomic writes: if the process dies partway through
    # writing the new content, the OLD file must survive untouched rather
    # than being left truncated -- the failure mode load_pending_trades'
    # malformed-file handling above exists to cover, but is better avoided
    # entirely here.
    state_dir = str(tmp_path)
    save_pending_trades({
        "AAPL": {
            "issue_number": 1, "side": "buy", "qty": 1.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2026-08-25",
        },
    }, state_dir=state_dir)
    original_content = open(os.path.join(state_dir, "pending_trades.csv"), "rb").read()

    import csv as csv_module
    real_writeheader = csv_module.DictWriter.writeheader

    def failing_writeheader(self):
        raise RuntimeError("simulated crash mid-write")

    monkeypatch.setattr(csv_module.DictWriter, "writeheader", failing_writeheader)
    try:
        with pytest.raises(RuntimeError):
            save_pending_trades({}, state_dir=state_dir)
    finally:
        monkeypatch.setattr(csv_module.DictWriter, "writeheader", real_writeheader)

    assert open(os.path.join(state_dir, "pending_trades.csv"), "rb").read() == original_content
    assert sorted(os.listdir(state_dir)) == ["pending_trades.csv"]  # no stray .tmp file left behind


def test_load_state_degrades_open_positions_to_empty_on_a_truncated_positions_file(tmp_path, capsys):
    # A cron cancelled mid-write leaves a partial final line -- unlike
    # load_equity_history, this loader used to have no protection against
    # that and would crash every subsequent cycle. reconcile_positions()
    # (live_loop.py) already treats a broker position missing from local
    # state as "unmanaged, warn loudly" rather than fabricating one, so
    # degrading to {} here is safe and consistent with that existing design.
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": [], "day": "2024-01-08", "starting_equity": 9500.0,
        "open_positions": {"AAPL": {"entry_price": 150.0, "shares": 10, "stop": 147.0, "target": 154.5, "opened_date": "2024-01-08"}},
    }, state_dir=state_dir)
    with open(os.path.join(state_dir, "positions.csv"), "a") as f:
        f.write("SERV,100.0,5")  # truncated row: missing stop/target/opened_date
    state = load_state(state_dir=state_dir)
    assert state["open_positions"] == {}
    assert "unreadable" in capsys.readouterr().err


def test_load_tier_pools_degrades_to_zero_defaults_on_a_malformed_file(tmp_path, capsys):
    state_dir = str(tmp_path)
    save_tier_pools({1: 700.0, 2: 200.0, 3: 100.0}, state_dir=state_dir)
    with open(os.path.join(state_dir, "tier_pools.csv"), "a") as f:
        f.write("4,not-a-num")
    assert load_tier_pools(state_dir=state_dir) == {1: 0.0, 2: 0.0, 3: 0.0}
    assert "unreadable" in capsys.readouterr().err


def test_load_tier_pools_returns_zero_defaults_when_no_file_exists(tmp_path):
    tier_pools = load_tier_pools(state_dir=str(tmp_path / "nonexistent"))
    assert tier_pools == {1: 0.0, 2: 0.0, 3: 0.0}


def test_save_then_load_round_trips_tier_pools(tmp_path):
    state_dir = str(tmp_path)
    save_tier_pools({1: 700.0, 2: 200.0, 3: 100.0}, state_dir=state_dir)
    tier_pools = load_tier_pools(state_dir=state_dir)
    assert tier_pools == {1: 700.0, 2: 200.0, 3: 100.0}


def test_save_tier_pools_writes_atomically_leaving_no_stray_temp_files(tmp_path):
    state_dir = str(tmp_path)
    save_tier_pools({1: 700.0, 2: 200.0, 3: 100.0}, state_dir=state_dir)
    assert os.listdir(state_dir) == ["tier_pools.csv"]


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


def test_load_pending_trades_returns_empty_dict_when_no_file_exists(tmp_path):
    assert load_pending_trades(state_dir=str(tmp_path / "nonexistent")) == {}


def test_save_then_load_round_trips_pending_trades(tmp_path):
    state_dir = str(tmp_path)
    pending_trades = {
        "AAPL": {
            "issue_number": 42, "side": "buy", "qty": 3.0, "price_at_proposal": 190.5,
            "stop_price": 185.0, "target_price": 200.0, "tier": 2, "proposed_date": "2026-08-26",
        },
        "SPY": {
            "issue_number": 43, "side": "buy", "qty": 1.0, "price_at_proposal": 550.0,
            "stop_price": None, "target_price": None, "tier": 1, "proposed_date": "2026-08-26",
        },
    }
    save_pending_trades(pending_trades, state_dir=state_dir)
    loaded = load_pending_trades(state_dir=state_dir)
    assert loaded == pending_trades


def test_save_pending_trades_creates_state_dir_if_missing(tmp_path):
    state_dir = str(tmp_path / "new_dir")
    save_pending_trades({}, state_dir=state_dir)
    assert os.path.exists(os.path.join(state_dir, "pending_trades.csv"))


def test_save_pending_trades_overwrites_previous_contents(tmp_path):
    state_dir = str(tmp_path)
    save_pending_trades({
        "AAPL": {
            "issue_number": 1, "side": "buy", "qty": 1.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2026-08-25",
        },
    }, state_dir=state_dir)
    save_pending_trades({}, state_dir=state_dir)
    assert load_pending_trades(state_dir=state_dir) == {}


def test_load_pending_trades_degrades_to_empty_on_a_malformed_file(tmp_path, capsys):
    state_dir = str(tmp_path)
    save_pending_trades({
        "AAPL": {
            "issue_number": 42, "side": "buy", "qty": 3.0, "price_at_proposal": 190.5,
            "stop_price": 185.0, "target_price": 200.0, "tier": 2, "proposed_date": "2026-08-26",
        },
    }, state_dir=state_dir)
    with open(os.path.join(state_dir, "pending_trades.csv"), "a") as f:
        f.write("SPY,43,buy,1.0")  # truncated row: missing several trailing fields
    assert load_pending_trades(state_dir=state_dir) == {}
    assert "unreadable" in capsys.readouterr().err


def test_load_tier1_holdings_returns_empty_dict_when_no_file_exists(tmp_path):
    assert load_tier1_holdings(state_dir=str(tmp_path / "nonexistent")) == {}


def test_load_tier1_holdings_degrades_to_empty_on_a_malformed_file(tmp_path, capsys):
    state_dir = str(tmp_path)
    save_tier1_holdings({"SPY": 5.0}, state_dir=state_dir)
    with open(os.path.join(state_dir, "tier1_holdings.csv"), "a") as f:
        f.write("VTI,not-a-num")
    assert load_tier1_holdings(state_dir=state_dir) == {}
    assert "unreadable" in capsys.readouterr().err


def test_save_then_load_round_trips_tier1_holdings(tmp_path):
    state_dir = str(tmp_path)
    holdings = {"SPY": 5.0, "VTI": 2.5}
    save_tier1_holdings(holdings, state_dir=state_dir)
    assert load_tier1_holdings(state_dir=state_dir) == holdings


def test_save_tier1_holdings_writes_atomically_leaving_no_stray_temp_files(tmp_path):
    state_dir = str(tmp_path)
    save_tier1_holdings({"SPY": 5.0}, state_dir=state_dir)
    assert os.listdir(state_dir) == ["tier1_holdings.csv"]


def test_save_pending_trades_writes_atomically_leaving_no_stray_temp_files(tmp_path):
    state_dir = str(tmp_path)
    save_pending_trades({
        "AAPL": {
            "issue_number": 1, "side": "buy", "qty": 1.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2026-08-25",
        },
    }, state_dir=state_dir)
    assert os.listdir(state_dir) == ["pending_trades.csv"]


def test_save_tier1_holdings_creates_state_dir_if_missing(tmp_path):
    state_dir = str(tmp_path / "new_dir")
    save_tier1_holdings({}, state_dir=state_dir)
    assert os.path.exists(os.path.join(state_dir, "tier1_holdings.csv"))


def test_save_tier1_holdings_overwrites_previous_contents(tmp_path):
    state_dir = str(tmp_path)
    save_tier1_holdings({"SPY": 5.0}, state_dir=state_dir)
    save_tier1_holdings({}, state_dir=state_dir)
    assert load_tier1_holdings(state_dir=state_dir) == {}
