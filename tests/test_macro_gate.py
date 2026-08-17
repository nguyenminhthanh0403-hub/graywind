from graywind_strategy.gates.macro_gate import macro_gate


def test_macro_gate_allows_when_no_fields_breach():
    snapshot = {"vix": 14.6, "nfci": -0.55, "hy_oas": 2.71, "curve_slope": 0.48}
    assert macro_gate(snapshot) is True


def test_macro_gate_allows_when_breaches_below_required_count():
    # Only vix breaches (>= 25.0); default required_breaches=2, so 1 breach still allows.
    snapshot = {"vix": 27.0, "nfci": -0.55, "hy_oas": 2.71, "curve_slope": 0.48}
    assert macro_gate(snapshot) is True


def test_macro_gate_blocks_when_breaches_meet_required_count():
    # vix and nfci both breach at their exact threshold boundary -- 2 of 4, meets default
    # required_breaches=2.
    snapshot = {"vix": 25.0, "nfci": 0.0, "hy_oas": 2.71, "curve_slope": 0.48}
    assert macro_gate(snapshot) is False


def test_macro_gate_blocks_when_all_four_fields_breach():
    snapshot = {"vix": 30.0, "nfci": 0.5, "hy_oas": 6.0, "curve_slope": -0.5}
    assert macro_gate(snapshot) is False


def test_macro_gate_curve_slope_breach_is_less_than_not_greater_than():
    # curve_slope is the one inverted-direction field: breach is < 0.0, not >= 0.0. A
    # deeply positive curve_slope must never count as a breach.
    snapshot = {"vix": 14.6, "nfci": -0.55, "hy_oas": 2.71, "curve_slope": 2.0}
    assert macro_gate(snapshot) is True


def test_macro_gate_respects_custom_required_breaches():
    # 3 breaches, but required_breaches=4 means it takes all 4 to block.
    snapshot = {"vix": 30.0, "nfci": 0.5, "hy_oas": 6.0, "curve_slope": 0.48}
    assert macro_gate(snapshot, required_breaches=4) is True
