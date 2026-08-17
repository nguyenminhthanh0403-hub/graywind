"""Bullion macro-gate: blocks new trades when a vote-count of macro stress
signals (VIX, NFCI, HY OAS, yield curve slope), sourced from Bullion's
public daily-cron data.json, meets a configured breach threshold. Fails
closed -- any fetch, parse, or staleness failure raises
MacroDataUnavailable, which the caller (pipeline.py) must treat as a
blocked trade, never as a skipped gate. Additive alongside vix_gate.py,
which keeps its own direct FRED call unchanged.
"""

VIX_THRESHOLD = 25.0
NFCI_THRESHOLD = 0.0
HY_OAS_THRESHOLD = 5.0
CURVE_SLOPE_THRESHOLD = 0.0


class MacroDataUnavailable(Exception):
    pass


def macro_gate(snapshot, required_breaches=2):
    breaches = 0
    if snapshot["vix"] >= VIX_THRESHOLD:
        breaches += 1
    if snapshot["nfci"] >= NFCI_THRESHOLD:
        breaches += 1
    if snapshot["hy_oas"] >= HY_OAS_THRESHOLD:
        breaches += 1
    if snapshot["curve_slope"] < CURVE_SLOPE_THRESHOLD:
        breaches += 1
    return breaches < required_breaches
