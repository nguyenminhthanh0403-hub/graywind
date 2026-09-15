import pytest
from fastapi import HTTPException

import rate_limit


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    rate_limit._request_log.clear()
    monkeypatch.setattr(rate_limit, "MAX_REQUESTS_PER_WINDOW", 2)


def test_allows_requests_under_the_limit():
    rate_limit.check_rate_limit("key1")
    rate_limit.check_rate_limit("key1")


def test_blocks_requests_over_the_limit():
    rate_limit.check_rate_limit("key1")
    rate_limit.check_rate_limit("key1")

    with pytest.raises(HTTPException) as exc_info:
        rate_limit.check_rate_limit("key1")

    assert exc_info.value.status_code == 429


def test_limits_are_tracked_independently_per_key():
    rate_limit.check_rate_limit("key1")
    rate_limit.check_rate_limit("key1")
    rate_limit.check_rate_limit("key2")
