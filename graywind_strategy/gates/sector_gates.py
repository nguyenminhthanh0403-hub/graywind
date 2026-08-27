"""Per-sector gate registry: lets a future gate (e.g. an energy oil-price
gate, a tech earnings-surprise gate) apply only to symbols in its sector,
without decide_trade knowing about individual sectors.

Registry contract: every function registered in a SECTOR_GATES list must be
a self-contained evaluator -- same shape as evaluate_vix_gate/
evaluate_macro_gate in pipeline.py. It performs its own I/O and catches its
own XDataUnavailable exception internally, returning a plain bool.
evaluate_sector_gates never sees a raw pure-logic function or an unhandled
exception. evaluate_sector_gates calls each registered gate as
`gate(symbol=symbol, as_of_date=as_of_date)` -- by keyword, not
positionally -- so a registered gate must accept `symbol` and `as_of_date`
as keyword arguments with those exact parameter names, not merely two
positional parameters in that order.

No tag, no registered gate for a symbol's sector, or an empty list are all
treated as "pass" -- a sector caveat is additive risk management, not a
required check (same precedent as earnings_gate: no earnings scheduled ->
allow, not block).

evaluate_sector_gates itself returns a GateResult (see
graywind_strategy.gate_result), not a plain bool -- its .value is the list
of (sub_gate_name, passed) tuples for every sub-gate actually evaluated
this call. Evaluation still short-circuits on the first failure (same as
the old all(...)), so .value can be a strict prefix of the full sector's
gate list, not every registered gate, when one fails.
"""
from graywind_strategy.gate_result import GateResult
from graywind_strategy.sector_config import SYMBOL_SECTOR


def energy_stub_gate(symbol, as_of_date):
    return True


SECTOR_GATES = {
    "energy": [energy_stub_gate],
}


def evaluate_sector_gates(symbol, as_of_date):
    sector = SYMBOL_SECTOR.get(symbol)
    gates = SECTOR_GATES.get(sector, [])
    readings = []
    for gate in gates:
        passed = gate(symbol=symbol, as_of_date=as_of_date)
        readings.append((gate.__name__, passed))
        if not passed:
            return GateResult(passed=False, value=readings)
    return GateResult(passed=True, value=readings)
