import csv
import os

from graywind_strategy.dashboard_export import write_cycle_export
from merge_dashboard_export import merge_export


def _read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _make_export(export_dir, timestamp, equity, trades=None, symbols=("AAPL",)):
    write_cycle_export(
        export_dir=export_dir, timestamp=timestamp, symbols=list(symbols),
        equity=equity, today_pnl=equity - 10000.0 if equity else None,
        symbol_statuses={}, cycle_trades=trades or [],
    )


def test_merge_creates_target_files_on_first_run(tmp_path):
    export_dir = str(tmp_path / "export")
    target_dir = str(tmp_path / "target")
    _make_export(export_dir, "2026-08-15T10:00:00-04:00", 10100.0)

    merge_export(export_dir=export_dir, target_data_dir=target_dir)

    equity_rows = _read_csv(os.path.join(target_dir, "equity_curve.csv"))
    assert equity_rows == [{"timestamp": "2026-08-15T10:00:00-04:00", "equity": "10100.0"}]
    status_rows = _read_csv(os.path.join(target_dir, "status.csv"))
    assert len(status_rows) == 1


def test_merge_appends_equity_point_on_second_run_without_losing_first(tmp_path):
    export_dir = str(tmp_path / "export")
    target_dir = str(tmp_path / "target")
    _make_export(export_dir, "2026-08-15T10:00:00-04:00", 10100.0)
    merge_export(export_dir=export_dir, target_data_dir=target_dir)

    _make_export(export_dir, "2026-08-15T10:15:00-04:00", 10150.0)
    merge_export(export_dir=export_dir, target_data_dir=target_dir)

    equity_rows = _read_csv(os.path.join(target_dir, "equity_curve.csv"))
    assert [r["timestamp"] for r in equity_rows] == ["2026-08-15T10:00:00-04:00", "2026-08-15T10:15:00-04:00"]
    assert [r["equity"] for r in equity_rows] == ["10100.0", "10150.0"]


def test_merge_appends_new_trades_across_two_runs(tmp_path):
    export_dir = str(tmp_path / "export")
    target_dir = str(tmp_path / "target")
    trade1 = [{"timestamp": "2026-08-15T10:00:00-04:00", "symbol": "AAPL", "side": "buy", "qty": 10, "price": 150.0, "reason": "signal=buy"}]
    _make_export(export_dir, "2026-08-15T10:00:00-04:00", 10100.0, trades=trade1)
    merge_export(export_dir=export_dir, target_data_dir=target_dir)

    trade2 = [{"timestamp": "2026-08-15T10:15:00-04:00", "symbol": "SPY", "side": "buy", "qty": 5, "price": 410.0, "reason": "signal=buy"}]
    _make_export(export_dir, "2026-08-15T10:15:00-04:00", 10150.0, trades=trade2)
    merge_export(export_dir=export_dir, target_data_dir=target_dir)

    trade_rows = _read_csv(os.path.join(target_dir, "trade_log.csv"))
    assert len(trade_rows) == 2
    assert trade_rows[0]["symbol"] == "AAPL"
    assert trade_rows[1]["symbol"] == "SPY"


def test_merge_does_not_append_when_a_cycle_had_zero_trades(tmp_path):
    export_dir = str(tmp_path / "export")
    target_dir = str(tmp_path / "target")
    _make_export(export_dir, "2026-08-15T10:00:00-04:00", 10100.0, trades=[])
    merge_export(export_dir=export_dir, target_data_dir=target_dir)
    trade_rows = _read_csv(os.path.join(target_dir, "trade_log.csv"))
    assert trade_rows == []


def test_merge_overwrites_status_rather_than_appending(tmp_path):
    export_dir = str(tmp_path / "export")
    target_dir = str(tmp_path / "target")
    _make_export(export_dir, "2026-08-15T10:00:00-04:00", 10100.0, symbols=("AAPL", "SPY"))
    merge_export(export_dir=export_dir, target_data_dir=target_dir)
    _make_export(export_dir, "2026-08-15T10:15:00-04:00", 10150.0, symbols=("AAPL", "SPY"))
    merge_export(export_dir=export_dir, target_data_dir=target_dir)

    status_rows = _read_csv(os.path.join(target_dir, "status.csv"))
    assert len(status_rows) == 2  # not 4 -- overwritten, not appended
    assert all(r["last_cycle_timestamp"] == "2026-08-15T10:15:00-04:00" for r in status_rows)


def test_two_run_round_trip_simulation_preserves_append_vs_overwrite_semantics(tmp_path):
    # The design doc's required "actually execute the workflow logic twice"
    # test: exercises the exact append (equity/trades) vs overwrite (status)
    # split end to end, the same way the real cron will run it twice in a row.
    export_dir = str(tmp_path / "export")
    target_dir = str(tmp_path / "target")

    _make_export(export_dir, "2026-08-15T10:00:00-04:00", 10000.0,
                  trades=[{"timestamp": "2026-08-15T10:00:00-04:00", "symbol": "AAPL", "side": "buy", "qty": 10, "price": 150.0, "reason": "signal=buy"}])
    merge_export(export_dir=export_dir, target_data_dir=target_dir)

    _make_export(export_dir, "2026-08-15T10:15:00-04:00", 10050.0, trades=[])
    merge_export(export_dir=export_dir, target_data_dir=target_dir)

    assert len(_read_csv(os.path.join(target_dir, "equity_curve.csv"))) == 2
    assert len(_read_csv(os.path.join(target_dir, "trade_log.csv"))) == 1
    assert len(_read_csv(os.path.join(target_dir, "status.csv"))) == 1


def test_merged_csvs_use_bare_lf_not_crlf(tmp_path):
    # Regression test for the final whole-branch review's Critical #1.
    # merge_export appends into an existing target file (or writes a fresh
    # header-only file on a zero-row cycle) and status.csv is copied
    # wholesale via shutil.copyfile -- all three paths must stay CRLF-free
    # so index.html's naive "\n"-split parser never sees a trailing "\r".
    # Byte-level check: csv.DictReader on the read side would silently
    # absorb CRLF and hide this bug, as it did across 136 passing tests.
    export_dir = str(tmp_path / "export")
    target_dir = str(tmp_path / "target")
    _make_export(export_dir, "2026-08-15T10:00:00-04:00", 10100.0,
                  trades=[{"timestamp": "2026-08-15T10:00:00-04:00", "symbol": "AAPL", "side": "buy", "qty": 10, "price": 150.0, "reason": "signal=buy"}])
    merge_export(export_dir=export_dir, target_data_dir=target_dir)
    # Zero-trade second cycle exercises the header-only "ensure file exists" path too.
    _make_export(export_dir, "2026-08-15T10:15:00-04:00", 10150.0, trades=[])
    merge_export(export_dir=export_dir, target_data_dir=target_dir)

    for filename in ("equity_curve.csv", "trade_log.csv", "status.csv"):
        content = open(os.path.join(target_dir, filename), "rb").read()
        assert b"\r\n" not in content, f"{filename} contains CRLF line endings"
