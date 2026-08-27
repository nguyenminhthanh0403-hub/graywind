import pytest
from unittest.mock import MagicMock, patch

from graywind_strategy.tier_config import (
    GuardrailViolation, TIER_GUARDRAILS, MAX_SYMBOLS_PER_SECTOR,
    sector_counts_for_tier, check_guardrail, fetch_market_cap, fetch_avg_volume,
    validate_symbol_addition, SYMBOL_TIER, TIER1_SYMBOL_WEIGHTS,
)


def test_symbol_tier_has_the_confirmed_starter_symbols():
    assert SYMBOL_TIER == {"AAPL": 2, "SERV": 3}


def test_tier1_symbol_weights_has_spy_at_full_weight():
    assert TIER1_SYMBOL_WEIGHTS == {"SPY": 1.0}


def test_check_guardrail_passes_when_all_bands_clear():
    # AAPL-like numbers: huge cap, huge volume, sector not yet crowded.
    check_guardrail(
        tier=2, market_cap=3_000_000_000_000, avg_volume=40_000_000,
        sector="tech", existing_sector_counts={"tech": 2},
    )  # no exception == pass


def test_check_guardrail_rejects_market_cap_below_tier2_floor():
    with pytest.raises(GuardrailViolation, match="market cap"):
        check_guardrail(
            tier=2, market_cap=1_999_999_999, avg_volume=1_000_000,
            sector="tech", existing_sector_counts={},
        )


def test_check_guardrail_rejects_market_cap_below_tier3_floor():
    # Mirrors QUIK's real rejected numbers from brainstorming: ~$208M cap, fails the $300M floor.
    with pytest.raises(GuardrailViolation, match="market cap"):
        check_guardrail(
            tier=3, market_cap=208_270_000, avg_volume=281_806,
            sector="tech", existing_sector_counts={},
        )


def test_check_guardrail_accepts_market_cap_exactly_at_tier3_floor():
    check_guardrail(
        tier=3, market_cap=300_000_000, avg_volume=100_000,
        sector="robotics", existing_sector_counts={},
    )  # boundary is inclusive -- no exception == pass


def test_check_guardrail_rejects_volume_below_tier3_floor():
    with pytest.raises(GuardrailViolation, match="volume"):
        check_guardrail(
            tier=3, market_cap=500_000_000, avg_volume=99_999,
            sector="robotics", existing_sector_counts={},
        )


def test_check_guardrail_accepts_serv_like_numbers_for_tier3():
    # SERV's real researched numbers from brainstorming: ~$423M cap, ~5.2M avg volume.
    check_guardrail(
        tier=3, market_cap=422_940_000, avg_volume=5_217_680,
        sector="robotics", existing_sector_counts={},
    )  # no exception == pass


def test_check_guardrail_rejects_when_sector_already_at_cap():
    with pytest.raises(GuardrailViolation, match="sector"):
        check_guardrail(
            tier=2, market_cap=10_000_000_000, avg_volume=1_000_000,
            sector="tech", existing_sector_counts={"tech": MAX_SYMBOLS_PER_SECTOR},
        )


def test_check_guardrail_accepts_when_sector_just_under_cap():
    check_guardrail(
        tier=2, market_cap=10_000_000_000, avg_volume=1_000_000,
        sector="tech", existing_sector_counts={"tech": MAX_SYMBOLS_PER_SECTOR - 1},
    )  # no exception == pass


def test_sector_counts_for_tier_counts_only_matching_tier_and_known_sectors():
    fake_symbol_tier = {"AAPL": 2, "NVDA": 2, "SERV": 3}
    fake_sector_map = {"AAPL": "tech", "NVDA": "tech", "SERV": "robotics"}
    counts = sector_counts_for_tier(tier=2, symbol_tier=fake_symbol_tier, sector_map=fake_sector_map)
    assert counts == {"tech": 2}


def test_fetch_market_cap_converts_finnhub_millions_to_dollars():
    fake_response = MagicMock()
    fake_response.json.return_value = {"marketCapitalization": 423.0}
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    result = fetch_market_cap("SERV", "fake-key", session=fake_session)

    assert result == 423_000_000.0


def test_fetch_market_cap_raises_when_field_missing():
    fake_response = MagicMock()
    fake_response.json.return_value = {}
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    with pytest.raises(GuardrailViolation, match="marketCapitalization"):
        fetch_market_cap("SERV", "fake-key", session=fake_session)


def test_fetch_avg_volume_averages_bar_volumes():
    fake_bar_1 = MagicMock(volume=100)
    fake_bar_2 = MagicMock(volume=300)
    fake_data_client = MagicMock()

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "graywind_strategy.tier_config.fetch_bars",
            lambda client, symbol, start, end: [fake_bar_1, fake_bar_2],
        )
        result = fetch_avg_volume(fake_data_client, "SERV")

    assert result == 200.0


def test_fetch_avg_volume_raises_when_no_bars_returned():
    fake_data_client = MagicMock()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "graywind_strategy.tier_config.fetch_bars",
            lambda client, symbol, start, end: [],
        )
        with pytest.raises(GuardrailViolation, match="no bars"):
            fetch_avg_volume(fake_data_client, "SERV")


def test_validate_symbol_addition_raises_on_first_failing_check():
    fake_response = MagicMock()
    fake_response.json.return_value = {"marketCapitalization": 1.0}  # $1M -- fails every floor
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    fake_data_client = MagicMock()

    with pytest.raises(GuardrailViolation, match="market cap"):
        validate_symbol_addition(
            "PENNY", tier=3, finnhub_api_key="k", data_client=fake_data_client,
            sector="tech", session=fake_session,
        )


def test_validate_symbol_addition_calls_backtest_gate_after_guardrail_checks_pass():
    fake_response = MagicMock()
    fake_response.json.return_value = {"marketCapitalization": 3_000_000.0}  # clears tier 2
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    fake_data_client = MagicMock()

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "graywind_strategy.tier_config.fetch_bars",
            lambda client, symbol, start, end: [MagicMock(volume=1_000_000)],
        )
        with patch("graywind_strategy.backtest_gate.validate_symbol_backtest") as mock_gate:
            validate_symbol_addition(
                "AAPL", tier=2, finnhub_api_key="k", data_client=fake_data_client,
                sector="tech", session=fake_session,
            )
    mock_gate.assert_called_once_with("AAPL", 2, fake_data_client)


def test_validate_symbol_addition_propagates_backtest_gate_rejection():
    fake_response = MagicMock()
    fake_response.json.return_value = {"marketCapitalization": 3_000_000.0}
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    fake_data_client = MagicMock()

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "graywind_strategy.tier_config.fetch_bars",
            lambda client, symbol, start, end: [MagicMock(volume=1_000_000)],
        )
        with patch(
            "graywind_strategy.backtest_gate.validate_symbol_backtest",
            side_effect=GuardrailViolation(
                "SERV: deflated Sharpe ratio 0.400 below 0.95 threshold with 5 trials counted"
            ),
        ):
            with pytest.raises(GuardrailViolation, match="deflated Sharpe"):
                validate_symbol_addition(
                    "SERV", tier=3, finnhub_api_key="k", data_client=fake_data_client,
                    sector="robotics", session=fake_session,
                )
