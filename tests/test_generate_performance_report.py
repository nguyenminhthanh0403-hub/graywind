import csv
import json
import os

from scripts.generate_performance_report import (
    ACCOUNTS,
    NO_DECISION_LOG_MATCH,
    SELL_EXIT_NARRATIVE,
    build_account_report,
    generate_report,
    load_account_data,
    per_symbol_pnl,
    build_block_frequency_notes,
    build_trade_narratives,
)
from graywind_strategy.backtester import sharpe_ratio


def _write_csv(path, fieldnames, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


TRADE_FIELDS = ["timestamp", "symbol", "side", "qty", "price", "reason"]
EQUITY_FIELDS = ["timestamp", "equity"]
DECISION_FIELDS = [
    "timestamp", "symbol", "action", "reason", "rsi", "sma_fast", "sma_slow",
    "vix", "sentiment", "days_to_earnings", "macro_breaches", "sector_gates",
]


def test_load_account_data_returns_none_when_dashboard_files_missing(tmp_path):
    result = load_account_data(
        state_dir=str(tmp_path / "state" / "small"),
        dashboard_dir=str(tmp_path / "dashboard-data" / "small"),
    )
    assert result is None


def test_load_account_data_falls_back_gracefully_when_decision_log_missing(tmp_path):
    dashboard_dir = str(tmp_path / "dashboard-data")
    _write_csv(os.path.join(dashboard_dir, "trade_log.csv"), TRADE_FIELDS, [
        {"timestamp": "2026-08-01T10:00:00-04:00", "symbol": "AAPL", "side": "buy", "qty": 10, "price": 100.0, "reason": "all checks passed"},
        {"timestamp": "2026-08-02T10:00:00-04:00", "symbol": "AAPL", "side": "sell", "qty": 10, "price": 105.0, "reason": "stop/target exit"},
    ])
    _write_csv(os.path.join(dashboard_dir, "equity_curve.csv"), EQUITY_FIELDS, [
        {"timestamp": "2026-08-01T09:35:00-04:00", "equity": 10000.0},
        {"timestamp": "2026-08-02T09:35:00-04:00", "equity": 10050.0},
    ])
    result = load_account_data(state_dir=str(tmp_path / "state"), dashboard_dir=dashboard_dir)
    assert result is not None
    assert result["decision_rows"] == []
    assert len(result["trades"]) == 2


def test_build_account_report_computes_metrics_and_narrative(tmp_path):
    dashboard_dir = str(tmp_path / "dashboard-data")
    state_dir = str(tmp_path / "state")
    _write_csv(os.path.join(dashboard_dir, "trade_log.csv"), TRADE_FIELDS, [
        {"timestamp": "2026-08-01T10:00:00-04:00", "symbol": "AAPL", "side": "buy", "qty": 10, "price": 100.0, "reason": "all checks passed"},
        {"timestamp": "2026-08-02T10:00:00-04:00", "symbol": "AAPL", "side": "sell", "qty": 10, "price": 105.0, "reason": "stop/target exit"},
    ])
    _write_csv(os.path.join(dashboard_dir, "equity_curve.csv"), EQUITY_FIELDS, [
        {"timestamp": "2026-08-01T09:35:00-04:00", "equity": 10000.0},
        {"timestamp": "2026-08-01T09:50:00-04:00", "equity": 9800.0},  # a blocked-cycle dip in between
        {"timestamp": "2026-08-02T10:00:00-04:00", "equity": 10050.0},
    ])
    # decision_log.csv lives under state_dir, not dashboard_dir (matches
    # GRAYWIND_STATE_DIR's real layout -- see Task 5/6).
    _write_csv(os.path.join(state_dir, "decision_log.csv"), DECISION_FIELDS, [
        {"timestamp": "2026-08-01T10:00:00-04:00", "symbol": "AAPL", "action": "buy", "reason": "all checks passed",
         "rsi": 45.2, "sma_fast": 101.0, "sma_slow": 99.0, "vix": 15.0, "sentiment": 0.1,
         "days_to_earnings": 12, "macro_breaches": 0, "sector_gates": "[]"},
        {"timestamp": "2026-08-01T09:50:00-04:00", "symbol": "AAPL", "action": "blocked", "reason": "vix_gate",
         "rsi": "", "sma_fast": "", "sma_slow": "", "vix": 30.0, "sentiment": "", "days_to_earnings": "",
         "macro_breaches": "", "sector_gates": ""},
    ])
    data = load_account_data(state_dir=state_dir, dashboard_dir=dashboard_dir)
    report = build_account_report(data)

    assert report["trade_count"] == 2
    assert report["total_pnl"] == 10050.0 - 10000.0
    assert report["win_rate"] == 1.0  # the one round trip (buy 100 -> sell 105) was profitable
    assert report["per_symbol"]["AAPL"]["trades"] == 1  # one round trip
    assert report["per_symbol"]["AAPL"]["pnl"] == (105.0 - 100.0) * 10
    assert len(report["trade_narratives"]) == 2
    buy_narrative = next(n for n in report["trade_narratives"] if n["side"] == "buy")
    assert buy_narrative["rsi"] == "45.2"
    assert buy_narrative["sma_fast"] == "101.0"
    assert buy_narrative["sma_slow"] == "99.0"
    assert "vix=15.0" in buy_narrative["gate_summary"]
    assert any("vix_gate" in note for note in report["block_frequency_notes"])
    # The sell leg has no real decision-log counterpart (decision_log.csv
    # never logs exits) -- it must get the honest exit-specific narrative,
    # not be matched against the buy-evaluation row above.
    sell_narrative = next(n for n in report["trade_narratives"] if n["side"] == "sell")
    assert sell_narrative["gate_summary"] == SELL_EXIT_NARRATIVE
    assert sell_narrative["rsi"] is None
    assert sell_narrative["sma_fast"] is None
    assert sell_narrative["sma_slow"] is None
    # Sharpe is reported unannualized (periods_per_year=1), not inflated by
    # the backtester's 15-minute-bar constant -- see I2.
    assert report["sharpe"] == sharpe_ratio(
        [10000.0, 9800.0, 10050.0], periods_per_year=1
    )


def test_per_symbol_pnl_pairs_buy_and_sell_round_trips():
    trades = [
        {"timestamp": "t1", "symbol": "AAPL", "side": "buy", "qty": 10, "price": 100.0, "reason": ""},
        {"timestamp": "t2", "symbol": "AAPL", "side": "sell", "qty": 10, "price": 90.0, "reason": ""},
    ]
    breakdown = per_symbol_pnl(trades)
    assert breakdown == {"AAPL": {"trades": 1, "pnl": -100.0}}


def test_build_block_frequency_notes_summarizes_by_reason():
    decision_rows = [
        {"action": "blocked", "reason": "vix_gate"},
        {"action": "blocked", "reason": "vix_gate"},
        {"action": "buy", "reason": "all checks passed"},
    ]
    notes = build_block_frequency_notes(decision_rows)
    assert len(notes) == 1
    assert "vix_gate" in notes[0]
    assert "67%" in notes[0]


def test_build_trade_narratives_falls_back_when_no_decision_log_match():
    trades = [{"timestamp": "t1", "symbol": "AAPL", "side": "buy", "qty": 10, "price": 100.0, "reason": "all checks passed"}]
    narratives = build_trade_narratives(trades, decision_rows=[])
    assert narratives[0]["gate_summary"] == NO_DECISION_LOG_MATCH
    assert narratives[0]["rsi"] is None
    assert narratives[0]["sma_fast"] is None
    assert narratives[0]["sma_slow"] is None


def test_build_trade_narratives_falls_back_when_nearest_match_is_days_away():
    # C1: an unbounded nearest-neighbor match could pair a trade with a
    # decision_log row from days away -- e.g. a much earlier (possibly
    # blocked) cycle's evaluation -- and present it as this trade's "why".
    # A row outside the same-day tolerance must be treated as no match at
    # all, falling back to the honest generic message instead of the
    # distant row's fabricated-looking detail.
    trades = [{
        "timestamp": "2026-08-10T10:00:00-04:00", "symbol": "AAPL", "side": "buy",
        "qty": 10, "price": 100.0, "reason": "all checks passed",
    }]
    decision_rows = [{
        "timestamp": "2026-08-01T10:00:00-04:00", "symbol": "AAPL", "action": "blocked",
        "reason": "vix_gate", "rsi": "99.9", "sma_fast": "1.0", "sma_slow": "2.0",
        "vix": "40.0", "sentiment": "-0.9", "days_to_earnings": "1",
        "macro_breaches": "3", "sector_gates": "['blocked']",
    }]
    narratives = build_trade_narratives(trades, decision_rows)
    assert narratives[0]["gate_summary"] == NO_DECISION_LOG_MATCH
    assert narratives[0]["rsi"] is None
    assert narratives[0]["sma_fast"] is None
    assert narratives[0]["sma_slow"] is None
    assert "99.9" not in str(narratives[0])
    assert "40.0" not in str(narratives[0])


def test_build_trade_narratives_gives_sells_exit_specific_treatment():
    # decision_log.csv structurally never has rows for sells (only the
    # buy-evaluation path logs). A sell must never be matched against a
    # nearby buy-evaluation row, even one from the very same timestamp.
    trades = [{
        "timestamp": "2026-08-10T10:00:00-04:00", "symbol": "AAPL", "side": "sell",
        "qty": 10, "price": 105.0, "reason": "stop/target exit",
    }]
    decision_rows = [{
        "timestamp": "2026-08-10T10:00:00-04:00", "symbol": "AAPL", "action": "buy",
        "reason": "all checks passed", "rsi": "45.2", "sma_fast": "101.0", "sma_slow": "99.0",
        "vix": "15.0", "sentiment": "0.1", "days_to_earnings": "12",
        "macro_breaches": "0", "sector_gates": "[]",
    }]
    narratives = build_trade_narratives(trades, decision_rows)
    assert narratives[0]["gate_summary"] == SELL_EXIT_NARRATIVE
    assert narratives[0]["rsi"] is None
    assert narratives[0]["sma_fast"] is None
    assert narratives[0]["sma_slow"] is None


def test_build_trade_narratives_includes_sma_fast_and_slow_on_a_real_match():
    trades = [{
        "timestamp": "2026-08-10T10:00:00-04:00", "symbol": "AAPL", "side": "buy",
        "qty": 10, "price": 100.0, "reason": "all checks passed",
    }]
    decision_rows = [{
        "timestamp": "2026-08-10T10:00:05-04:00", "symbol": "AAPL", "action": "buy",
        "reason": "all checks passed", "rsi": "45.2", "sma_fast": "101.0", "sma_slow": "99.0",
        "vix": "15.0", "sentiment": "0.1", "days_to_earnings": "12",
        "macro_breaches": "0", "sector_gates": "[]",
    }]
    narratives = build_trade_narratives(trades, decision_rows)
    assert narratives[0]["sma_fast"] == "101.0"
    assert narratives[0]["sma_slow"] == "99.0"


def test_generate_report_skips_account_with_no_dashboard_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dashboard_dir = str(tmp_path / "dashboard-data")
    _write_csv(os.path.join(dashboard_dir, "trade_log.csv"), TRADE_FIELDS, [])
    _write_csv(os.path.join(dashboard_dir, "equity_curve.csv"), EQUITY_FIELDS, [])
    import scripts.generate_performance_report as gpr
    monkeypatch.setattr(gpr, "ACCOUNTS", [
        {"label": "100k", "state_dir": "state", "dashboard_dir": "dashboard-data"},
        {"label": "small", "state_dir": "state/small", "dashboard_dir": "dashboard-data/small"},
    ])
    report = generate_report()
    assert "100k" in report["accounts"]
    assert "small" not in report["accounts"]
    assert os.path.exists(os.path.join(dashboard_dir, "performance_report.json"))
