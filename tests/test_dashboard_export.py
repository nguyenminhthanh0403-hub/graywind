import csv
import os

from graywind_strategy.dashboard_export import write_cycle_export


def _read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_writes_new_equity_point_with_timestamp_and_equity(tmp_path):
    export_dir = str(tmp_path)
    write_cycle_export(
        export_dir=export_dir, timestamp="2026-08-15T10:00:00-04:00", symbols=["AAPL"],
        equity=10500.0, today_pnl=500.0, symbol_statuses={}, cycle_trades=[],
    )
    rows = _read_csv(os.path.join(export_dir, "new_equity_point.csv"))
    assert rows == [{"timestamp": "2026-08-15T10:00:00-04:00", "equity": "10500.0"}]


def test_writes_blank_equity_when_cycle_had_no_confirmed_equity_reading(tmp_path):
    # main()'s get_account() failure path -- equity/today_pnl are None, but
    # the file must still exist with a row (a failed cycle is still a
    # recorded event, not a silent gap in the dashboard).
    export_dir = str(tmp_path)
    write_cycle_export(
        export_dir=export_dir, timestamp="2026-08-15T10:00:00-04:00", symbols=["AAPL"],
        equity=None, today_pnl=None, symbol_statuses={}, cycle_trades=[],
    )
    rows = _read_csv(os.path.join(export_dir, "new_equity_point.csv"))
    assert rows == [{"timestamp": "2026-08-15T10:00:00-04:00", "equity": ""}]


def test_writes_one_trade_row_per_cycle_trade(tmp_path):
    export_dir = str(tmp_path)
    trades = [
        {"timestamp": "2026-08-15T10:00:00-04:00", "symbol": "AAPL", "side": "buy", "qty": 10, "price": 150.0, "reason": "signal=buy"},
        {"timestamp": "2026-08-15T10:00:00-04:00", "symbol": "SPY", "side": "sell", "qty": 5, "price": 410.0, "reason": "stop/target exit"},
    ]
    write_cycle_export(
        export_dir=export_dir, timestamp="2026-08-15T10:00:00-04:00", symbols=["AAPL", "SPY"],
        equity=10500.0, today_pnl=500.0, symbol_statuses={}, cycle_trades=trades,
    )
    rows = _read_csv(os.path.join(export_dir, "new_trades.csv"))
    assert len(rows) == 2
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["side"] == "buy"
    assert rows[1]["symbol"] == "SPY"
    assert rows[1]["side"] == "sell"


def test_writes_empty_trades_file_with_header_when_no_trades_this_cycle(tmp_path):
    export_dir = str(tmp_path)
    write_cycle_export(
        export_dir=export_dir, timestamp="2026-08-15T10:00:00-04:00", symbols=["AAPL"],
        equity=10500.0, today_pnl=500.0, symbol_statuses={}, cycle_trades=[],
    )
    rows = _read_csv(os.path.join(export_dir, "new_trades.csv"))
    assert rows == []


def test_status_has_one_row_per_requested_symbol(tmp_path):
    export_dir = str(tmp_path)
    statuses = {
        "AAPL": {"position_open": True, "shares": 10, "entry_price": 150.0, "current_price": 152.0, "action": "hold", "reason": "already holding 10 shares"},
    }
    write_cycle_export(
        export_dir=export_dir, timestamp="2026-08-15T10:00:00-04:00", symbols=["AAPL", "SPY"],
        equity=10500.0, today_pnl=500.0, symbol_statuses=statuses, cycle_trades=[],
    )
    rows = _read_csv(os.path.join(export_dir, "status.csv"))
    assert len(rows) == 2
    by_symbol = {r["symbol"]: r for r in rows}
    assert by_symbol["AAPL"]["action"] == "hold"
    assert by_symbol["AAPL"]["shares"] == "10"


def test_status_defaults_unevaluated_symbol_to_unknown_action(tmp_path):
    # A cycle that failed before the per-symbol loop ran (e.g. get_account()
    # raised) leaves symbol_statuses empty -- every watchlist symbol must
    # still get a row, not silently vanish from the dashboard for that cycle.
    export_dir = str(tmp_path)
    write_cycle_export(
        export_dir=export_dir, timestamp="2026-08-15T10:00:00-04:00", symbols=["AAPL", "SPY"],
        equity=None, today_pnl=None, symbol_statuses={}, cycle_trades=[],
    )
    rows = _read_csv(os.path.join(export_dir, "status.csv"))
    assert len(rows) == 2
    assert all(r["action"] == "unknown" for r in rows)
    assert all(r["reason"] == "cycle did not evaluate this symbol" for r in rows)


def test_status_rows_carry_account_level_fields(tmp_path):
    export_dir = str(tmp_path)
    write_cycle_export(
        export_dir=export_dir, timestamp="2026-08-15T10:00:00-04:00", symbols=["AAPL"],
        equity=10500.0, today_pnl=500.0, symbol_statuses={}, cycle_trades=[],
    )
    rows = _read_csv(os.path.join(export_dir, "status.csv"))
    assert rows[0]["last_cycle_timestamp"] == "2026-08-15T10:00:00-04:00"
    assert rows[0]["account_equity"] == "10500.0"
    assert rows[0]["today_pnl"] == "500.0"


def test_export_dir_is_created_if_missing(tmp_path):
    export_dir = str(tmp_path / "nested" / "export")
    write_cycle_export(
        export_dir=export_dir, timestamp="2026-08-15T10:00:00-04:00", symbols=["AAPL"],
        equity=10500.0, today_pnl=500.0, symbol_statuses={}, cycle_trades=[],
    )
    assert os.path.exists(os.path.join(export_dir, "status.csv"))


def test_written_csvs_use_bare_lf_not_crlf(tmp_path):
    # Regression test for the final whole-branch review's Critical #1:
    # csv.DictWriter's default "excel" dialect writes "\r\n" line endings.
    # index.html's parseCSV splits on "\n" only, so a CRLF-terminated last
    # header/field silently retains a trailing "\r" (e.g. "reason\r"),
    # breaking row.reason lookups and poisoning parseFloat on numeric
    # fields. This must be checked at the byte level -- csv.DictReader
    # transparently absorbs CRLF on read, so a round-trip test through
    # DictReader (as every other test in this file does) cannot catch it.
    export_dir = str(tmp_path)
    write_cycle_export(
        export_dir=export_dir, timestamp="2026-08-15T10:00:00-04:00", symbols=["AAPL"],
        equity=10500.0, today_pnl=500.0, symbol_statuses={}, cycle_trades=[],
    )
    for filename in ("new_equity_point.csv", "new_trades.csv", "status.csv"):
        content = open(os.path.join(export_dir, filename), "rb").read()
        assert b"\r\n" not in content, f"{filename} contains CRLF line endings"
