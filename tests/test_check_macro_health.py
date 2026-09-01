import csv
import os

from scripts.check_macro_health import (
    DEFAULT_STREAK_THRESHOLD, read_macro_cycles, unavailable_streak, is_unhealthy,
)

FIELDS = [
    "timestamp", "symbol", "action", "reason", "rsi", "sma_fast", "sma_slow",
    "vix", "sentiment", "days_to_earnings", "macro_breaches", "sector_gates",
]


def _write_log(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        for timestamp, symbol, macro in rows:
            writer.writerow({
                "timestamp": timestamp, "symbol": symbol, "action": "blocked",
                "reason": "macro_gate", "rsi": "50", "sma_fast": "100", "sma_slow": "98",
                "vix": "15", "sentiment": "0.1", "days_to_earnings": "none",
                "macro_breaches": macro, "sector_gates": "",
            })


def test_missing_log_yields_no_cycles(tmp_path):
    assert read_macro_cycles(str(tmp_path / "nope.csv")) == []


def test_cycles_where_the_macro_gate_never_ran_are_ignored(tmp_path):
    path = str(tmp_path / "state" / "decision_log.csv")
    _write_log(path, [("t1", "AAPL", ""), ("t2", "AAPL", "")])
    assert read_macro_cycles(path) == []


def test_one_cycle_per_timestamp_not_per_symbol(tmp_path):
    # Two symbols per cycle must not count as two cycles -- otherwise the streak
    # threshold trips in half the intended wall-clock time.
    path = str(tmp_path / "state" / "decision_log.csv")
    _write_log(path, [
        ("t1", "AAPL", "unavailable"), ("t1", "SERV", "unavailable"),
        ("t2", "AAPL", "unavailable"), ("t2", "SERV", "unavailable"),
    ])
    assert read_macro_cycles(path) == [("t1", True), ("t2", True)]


def test_streak_counts_only_trailing_unavailable_cycles(tmp_path):
    path = str(tmp_path / "state" / "decision_log.csv")
    _write_log(path, [
        ("t1", "AAPL", "unavailable"),
        ("t2", "AAPL", "2"),           # recovered -- resets the streak
        ("t3", "AAPL", "unavailable"),
        ("t4", "AAPL", "unavailable"),
    ])
    assert unavailable_streak(read_macro_cycles(path)) == 2


def test_a_single_recovered_cycle_resets_the_streak(tmp_path):
    path = str(tmp_path / "state" / "decision_log.csv")
    _write_log(path, [("t1", "AAPL", "unavailable")] * 0 + [
        ("t1", "AAPL", "unavailable"), ("t2", "AAPL", "unavailable"), ("t3", "AAPL", "0"),
    ])
    assert unavailable_streak(read_macro_cycles(path)) == 0


def test_zero_breaches_is_not_treated_as_unavailable(tmp_path):
    # "0" means the macro gate ran and found no breaches -- the healthiest
    # possible reading. It must never be confused with "could not answer".
    path = str(tmp_path / "state" / "decision_log.csv")
    _write_log(path, [("t%d" % i, "AAPL", "0") for i in range(20)])
    assert unavailable_streak(read_macro_cycles(path)) == 0
    assert is_unhealthy(read_macro_cycles(path), threshold=3) is False


def test_unhealthy_only_once_the_streak_reaches_the_threshold(tmp_path):
    path = str(tmp_path / "state" / "decision_log.csv")
    _write_log(path, [("t%d" % i, "AAPL", "unavailable") for i in range(3)])
    cycles = read_macro_cycles(path)
    assert is_unhealthy(cycles, threshold=3) is True
    assert is_unhealthy(cycles, threshold=4) is False


def test_a_brief_blip_does_not_alarm_at_the_default_threshold(tmp_path):
    # fetch_bullion_macro_snapshot converts ANY exception into
    # MacroDataUnavailable, so a transient network error produces one
    # unavailable cycle. That must not page anyone.
    path = str(tmp_path / "state" / "decision_log.csv")
    _write_log(path, [("t1", "AAPL", "2"), ("t2", "AAPL", "unavailable")])
    assert is_unhealthy(read_macro_cycles(path), threshold=DEFAULT_STREAK_THRESHOLD) is False
