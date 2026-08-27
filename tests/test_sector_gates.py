# tests/test_sector_gates.py
from datetime import date

from graywind_strategy.gates.sector_gates import (
    SECTOR_GATES,
    energy_stub_gate,
    evaluate_sector_gates,
)


def test_evaluate_sector_gates_passes_untagged_symbol():
    # SPY has no entry in SYMBOL_SECTOR
    result = evaluate_sector_gates(symbol="SPY", as_of_date=date(2024, 1, 8))
    assert result.passed is True
    assert result.value == []


def test_evaluate_sector_gates_passes_tagged_symbol_with_no_registered_gate():
    # AAPL is tagged "tech" in SYMBOL_SECTOR, but SECTOR_GATES has no "tech" entry
    result = evaluate_sector_gates(symbol="AAPL", as_of_date=date(2024, 1, 8))
    assert result.passed is True
    assert result.value == []


def test_evaluate_sector_gates_passes_with_registered_stub():
    # XOM is tagged "energy", which is registered with energy_stub_gate
    result = evaluate_sector_gates(symbol="XOM", as_of_date=date(2024, 1, 8))
    assert result.passed is True
    assert result.value == [("energy_stub_gate", True)]


def test_energy_stub_gate_always_true():
    assert energy_stub_gate(symbol="XOM", as_of_date=date(2024, 1, 8)) is True


def test_evaluate_sector_gates_blocks_when_a_registered_gate_returns_false(monkeypatch):
    failing_gate = lambda symbol, as_of_date: False
    monkeypatch.setitem(SECTOR_GATES, "energy", [failing_gate])
    result = evaluate_sector_gates(symbol="XOM", as_of_date=date(2024, 1, 8))
    assert result.passed is False
    assert result.value == [("<lambda>", False)]


def test_evaluate_sector_gates_requires_all_gates_in_list_to_pass(monkeypatch):
    passing_gate = lambda symbol, as_of_date: True
    failing_gate = lambda symbol, as_of_date: False
    monkeypatch.setitem(SECTOR_GATES, "energy", [passing_gate, failing_gate])
    result = evaluate_sector_gates(symbol="XOM", as_of_date=date(2024, 1, 8))
    assert result.passed is False
    assert result.value == [("<lambda>", True), ("<lambda>", False)]


def test_evaluate_sector_gates_short_circuits_after_first_failure(monkeypatch):
    from unittest.mock import MagicMock

    failing_gate = lambda symbol, as_of_date: False
    never_called_gate = MagicMock()
    monkeypatch.setitem(SECTOR_GATES, "energy", [failing_gate, never_called_gate])
    result = evaluate_sector_gates(symbol="XOM", as_of_date=date(2024, 1, 8))
    assert result.passed is False
    # Only the failing gate made it into value -- never_called_gate never ran,
    # so it's honestly absent from the reading, not silently invented.
    assert result.value == [("<lambda>", False)]
    never_called_gate.assert_not_called()
