"""Shared guardrail-violation exception. Lives outside tier_config.py and
backtest_gate.py specifically so both can raise/catch the same class without
importing each other -- tier_config calls into backtest_gate, so the reverse
import would be circular.
"""


class GuardrailViolation(Exception):
    pass
