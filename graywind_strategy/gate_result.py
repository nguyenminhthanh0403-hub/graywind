"""Shared result type for the five signal-augmentation gates
(vix/sentiment/earnings/macro/sector) evaluated in pipeline.py and
gates/sector_gates.py. Lives in its own leaf module (no project imports)
so both of those modules can import it without a circular import --
pipeline.py already imports evaluate_sector_gates FROM
gates/sector_gates.py, so a GateResult defined inside pipeline.py would
force gates/sector_gates.py to import back from pipeline.py.
"""
from dataclasses import dataclass


@dataclass
class GateResult:
    passed: bool
    value: object = None
    detail: str = ""

    def __bool__(self):
        return self.passed
