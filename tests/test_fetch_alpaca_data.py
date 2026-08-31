import csv
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from alpaca.data.enums import DataFeed

from fetch_alpaca_data import fetch_bars, write_csv


def make_bar(ts, o, h, l, c, v):
    return SimpleNamespace(timestamp=ts, open=o, high=h, low=l, close=c, volume=v)


def make_barset(bars_by_symbol):
    """Stand-in for alpaca-py's BarSet, faithful on the one behavior that
    matters here: BarSet exposes a `.data` dict, and its __getitem__ RAISES
    KeyError("No key X was found.") for a symbol with no bars rather than
    returning an empty list.

    The earlier stub was a plain dict, which silently supports
    `response[symbol]` for present keys and so could never surface that
    difference. fetch_bars was written against the dict's semantics and
    raised KeyError in production whenever Alpaca returned zero bars for a
    symbol -- routine on the IEX feed for a thin name, right after the open,
    or during a partial outage -- which propagated past four separate
    `if not bars:` guards written to handle exactly that case.
    """
    class _BarSet:
        def __init__(self, data):
            self.data = data

        def __getitem__(self, symbol):
            if symbol not in self.data:
                raise KeyError(f"No key {symbol} was found.")
            return self.data[symbol]

    return _BarSet(bars_by_symbol)


def test_write_csv_writes_header_and_rows(tmp_path):
    bars = [make_bar(datetime(2024, 1, 8, 9, 30), 100.0, 101.0, 99.5, 100.5, 1000)]
    path = write_csv("AAPL", bars, output_dir=str(tmp_path))
    with open(path) as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["time", "open", "high", "low", "close", "volume"]
    assert rows[1] == ["2024-01-08 09:30:00", "100.0", "101.0", "99.5", "100.5", "1000"]


def test_write_csv_raises_on_empty_bars_and_writes_nothing(tmp_path):
    with pytest.raises(ValueError):
        write_csv("AAPL", [], output_dir=str(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_fetch_bars_calls_client_with_expected_symbol():
    fake_client = MagicMock()
    fake_client.get_stock_bars.return_value = make_barset({
        "AAPL": [make_bar(datetime(2024, 1, 8), 1, 2, 0.5, 1.5, 10)]
    })
    result = fetch_bars(fake_client, "AAPL", datetime(2024, 1, 1), datetime(2024, 1, 8))
    assert len(result) == 1
    fake_client.get_stock_bars.assert_called_once()


def test_fetch_bars_requests_the_iex_feed():
    # Regression test: a free/paper Alpaca account can't query the default
    # SIP feed for recent data ("subscription does not permit querying
    # recent SIP data", surfaced when fetching real sector-ETF bars for a
    # backtest) -- the request must explicitly ask for the IEX feed, which
    # free-tier accounts are allowed to use.
    fake_client = MagicMock()
    fake_client.get_stock_bars.return_value = make_barset({
        "AAPL": [make_bar(datetime(2024, 1, 8), 1, 2, 0.5, 1.5, 10)]
    })
    fetch_bars(fake_client, "AAPL", datetime(2024, 1, 1), datetime(2024, 1, 8))
    request = fake_client.get_stock_bars.call_args[0][0]
    assert request.feed == DataFeed.IEX


def test_fetch_bars_returns_empty_list_when_symbol_has_no_bars():
    # Regression: alpaca-py's BarSet.__getitem__ raises KeyError for a symbol
    # that came back with no bars, so `list(response[symbol])` blew up instead
    # of returning []. Alpaca does this routinely for a thin symbol on the IEX
    # feed, in the first minutes after the open, and during partial outages.
    # Four separate "no bars, skip this cycle" guards downstream (live_loop's
    # per-symbol skip and run_tier1_rebalance's, tier1_rebalance's price
    # check, write_csv's ValueError) were unreachable because of it.
    fake_client = MagicMock()
    fake_client.get_stock_bars.return_value = make_barset({})
    assert fetch_bars(fake_client, "SERV", datetime(2024, 1, 1), datetime(2024, 1, 8)) == []


def test_fetch_bars_returns_empty_for_missing_symbol_when_others_present():
    fake_client = MagicMock()
    fake_client.get_stock_bars.return_value = make_barset({
        "AAPL": [make_bar(datetime(2024, 1, 8), 1, 2, 0.5, 1.5, 10)]
    })
    assert fetch_bars(fake_client, "SERV", datetime(2024, 1, 1), datetime(2024, 1, 8)) == []
