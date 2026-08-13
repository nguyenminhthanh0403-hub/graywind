import csv
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from fetch_alpaca_data import fetch_bars, write_csv


def make_bar(ts, o, h, l, c, v):
    return SimpleNamespace(timestamp=ts, open=o, high=h, low=l, close=c, volume=v)


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
    fake_client.get_stock_bars.return_value = {
        "AAPL": [make_bar(datetime(2024, 1, 8), 1, 2, 0.5, 1.5, 10)]
    }
    result = fetch_bars(fake_client, "AAPL", datetime(2024, 1, 1), datetime(2024, 1, 8))
    assert len(result) == 1
    fake_client.get_stock_bars.assert_called_once()
