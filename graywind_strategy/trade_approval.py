"""GitHub Issues as the trade-approval surface (personal use only --
docs/superpowers/specs/2026-08-26-graywind-trade-approval-advisor-design.md). Every function
here is a narrow I/O wrapper around the GitHub REST API (create/close an issue, read its
reactions) -- the same pure-logic/thin-I/O split as gates/earnings_gate.py. Orchestration
(which trades to propose, how to resolve a pending one) lives in live_loop.py, which is the
only caller that also knows about trading_client/tier_pools/open_positions.
"""
import requests

GITHUB_API_BASE = "https://api.github.com"
PENDING_TRADE_LABEL = "pending-trade"


class IssueNotFound(Exception):
    pass


def _headers(github_token):
    return {"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github+json"}


def propose_trade(symbol, side, qty, price, tier, account_label, reasoning,
                   github_token, repo, session=requests):
    url = f"{GITHUB_API_BASE}/repos/{repo}/issues"
    title = f"[Graywind {account_label}] Proposed {side.upper()}: {symbol} (tier {tier})"
    body = (
        f"**Symbol:** {symbol}\n**Side:** {side}\n**Qty:** {qty}\n**Price:** {price}\n"
        f"**Tier:** {tier}\n\n**Reasoning:** {reasoning}\n\n"
        "React with :+1: to approve, :-1: to reject. Unresolved proposals expire at end of "
        "trading day."
    )
    labels = [PENDING_TRADE_LABEL, f"account:{account_label}", f"tier:{tier}"]
    response = session.post(
        url, headers=_headers(github_token),
        json={"title": title, "body": body, "labels": labels}, timeout=10,
    )
    response.raise_for_status()
    return response.json()["number"]


def get_owner_reaction(issue_number, owner_username, github_token, repo, session=requests):
    url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}/reactions"
    response = session.get(url, headers=_headers(github_token), timeout=10)
    if response.status_code == 404:
        raise IssueNotFound(f"issue {issue_number} not found")
    response.raise_for_status()
    reactions = response.json()
    owner_reactions = {r["content"] for r in reactions if r["user"]["login"] == owner_username}
    if "-1" in owner_reactions:
        return "rejected"
    if "+1" in owner_reactions:
        return "approved"
    return None


def close_issue(issue_number, comment, github_token, repo, session=requests):
    comment_url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}/comments"
    session.post(comment_url, headers=_headers(github_token), json={"body": comment}, timeout=10).raise_for_status()
    issue_url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}"
    session.patch(issue_url, headers=_headers(github_token), json={"state": "closed"}, timeout=10).raise_for_status()
