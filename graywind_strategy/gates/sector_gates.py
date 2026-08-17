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
"""
from graywind_strategy.sector_config import SYMBOL_SECTOR


def energy_stub_gate(symbol, as_of_date):
    return True


SECTOR_GATES = {
    "energy": [energy_stub_gate],
}


def evaluate_sector_gates(symbol, as_of_date):
    sector = SYMBOL_SECTOR.get(symbol)
    gates = SECTOR_GATES.get(sector, [])
    return all(gate(symbol=symbol, as_of_date=as_of_date) for gate in gates)
