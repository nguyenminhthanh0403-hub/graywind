from graywind_strategy.sector_config import SYMBOL_SECTOR, symbols_in_sector


def test_symbol_sector_contains_all_roster_symbols():
    for symbol in ["AAPL", "XOM", "CVX", "NVDA", "MSFT", "JNJ", "UNH"]:
        assert symbol in SYMBOL_SECTOR


def test_symbol_sector_excludes_broad_market_spy():
    # SPY is a broad-market index, not sector-specific -- deliberately
    # absent from the mapping rather than tagged with an arbitrary sector.
    assert "SPY" not in SYMBOL_SECTOR


def test_symbols_in_sector_returns_expected_energy_symbols():
    assert sorted(symbols_in_sector("energy")) == ["CVX", "XOM"]


def test_symbols_in_sector_returns_expected_tech_symbols():
    assert sorted(symbols_in_sector("tech")) == ["AAPL", "MSFT", "NVDA"]


def test_symbols_in_sector_returns_empty_list_for_unknown_sector():
    assert symbols_in_sector("nonexistent") == []


def test_symbol_sector_tags_serv_as_robotics():
    assert SYMBOL_SECTOR["SERV"] == "robotics"


def test_symbols_in_sector_returns_serv_for_robotics():
    assert symbols_in_sector("robotics") == ["SERV"]
