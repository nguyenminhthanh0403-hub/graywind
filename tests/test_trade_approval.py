from unittest.mock import MagicMock, call

import pytest

from graywind_strategy.trade_approval import (
    IssueNotFound, propose_trade, get_owner_reaction, close_issue, notify_ntfy,
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
    # GitHub's reactions endpoint defaults to 30 per page and this function does
    # not follow Link headers, so on a public repo 30+ strangers' reactions could
    # push the owner's own :+1: onto page 2 and silently make approval impossible.
    # per_page=100 raises that ceiling to the API's maximum (final-review Fix 4).
    assert fake_session.get.call_args.kwargs["params"] == {"per_page": 100}


def test_get_owner_reaction_ignores_reaction_from_a_deleted_account():
    # GitHub returns "user": null for a reaction left by an account that has
    # since been deleted. Indexing r["user"]["login"] raises TypeError on that,
    # which (via live_loop's per-symbol except) leaves the pending_trades row
    # stuck forever and permanently disables the symbol. A null user simply
    # isn't the owner, so it must be skipped, not crash the scan.
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = [
        {"content": "+1", "user": None},
        {"content": "+1", "user": {"login": "me"}},
    ]
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    assert get_owner_reaction(101, "me", "tok", "me/graywind", session=fake_session) == "approved"


def test_get_owner_reaction_returns_none_when_only_a_deleted_account_reacted():
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = [{"content": "+1", "user": None}]
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    assert get_owner_reaction(101, "me", "tok", "me/graywind", session=fake_session) is None


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


def test_propose_trade_assigns_and_mentions_owner_and_pushes_ntfy():
    """The whole point of the notification work: issues #4-#38 expired because a bot-authored
    issue with no assignee and no @mention produces no GitHub notification."""
    issue_response = MagicMock()
    issue_response.json.return_value = {"number": 42}
    issue_response.raise_for_status.return_value = None
    ntfy_response = MagicMock()
    ntfy_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.post.side_effect = [issue_response, ntfy_response]

    result = propose_trade(
        symbol="SERV", side="buy", qty=5.0, price=42.0, tier=3, account_label="small",
        reasoning="signal=buy, all gates passed", github_token="tok", repo="me/graywind",
        owner_username="me", ntfy_topic="sekrit-topic", session=fake_session,
    )

    assert result == 42
    issue_call, ntfy_call = fake_session.post.call_args_list
    assert issue_call.args[0] == "https://api.github.com/repos/me/graywind/issues"
    assert issue_call.kwargs["json"]["assignees"] == ["me"]
    assert "cc @me" in issue_call.kwargs["json"]["body"]

    # Root URL with the topic as a payload field -- ntfy.sh only parses JSON at the root.
    # Posting to ntfy.sh/<topic> instead returns 200 but delivers the raw JSON as the message
    # text and silently drops the title/click/priority, so the URL is load-bearing.
    assert ntfy_call.args[0] == "https://ntfy.sh/"
    ntfy_payload = ntfy_call.kwargs["json"]
    assert ntfy_payload["topic"] == "sekrit-topic"
    assert ntfy_payload["click"] == "https://github.com/me/graywind/issues/42"
    assert "SERV" in ntfy_payload["message"]
    assert ntfy_payload["priority"] == 5


def test_propose_trade_omits_assignees_entirely_when_no_owner_is_known():
    fake_response = MagicMock()
    fake_response.json.return_value = {"number": 7}
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.post.return_value = fake_response

    propose_trade(
        symbol="SERV", side="buy", qty=5.0, price=42.0, tier=3, account_label="small",
        reasoning="r", github_token="tok", repo="me/graywind", session=fake_session,
    )

    payload = fake_session.post.call_args.kwargs["json"]
    assert "assignees" not in payload
    assert "cc @" not in payload["body"]


def test_notify_ntfy_warns_loudly_and_posts_nothing_when_no_topic_configured(capsys):
    """A silent no-op here would recreate the original bug in a new place: the cycle would
    look healthy while no notification ever reached anyone."""
    fake_session = MagicMock()

    notify_ntfy(None, "title", "message", "https://example.com", session=fake_session)

    fake_session.post.assert_not_called()
    assert "NTFY_TOPIC" in capsys.readouterr().err


def test_propose_trade_survives_an_ntfy_failure_and_still_returns_the_issue_number(capsys):
    """A created issue must never be lost to a notification hiccup -- without the number the
    caller cannot write a pending_trades row, so the issue could never be resolved."""
    issue_response = MagicMock()
    issue_response.json.return_value = {"number": 99}
    issue_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.post.side_effect = [issue_response, RuntimeError("ntfy.sh is down")]

    result = propose_trade(
        symbol="SERV", side="buy", qty=5.0, price=42.0, tier=3, account_label="small",
        reasoning="r", github_token="tok", repo="me/graywind",
        owner_username="me", ntfy_topic="sekrit-topic", session=fake_session,
    )

    assert result == 99
    assert "ntfy notification failed" in capsys.readouterr().err
