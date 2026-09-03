from unittest.mock import MagicMock, call

import pytest

from graywind_strategy.trade_approval import (
    IssueNotFound, propose_trade, get_owner_reaction, close_issue,
)


def test_propose_trade_posts_issue_and_returns_number():
    fake_response = MagicMock()
    fake_response.json.return_value = {"number": 101}
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.post.return_value = fake_response

    result = propose_trade(
        symbol="SERV", side="buy", qty=5.0, price=42.0, tier=3, account_label="small",
        reasoning="signal=buy, all gates passed", github_token="tok", repo="me/graywind",
        session=fake_session,
    )

    assert result == 101
    fake_session.post.assert_called_once()
    call_args = fake_session.post.call_args
    assert call_args.args[0] == "https://api.github.com/repos/me/graywind/issues"
    payload = call_args.kwargs["json"]
    assert "SERV" in payload["title"]
    assert "BUY" in payload["title"]
    assert "pending-trade" in payload["labels"]
    assert "account:small" in payload["labels"]
    assert "tier:3" in payload["labels"]


def test_get_owner_reaction_returns_approved_on_owner_thumbs_up():
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = [
        {"content": "+1", "user": {"login": "me"}},
        {"content": "+1", "user": {"login": "a-stranger"}},
    ]
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    result = get_owner_reaction(101, "me", "tok", "me/graywind", session=fake_session)

    assert result == "approved"


def test_get_owner_reaction_returns_rejected_on_owner_thumbs_down():
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = [{"content": "-1", "user": {"login": "me"}}]
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    result = get_owner_reaction(101, "me", "tok", "me/graywind", session=fake_session)

    assert result == "rejected"


def test_get_owner_reaction_ignores_non_owner_reactions():
    # The single most important test in this plan: the repo is public, so a
    # stranger's reaction must never be able to move a real order.
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = [
        {"content": "+1", "user": {"login": "a-stranger"}},
        {"content": "-1", "user": {"login": "another-stranger"}},
    ]
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    result = get_owner_reaction(101, "me", "tok", "me/graywind", session=fake_session)

    assert result is None


def test_get_owner_reaction_returns_none_when_no_reactions_yet():
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = []
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    result = get_owner_reaction(101, "me", "tok", "me/graywind", session=fake_session)

    assert result is None


def test_get_owner_reaction_raises_issue_not_found_on_404():
    fake_response = MagicMock()
    fake_response.status_code = 404
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    with pytest.raises(IssueNotFound):
        get_owner_reaction(101, "me", "tok", "me/graywind", session=fake_session)


def test_close_issue_posts_comment_then_closes():
    fake_session = MagicMock()
    fake_session.post.return_value = MagicMock(raise_for_status=MagicMock(return_value=None))
    fake_session.patch.return_value = MagicMock(raise_for_status=MagicMock(return_value=None))

    close_issue(101, "approved and executed.", "tok", "me/graywind", session=fake_session)

    fake_session.post.assert_called_once_with(
        "https://api.github.com/repos/me/graywind/issues/101/comments",
        headers={"Authorization": "Bearer tok", "Accept": "application/vnd.github+json"},
        json={"body": "approved and executed."}, timeout=10,
    )
    fake_session.patch.assert_called_once_with(
        "https://api.github.com/repos/me/graywind/issues/101",
        headers={"Authorization": "Bearer tok", "Accept": "application/vnd.github+json"},
        json={"state": "closed"}, timeout=10,
    )
