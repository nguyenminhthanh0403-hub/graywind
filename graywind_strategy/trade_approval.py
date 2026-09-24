"""GitHub Issues as the trade-approval surface (personal use only --
docs/superpowers/specs/2026-08-26-graywind-trade-approval-advisor-design.md). Every function
here is a narrow I/O wrapper around the GitHub REST API (create/close an issue, read its
reactions) -- the same pure-logic/thin-I/O split as gates/earnings_gate.py. Orchestration
(which trades to propose, how to resolve a pending one) lives in live_loop.py, which is the
only caller that also knows about trading_client/tier_pools/open_positions.

A proposal is only useful if the owner SEES it: issues #4-#38 all expired unapproved because
a bot-authored issue with no assignee and no @mention generates no GitHub notification at all.
propose_trade() therefore assigns the owner AND @mentions them (either one is enough for
GitHub's own email/mobile push, but assignment also makes the issue findable in the owner's
"Assigned" view) and pushes an ntfy.sh notification to their phone.

The ntfy topic is effectively a BEARER SECRET: ntfy.sh topics are a single public namespace
with no authentication, so anyone who learns or guesses the topic can read every proposal and
publish fake ones to it. Keep it long, random, and in a repo secret -- never in source.
"""
import sys

import requests

GITHUB_API_BASE = "https://api.github.com"
PENDING_TRADE_LABEL = "pending-trade"


class IssueNotFound(Exception):
    pass


def _headers(github_token):
    return {"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github+json"}


def notify_ntfy(topic, title, message, click_url, session=requests):
    """Push a proposal to the owner's phone via ntfy.sh.

    Warns LOUDLY rather than silently returning when no topic is configured: an approval
    surface nobody is watching is the exact failure this whole module exists to fix, so a
    missing topic must show up in the cycle log instead of looking like success.
    """
    if not topic:
        print(
            "WARNING: no NTFY_TOPIC configured -- NO phone notification was sent for this "
            "proposal. It will expire unapproved unless the owner checks GitHub directly.",
            file=sys.stderr,
        )
        return
    # Posted to ntfy.sh's ROOT url with the topic as a FIELD, not to ntfy.sh/<topic>. This is
    # not interchangeable and the wrong one fails silently-ish: ntfy only parses a JSON body
    # when it arrives at the root, so posting this same payload to ntfy.sh/<topic> returns 200
    # while delivering the raw JSON text as the notification message and dropping the title,
    # click link and priority entirely. Verified against the live service, 2026-09-24.
    response = session.post(
        "https://ntfy.sh/",
        json={
            "topic": topic,
            "title": title,
            "message": message,
            "click": click_url,
            "priority": 5,
            "tags": ["moneybag"],
        },
        timeout=10,
    )
    response.raise_for_status()


def propose_trade(symbol, side, qty, price, tier, account_label, reasoning,
                   github_token, repo, owner_username=None, ntfy_topic=None, session=requests):
    url = f"{GITHUB_API_BASE}/repos/{repo}/issues"
    title = f"[Graywind {account_label}] Proposed {side.upper()}: {symbol} (tier {tier})"
    body = (
        f"**Symbol:** {symbol}\n**Side:** {side}\n**Qty:** {qty}\n**Price:** {price}\n"
        f"**Tier:** {tier}\n\n**Reasoning:** {reasoning}\n\n"
        "React with :+1: to approve, :-1: to reject. Unresolved proposals expire at end of "
        "trading day."
    )
    if owner_username:
        body += f"\n\ncc @{owner_username}"
    payload = {"title": title, "body": body, "labels": [
        PENDING_TRADE_LABEL, f"account:{account_label}", f"tier:{tier}",
    ]}
    if owner_username:
        # Omitted entirely rather than sent as [] when there is no owner: GitHub treats an
        # explicit empty assignees list on creation as "assign nobody", which is the same
        # outcome, but sending a key whose value we don't mean invites a future reader to
        # assume assignment was considered and declined rather than unavailable.
        payload["assignees"] = [owner_username]

    response = session.post(url, headers=_headers(github_token), json=payload, timeout=10)
    response.raise_for_status()
    issue_number = response.json()["number"]

    # Deliberately AFTER the issue exists and its number is known, and wrapped so nothing
    # here can propagate: ntfy.sh is a free best-effort service with no SLA, and a proposal
    # that was successfully created must never be lost to a notification hiccup. Losing the
    # return value would strand the issue with no pending_trades row to ever resolve it.
    try:
        notify_ntfy(
            ntfy_topic, title,
            f"{side.upper()} {qty} {symbol} @ {price} (tier {tier}) -- expires at end of "
            "trading day.",
            f"https://github.com/{repo}/issues/{issue_number}",
            session=session,
        )
    except Exception as exc:
        print(f"ntfy notification failed ({exc}); issue #{issue_number} was still created "
              f"and is awaiting approval", file=sys.stderr)

    return issue_number


def get_owner_reaction(issue_number, owner_username, github_token, repo, session=requests):
    url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}/reactions"
    # per_page=100 (the API maximum): this endpoint defaults to 30 per page and
    # this function deliberately does not follow Link headers, so without it 30+
    # reactions from other people on a public repo would push the owner's own
    # :+1: onto page 2 and silently make approving a trade impossible.
    response = session.get(url, headers=_headers(github_token), params={"per_page": 100}, timeout=10)
    if response.status_code == 404:
        raise IssueNotFound(f"issue {issue_number} not found")
    response.raise_for_status()
    reactions = response.json()
    # `user` is null for a reaction left by a since-deleted account; that is not
    # the owner, so it must be skipped rather than raising TypeError -- an
    # exception here leaves the caller's pending_trades row stuck forever.
    owner_reactions = {
        r["content"] for r in reactions if (r.get("user") or {}).get("login") == owner_username
    }
    if "-1" in owner_reactions:
        return "rejected"
    if "+1" in owner_reactions:
        return "approved"
    return None


def close_issue(issue_number, comment, github_token, repo, session=requests):
    # An auto-approved tier-2/3 trade (see tier_config.AUTO_APPROVE_TIERS) never created an
    # issue, so its pending_trades row carries issue_number=None. Returning early here means
    # all four of process_pending_trades' close_issue call sites -- expiry, rejection,
    # failed re-validation and successful execution -- keep working unchanged, instead of each
    # growing its own `if issue_number is not None` guard inside that already dense block.
    if issue_number is None:
        return
    comment_url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}/comments"
    session.post(comment_url, headers=_headers(github_token), json={"body": comment}, timeout=10).raise_for_status()
    issue_url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}"
    session.patch(issue_url, headers=_headers(github_token), json={"state": "closed"}, timeout=10).raise_for_status()
