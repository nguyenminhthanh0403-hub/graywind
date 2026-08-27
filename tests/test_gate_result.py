from graywind_strategy.gate_result import GateResult


def test_gate_result_is_truthy_when_passed():
    result = GateResult(passed=True, value=15.0)
    assert bool(result) is True
    assert result if result else False  # exercises __bool__ in an `if` context


def test_gate_result_is_falsy_when_not_passed():
    result = GateResult(passed=False, detail="VixDataUnavailable")
    assert bool(result) is False
    assert not result


def test_gate_result_defaults_value_and_detail():
    result = GateResult(passed=True)
    assert result.value is None
    assert result.detail == ""


def test_gate_result_works_in_existing_if_not_idiom():
    # Pins the exact idiom decide_trade uses today: `if not evaluate_x_gate(...)`.
    passing = GateResult(passed=True, value=1)
    blocking = GateResult(passed=False)
    assert not (not passing)
    assert not blocking
