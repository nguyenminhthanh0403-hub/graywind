# Graywind Trade-Approval Advisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate every new-position buy (tiers 1/2/3, both accounts) behind an owner-only GitHub
issue reaction before it executes, while stop-loss/target/rebalance sells keep executing
automatically exactly as today.

**Architecture:** A new `graywind_strategy/trade_approval.py` module is a narrow I/O wrapper
around the GitHub REST API (create an issue, read its reactions, close it) — same
pure-logic/thin-I/O split this codebase already uses in `earnings_gate.py`. A new
`state/pending_trades.csv` (via two new functions in `state_store.py`, following that module's
existing round-trip pattern) tracks proposals awaiting a decision, keyed by symbol so at most
one proposal can be open per symbol at a time. `live_loop.py`'s existing buy-submission sites
(`process_symbol` for tiers 2/3, `run_tier1_rebalance` for tier 1) are changed to propose
instead of execute; a new orchestration function, `process_pending_trades`, resolves every open
proposal once per cycle (expire / reject / re-validate-and-execute) before the rest of the
cycle runs.

**Tech Stack:** Python 3.12/3.14, `pytest`, `unittest.mock`, `requests` — no new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-26-graywind-trade-approval-advisor-design.md`

**Depends on:** `docs/superpowers/plans/2026-08-26-graywind-dual-account-tier-symbols.md`
having already shipped — this plan assumes `live_loop.py` already has a `state_dir` local
variable (from that plan's Task 3) and `WATCHLIST = ["AAPL", "SERV"]`. Do not start this plan
until that one is merged.

## Global Constraints

- TDD (red/green) for every change — this project's existing convention.
- Run tests with the project's venv: `.venv/bin/python -m pytest tests/ -q`.
- **Only a reaction from the repo owner's GitHub username counts as approval/rejection** —
  the repo is public, so this filter is a hard correctness requirement, verified by its own
  dedicated test in Task 2 (`test_get_owner_reaction_ignores_non_owner_reactions`) — this is
  the single most important test in this plan.
- **Sells stay fully automatic** — stop-loss/target exits (`process_symbol`'s sell branch) and
  tier-1 rebalance sells (`run_tier1_rebalance`'s sell branch) are **not touched** by this
  plan. Only the buy branches change.
- Price-staleness re-check tolerance at approval time: 2% (`PRICE_STALENESS_TOLERANCE = 0.02`
  in `live_loop.py`).
- Proposal expiry: same trading day — a pending trade whose `proposed_date` isn't today's date
  is closed as expired with no order, checked at the start of every cycle's resolution pass.
- No new GitHub secrets needed: `GITHUB_TOKEN` is GitHub Actions' own automatically-provided
  secret (needs threading into each job's `env:` block, Task 6); `GITHUB_REPOSITORY`
  (`"owner/repo"`) and the repo owner's username (`GITHUB_REPOSITORY.split("/")[0]`) are both
  already available as implicit environment values in every Actions job — no new secret or
  config value to set up.
- `stop_price`/`target_price` must travel with a tier-2/3 proposal from creation through to
  execution (`open_positions[symbol]["stop"]`/`["target"]` — consumed by `process_symbol`'s
  existing stop/target-exit check on every later cycle). This isn't spelled out at the CSV
  level in the design spec's prose; it's a plan-level detail filling that gap — the
  `pending_trades` row schema in Task 1 includes both fields (`None` for tier-1 proposals,
  which have no stop/target concept).
- Tier-1 approved buys must **not** be added to `open_positions` — tier-1 holdings are tracked
  by querying Alpaca's real positions directly in `run_tier1_rebalance` (see that function's
  existing `real_positions = {p.symbol: ... for p in trading_client.get_all_positions()}`
  line), not via `open_positions`. Only tier-2/3 approved buys touch `open_positions`.

---

## Task 1: `pending_trades.csv` persistence in `state_store.py`

**Files:**
- Modify: `graywind_strategy/state_store.py`
- Test: `tests/test_state_store.py`

**Interfaces:**
- Produces: `load_pending_trades(state_dir=DEFAULT_STATE_DIR) -> dict[str, dict]` (keyed by
  symbol; each value has keys `issue_number: int, side: str, qty: float,
  price_at_proposal: float, stop_price: float | None, target_price: float | None,
  tier: int | None, proposed_date: str`), `save_pending_trades(pending_trades,
  state_dir=DEFAULT_STATE_DIR) -> None`.
- Consumes: nothing new (follows the exact pattern of this file's existing
  `load_tier_pools`/`save_tier_pools`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_state_store.py`:

```python
from graywind_strategy.state_store import load_pending_trades, save_pending_trades


def test_load_pending_trades_returns_empty_dict_when_no_file_exists(tmp_path):
    assert load_pending_trades(state_dir=str(tmp_path / "nonexistent")) == {}


def test_save_then_load_round_trips_pending_trades(tmp_path):
    state_dir = str(tmp_path)
    pending_trades = {
        "AAPL": {
            "issue_number": 42, "side": "buy", "qty": 3.0, "price_at_proposal": 190.5,
            "stop_price": 185.0, "target_price": 200.0, "tier": 2, "proposed_date": "2026-08-26",
        },
        "SPY": {
            "issue_number": 43, "side": "buy", "qty": 1.0, "price_at_proposal": 550.0,
            "stop_price": None, "target_price": None, "tier": 1, "proposed_date": "2026-08-26",
        },
    }
    save_pending_trades(pending_trades, state_dir=state_dir)
    loaded = load_pending_trades(state_dir=state_dir)
    assert loaded == pending_trades


def test_save_pending_trades_creates_state_dir_if_missing(tmp_path):
    state_dir = str(tmp_path / "new_dir")
    save_pending_trades({}, state_dir=state_dir)
    assert os.path.exists(os.path.join(state_dir, "pending_trades.csv"))


def test_save_pending_trades_overwrites_previous_contents(tmp_path):
    state_dir = str(tmp_path)
    save_pending_trades({
        "AAPL": {
            "issue_number": 1, "side": "buy", "qty": 1.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2026-08-25",
        },
    }, state_dir=state_dir)
    save_pending_trades({}, state_dir=state_dir)
    assert load_pending_trades(state_dir=state_dir) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_state_store.py -v -k pending_trades`
Expected: FAIL — `ImportError` (`load_pending_trades`/`save_pending_trades` don't exist yet).

- [ ] **Step 3: Implement**

In `graywind_strategy/state_store.py`, add near the other filename/fields constants:

```python
PENDING_TRADES_FILENAME = "pending_trades.csv"
PENDING_TRADES_FIELDS = [
    "symbol", "issue_number", "side", "qty", "price_at_proposal",
    "stop_price", "target_price", "tier", "proposed_date",
]
```

Add these two functions (after `save_rebalance_state`):

```python
def load_pending_trades(state_dir=DEFAULT_STATE_DIR):
    pending_trades = {}
    path = os.path.join(state_dir, PENDING_TRADES_FILENAME)
    if os.path.exists(path):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                pending_trades[row["symbol"]] = {
                    "issue_number": int(row["issue_number"]),
                    "side": row["side"],
                    "qty": float(row["qty"]),
                    "price_at_proposal": float(row["price_at_proposal"]),
                    "stop_price": float(row["stop_price"]) if row["stop_price"] else None,
                    "target_price": float(row["target_price"]) if row["target_price"] else None,
                    "tier": int(row["tier"]) if row["tier"] else None,
                    "proposed_date": row["proposed_date"],
                }
    return pending_trades


def save_pending_trades(pending_trades, state_dir=DEFAULT_STATE_DIR):
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, PENDING_TRADES_FILENAME), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PENDING_TRADES_FIELDS, lineterminator="\n")
        writer.writeheader()
        for symbol, trade in pending_trades.items():
            writer.writerow({
                "symbol": symbol,
                "issue_number": trade["issue_number"],
                "side": trade["side"],
                "qty": trade["qty"],
                "price_at_proposal": trade["price_at_proposal"],
                "stop_price": trade["stop_price"] if trade["stop_price"] is not None else "",
                "target_price": trade["target_price"] if trade["target_price"] is not None else "",
                "tier": trade["tier"] if trade["tier"] is not None else "",
                "proposed_date": trade["proposed_date"],
            })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_state_store.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/state_store.py tests/test_state_store.py
git commit -m "feat: persist pending trade-approval proposals in state_store"
```

---

## Task 2: `trade_approval.py` — GitHub Issues I/O wrapper

**Files:**
- Create: `graywind_strategy/trade_approval.py`
- Test: `tests/test_trade_approval.py` (new file)

**Interfaces:**
- Produces: `IssueNotFound(Exception)`, `propose_trade(symbol, side, qty, price, tier,
  account_label, reasoning, github_token, repo, session=requests) -> int` (returns the created
  issue's number), `get_owner_reaction(issue_number, owner_username, github_token, repo,
  session=requests) -> "approved" | "rejected" | None` (raises `IssueNotFound` on a 404),
  `close_issue(issue_number, comment, github_token, repo, session=requests) -> None`.
- Consumes: nothing from earlier tasks.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_trade_approval.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_trade_approval.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graywind_strategy.trade_approval'`.

- [ ] **Step 3: Implement**

Create `graywind_strategy/trade_approval.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_trade_approval.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add graywind_strategy/trade_approval.py tests/test_trade_approval.py
git commit -m "feat: add GitHub-Issues trade-approval I/O wrapper"
```

---

## Task 3: `process_symbol` proposes tier-2/3 buys instead of executing

**Files:**
- Modify: `live_loop.py`
- Test: `tests/test_live_loop.py`

**Interfaces:**
- Consumes: `graywind_strategy.trade_approval.propose_trade` (Task 2).
- Produces: `process_symbol(..., pending_trades=None, github_token=None, repo=None,
  account_label=None, session=requests)` — five new optional params. On a `"buy"` decision:
  if `symbol` already has a row in `pending_trades`, skip (no duplicate issue); otherwise call
  `trade_approval.propose_trade(...)` and add a row to `pending_trades[symbol]` with keys
  `issue_number, side, qty, price_at_proposal, stop_price, target_price, tier,
  proposed_date` — **no order is submitted, `tier_pools`/`open_positions` are not touched**
  (that now only happens in Task 5's `process_pending_trades`, after approval).

- [ ] **Step 1: Write the failing tests**

Add `import requests` to the top of `tests/test_live_loop.py` (alongside the existing
`import os` / `import pandas as pd` lines) — the tests below assert against `process_symbol`'s
default `session=requests` value.

First, update the shared `_call` helper near the top of `tests/test_live_loop.py` to thread
the new params through with sensible defaults so every *other* existing test in the file
(which don't exercise the buy path) keeps working unchanged:

```python
def _call(symbol="AAPL", signal="hold", current_price=100.0, today=date(2024, 1, 8),
          open_positions=None, trading_client=None, pdt_throttle=None, decide_return=None,
          drawdown_breaker=None, equity=10000.0, tier_pools=None, pending_trades=None):
    open_positions = {} if open_positions is None else open_positions
    trading_client = MagicMock() if trading_client is None else trading_client
    pdt_throttle = MagicMock() if pdt_throttle is None else pdt_throttle
    drawdown_breaker = MagicMock() if drawdown_breaker is None else drawdown_breaker
    pending_trades = {} if pending_trades is None else pending_trades
    with patch(
        "live_loop.decide_trade",
        return_value=decide_return or TradeDecision(action="hold", reason="no buy signal"),
    ) as mock_decide:
        process_symbol(
            symbol=symbol, signal=signal, current_price=current_price, today=today,
            open_positions=open_positions, equity=equity,
            pdt_throttle=pdt_throttle, position_sizer=MagicMock(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(),
            finnhub_api_key="k", trading_client=trading_client,
            drawdown_breaker=drawdown_breaker, tier_pools=tier_pools,
            pending_trades=pending_trades, github_token="tok", repo="me/graywind",
            account_label="100k",
        )
    return mock_decide, trading_client, pdt_throttle, open_positions, drawdown_breaker
```

Now rewrite the two existing buy-path tests that this change breaks. Replace
`test_process_symbol_records_buy_trade_and_status_when_collectors_passed`:

```python
def test_process_symbol_proposes_buy_instead_of_executing():
    # SYMBOL_TIER is patched explicitly here (rather than relying on AAPL's real tag) so this
    # test is isolated from tier_config.py's actual contents -- AAPL is tagged tier 2 for real
    # once the dual-account/tier-symbols plan has shipped, and this test's `tier=2` expectation
    # must track that, not silently drift to `None` if tier_config.py ever changes.
    cycle_trades = []
    symbol_statuses = {}
    pending_trades = {}
    with patch.dict("live_loop.SYMBOL_TIER", {"AAPL": 2}, clear=True), patch(
        "live_loop.decide_trade",
        return_value=TradeDecision(action="buy", reason="signal=buy", shares=10, stop_price=98.0, target_price=103.0),
    ), patch("live_loop.trade_approval.propose_trade", return_value=101) as mock_propose:
        trading_client = MagicMock()
        process_symbol(
            symbol="AAPL", signal="buy", current_price=100.0, today=date(2024, 1, 8),
            open_positions={}, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
            trading_client=trading_client, drawdown_breaker=MagicMock(),
            cycle_timestamp="2026-08-15T10:00:00-04:00", cycle_trades=cycle_trades, symbol_statuses=symbol_statuses,
            pending_trades=pending_trades, github_token="tok", repo="me/graywind", account_label="100k",
        )
    mock_propose.assert_called_once_with(
        symbol="AAPL", side="buy", qty=10, price=100.0, tier=2, account_label="100k",
        reasoning="signal=buy", github_token="tok", repo="me/graywind", session=requests,
    )
    trading_client.submit_order.assert_not_called()
    assert cycle_trades == []  # not a real trade yet -- just a proposal
    assert symbol_statuses["AAPL"]["action"] == "proposed"
    assert pending_trades["AAPL"] == {
        "issue_number": 101, "side": "buy", "qty": 10, "price_at_proposal": 100.0,
        "stop_price": 98.0, "target_price": 103.0, "tier": 2, "proposed_date": "2024-01-08",
    }
```

Replace `test_process_symbol_buy_decrements_tier_pool_cash`:

```python
def test_process_symbol_buy_proposal_does_not_touch_tier_pool_cash():
    with patch.dict("live_loop.SYMBOL_TIER", {"AAPL": 2}, clear=True), \
         patch("live_loop.trade_approval.propose_trade", return_value=101):
        tier_pools = {1: 0.0, 2: 500.0, 3: 0.0}
        _call(
            symbol="AAPL", signal="buy", current_price=100.0, equity=10000.0,
            tier_pools=tier_pools,
            decide_return=TradeDecision(
                action="buy", reason="all checks passed",
                shares=2.0, stop_price=95.0, target_price=110.0,
            ),
        )
    assert tier_pools[2] == 500.0  # unchanged -- only execution (Task 5) touches this
```

Add a duplicate-proposal test:

```python
def test_process_symbol_skips_duplicate_proposal_for_already_pending_symbol():
    pending_trades = {
        "AAPL": {
            "issue_number": 99, "side": "buy", "qty": 5.0, "price_at_proposal": 95.0,
            "stop_price": 90.0, "target_price": 100.0, "tier": 2, "proposed_date": "2024-01-08",
        },
    }
    with patch("live_loop.trade_approval.propose_trade") as mock_propose:
        _call(
            symbol="AAPL", signal="buy", pending_trades=pending_trades,
            decide_return=TradeDecision(action="buy", reason="signal=buy", shares=10, stop_price=98.0, target_price=103.0),
        )
    mock_propose.assert_not_called()
    assert pending_trades["AAPL"]["issue_number"] == 99  # untouched, not overwritten
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -v -k "propose or pending_trade"`
Expected: FAIL — `TypeError: process_symbol() got an unexpected keyword argument
'pending_trades'`.

- [ ] **Step 3: Implement**

At the top of `live_loop.py`, add the import (alongside the existing `graywind_strategy`
imports):

```python
from graywind_strategy import trade_approval
```

Change `process_symbol`'s signature (the `def process_symbol(...)` line) to add the five new
parameters:

```python
def process_symbol(symbol, signal, current_price, today, open_positions, equity,
                    pdt_throttle, position_sizer, drawdown_breaker_ok,
                    fred_api_key, news_client, finnhub_api_key, trading_client,
                    drawdown_breaker, cycle_timestamp=None, cycle_trades=None,
                    symbol_statuses=None, tier_pools=None, pending_trades=None,
                    github_token=None, repo=None, account_label=None, session=requests):
```

(`requests` needs importing at the top of `live_loop.py` too: add `import requests` next to
the existing `import os`/`import sys` lines.)

Right after the existing `if cycle_trades is None: ... if symbol_statuses is None: ...` guard
near the top of the function body, add:

```python
    if pending_trades is None:
        pending_trades = {}
```

Replace the entire `if decision.action == "buy":` block (the block that currently builds a
`MarketOrderRequest`, calls `trading_client.submit_order`, decrements `tier_pools`, and sets
`open_positions[symbol]`) with:

```python
        if decision.action == "buy":
            if symbol in pending_trades:
                symbol_statuses[symbol] = {
                    "position_open": False, "shares": None, "entry_price": None,
                    "current_price": current_price, "action": "pending",
                    "reason": "awaiting approval on existing proposal",
                }
                print(f"{symbol}: already has a pending trade proposal, skipping")
            else:
                issue_number = trade_approval.propose_trade(
                    symbol=symbol, side="buy", qty=decision.shares, price=current_price,
                    tier=tier, account_label=account_label, reasoning=decision.reason,
                    github_token=github_token, repo=repo, session=session,
                )
                pending_trades[symbol] = {
                    "issue_number": issue_number, "side": "buy", "qty": decision.shares,
                    "price_at_proposal": current_price, "stop_price": decision.stop_price,
                    "target_price": decision.target_price, "tier": tier,
                    "proposed_date": today.isoformat(),
                }
                symbol_statuses[symbol] = {
                    "position_open": False, "shares": None, "entry_price": None,
                    "current_price": current_price, "action": "proposed", "reason": decision.reason,
                }
                print(f"{symbol}: proposed buy for {decision.shares} shares (issue #{issue_number}), awaiting approval")
```

(The `else:` branch for `decision.action != "buy"` right below, and everything else in the
function, stays exactly as it is.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add live_loop.py tests/test_live_loop.py
git commit -m "feat: propose tier-2/3 buys via GitHub issue instead of executing directly"
```

---

## Task 4: `run_tier1_rebalance` proposes tier-1 buys instead of executing

**Files:**
- Modify: `live_loop.py`
- Test: `tests/test_live_loop.py`

**Interfaces:**
- Consumes: `graywind_strategy.trade_approval.propose_trade` (Task 2).
- Produces: `run_tier1_rebalance(trading_client, data_client, tier_pools, pending_trades=None,
  github_token=None, repo=None, account_label=None, today=None, session=requests)` — five new
  optional params. Sell orders (overweight drift) still submit and settle immediately, exactly
  as before. Buy orders (underweight drift) propose via `trade_approval.propose_trade` instead
  of submitting — `tier_pools` is **not** touched for a proposed buy, and the bought symbol is
  **not** added to `open_positions` (tier-1 holdings are tracked via
  `trading_client.get_all_positions()`, not `open_positions` — see Global Constraints).

- [ ] **Step 1: Write the failing tests**

Rewrite `test_run_tier1_rebalance_submits_orders_and_updates_tier_pool_cash` (the buy-path
test — it currently asserts immediate execution, which this task changes):

```python
def test_run_tier1_rebalance_proposes_buy_instead_of_executing():
    fake_bar = MagicMock(close=100.0)
    trading_client = MagicMock()
    trading_client.get_all_positions.return_value = [MagicMock(symbol="VTI", qty="5")]
    tier_pools = {1: 200.0, 2: 0.0, 3: 0.0}
    pending_trades = {}
    with patch.dict("live_loop.TIER1_SYMBOL_WEIGHTS", {"VTI": 1.0}, clear=True), \
         patch("live_loop.fetch_bars", return_value=[fake_bar]), \
         patch("live_loop.trade_approval.propose_trade", return_value=201) as mock_propose:
        orders = run_tier1_rebalance(
            trading_client, MagicMock(), tier_pools, pending_trades=pending_trades,
            github_token="tok", repo="me/graywind", account_label="100k", today=date(2026, 8, 26),
        )
    # Same underlying drift math as before this task -- see the original test's comment:
    # tier1_equity=700.0, target=700.0, current=500.0, drift=-0.286 -> buy 2.0 shares.
    assert len(orders) == 1
    assert orders[0].symbol == "VTI"
    assert orders[0].side == "buy"
    assert orders[0].qty == 2.0
    trading_client.submit_order.assert_not_called()
    mock_propose.assert_called_once_with(
        symbol="VTI", side="buy", qty=2.0, price=100.0, tier=1, account_label="100k",
        reasoning="tier-1 monthly drift rebalance", github_token="tok", repo="me/graywind",
        session=requests,
    )
    assert tier_pools[1] == 200.0  # unchanged -- only execution (Task 5) touches this
    assert pending_trades["VTI"] == {
        "issue_number": 201, "side": "buy", "qty": 2.0, "price_at_proposal": 100.0,
        "stop_price": None, "target_price": None, "tier": 1, "proposed_date": "2026-08-26",
    }
```

Add a new sell-path regression test (this branch is untouched by this task, but wasn't
covered by a dedicated `run_tier1_rebalance`-level test before — worth locking down given this
task edits the branching logic directly):

```python
def test_run_tier1_rebalance_sell_still_executes_immediately():
    fake_bar = MagicMock(close=100.0)
    trading_client = MagicMock()
    trading_client.get_all_positions.return_value = [MagicMock(symbol="VTI", qty="7")]
    tier_pools = {1: 0.0, 2: 0.0, 3: 0.0}
    with patch.dict("live_loop.TIER1_SYMBOL_WEIGHTS", {"VTI": 0.6}, clear=True), \
         patch("live_loop.fetch_bars", return_value=[fake_bar]), \
         patch("live_loop.trade_approval.propose_trade") as mock_propose:
        # tier1_equity = 0.0 + 7*100 = 700.0; target = 700*0.6 = 420.0; current = 700.0;
        # drift = (700-420)/700 = 0.4 > 0.05 -> sell (700-420)/100 = 2.8 shares.
        orders = run_tier1_rebalance(trading_client, MagicMock(), tier_pools)
    assert orders[0].side == "sell"
    trading_client.submit_order.assert_called_once()
    mock_propose.assert_not_called()
    assert tier_pools[1] == 280.0  # 0.0 + 2.8 * 100.0 -- sell still settles immediately
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -v -k "run_tier1_rebalance"`
Expected: FAIL — the rewritten buy test fails on the old immediate-execution assertions (or
`TypeError` on the new kwargs, depending on which test runs first); the sell test currently
fails only because `trade_approval` isn't imported as a patch target yet (import error inside
the `patch()` call).

- [ ] **Step 3: Implement**

Change `run_tier1_rebalance`'s signature and body in `live_loop.py`:

```python
def run_tier1_rebalance(trading_client, data_client, tier_pools, pending_trades=None,
                         github_token=None, repo=None, account_label=None, today=None,
                         session=requests):
    """I/O wrapper around tier1_rebalance.compute_rebalance_orders(): fetches
    each tier-1 symbol's latest bar and Alpaca's real current holdings,
    computes the rebalance orders, and settles them -- sells execute
    immediately (risk-reducing, stays automatic); buys are proposed via a
    GitHub issue instead of submitted directly (docs/superpowers/specs/
    2026-08-26-graywind-trade-approval-advisor-design.md). No-ops entirely
    (zero I/O) when TIER1_SYMBOL_WEIGHTS is empty -- see tier_config.py.
    """
    if not TIER1_SYMBOL_WEIGHTS:
        return []
    pending_trades = {} if pending_trades is None else pending_trades
    if today is None:
        today = datetime.now(ET).date()

    now = datetime.now(ET)
    current_prices = {}
    for symbol in TIER1_SYMBOL_WEIGHTS:
        bars = fetch_bars(data_client, symbol, now - SIGNAL_LOOKBACK, now)
        if bars:
            current_prices[symbol] = bars[-1].close

    real_positions = {p.symbol: float(p.qty) for p in trading_client.get_all_positions()}
    current_holdings = {symbol: real_positions.get(symbol, 0.0) for symbol in TIER1_SYMBOL_WEIGHTS}

    tier1_equity = tier_pools[1] + sum(
        current_holdings[s] * current_prices[s] for s in current_holdings if s in current_prices
    )
    orders = compute_rebalance_orders(
        tier1_equity=tier1_equity, current_holdings=current_holdings,
        current_prices=current_prices, target_weights=TIER1_SYMBOL_WEIGHTS,
    )
    for order in orders:
        if order.side == "buy":
            if order.symbol in pending_trades:
                print(f"{order.symbol}: already has a pending trade proposal, skipping rebalance buy")
                continue
            issue_number = trade_approval.propose_trade(
                symbol=order.symbol, side="buy", qty=order.qty, price=current_prices[order.symbol],
                tier=1, account_label=account_label, reasoning="tier-1 monthly drift rebalance",
                github_token=github_token, repo=repo, session=session,
            )
            pending_trades[order.symbol] = {
                "issue_number": issue_number, "side": "buy", "qty": order.qty,
                "price_at_proposal": current_prices[order.symbol], "stop_price": None,
                "target_price": None, "tier": 1, "proposed_date": today.isoformat(),
            }
            print(f"{order.symbol}: proposed tier-1 rebalance buy for {order.qty} shares (issue #{issue_number})")
            continue
        market_order = MarketOrderRequest(
            symbol=order.symbol, qty=order.qty,
            side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
        )
        trading_client.submit_order(market_order)
        notional = order.qty * current_prices[order.symbol]
        tier_pools[1] += notional
        print(f"{order.symbol}: submitted tier-1 rebalance sell for {order.qty} shares")
    return orders
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add live_loop.py tests/test_live_loop.py
git commit -m "feat: propose tier-1 rebalance buys via GitHub issue instead of executing directly"
```

---

## Task 5: `process_pending_trades` resolution + wiring into `main()`

**Files:**
- Modify: `live_loop.py`
- Test: `tests/test_live_loop.py`

**Interfaces:**
- Consumes: `graywind_strategy.trade_approval.{get_owner_reaction, close_issue,
  IssueNotFound}` (Task 2), `graywind_strategy.state_store.{load_pending_trades,
  save_pending_trades}` (Task 1), `process_symbol`/`run_tier1_rebalance`'s new params (Tasks
  3/4).
- Produces: `process_pending_trades(pending_trades, today, trading_client, drawdown_breaker,
  github_token, repo, owner_username, tier_pools, open_positions, data_client,
  cycle_trades=None, symbol_statuses=None, session=requests) -> None` (mutates
  `pending_trades`/`tier_pools`/`open_positions`/`cycle_trades`/`symbol_statuses` in place).
  `main()` calls this once per cycle, right after `open_positions = reconcile_positions(...)`
  and before the tier-1-rebalance-trigger check, and threads `pending_trades`/`github_token`/
  `repo`/`account_label` into its `process_symbol`/`run_tier1_rebalance` calls.

- [ ] **Step 1: Write the failing tests for `process_pending_trades`**

Add `from graywind_strategy import trade_approval` and update the existing
`from live_loop import is_market_hours, process_symbol, run_tier1_rebalance` line to also
import `process_pending_trades`, in the top-of-file imports of `tests/test_live_loop.py`.

Then add to `tests/test_live_loop.py` (anywhere after the existing test functions):

```python
def test_process_pending_trades_expires_stale_proposal():
    pending_trades = {
        "AAPL": {
            "issue_number": 1, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-07",
        },
    }
    with patch("live_loop.trade_approval.close_issue") as mock_close, \
         patch("live_loop.trade_approval.get_owner_reaction") as mock_reaction:
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=MagicMock(),
            drawdown_breaker=MagicMock(), github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 0.0, 3: 0.0}, open_positions={},
            data_client=MagicMock(),
        )
    mock_close.assert_called_once()
    assert mock_close.call_args.args[0] == 1
    mock_reaction.assert_not_called()  # expired before a reaction was even checked
    assert pending_trades == {}


def test_process_pending_trades_closes_on_owner_rejection():
    pending_trades = {
        "AAPL": {
            "issue_number": 2, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-08",
        },
    }
    with patch("live_loop.trade_approval.get_owner_reaction", return_value="rejected"), \
         patch("live_loop.trade_approval.close_issue") as mock_close:
        trading_client = MagicMock()
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=trading_client,
            drawdown_breaker=MagicMock(), github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 0.0, 3: 0.0}, open_positions={},
            data_client=MagicMock(),
        )
    trading_client.submit_order.assert_not_called()
    mock_close.assert_called_once()
    assert pending_trades == {}


def test_process_pending_trades_leaves_undecided_proposal_open():
    pending_trades = {
        "AAPL": {
            "issue_number": 3, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-08",
        },
    }
    with patch("live_loop.trade_approval.get_owner_reaction", return_value=None), \
         patch("live_loop.trade_approval.close_issue") as mock_close:
        trading_client = MagicMock()
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=trading_client,
            drawdown_breaker=MagicMock(), github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 0.0, 3: 0.0}, open_positions={},
            data_client=MagicMock(),
        )
    trading_client.submit_order.assert_not_called()
    mock_close.assert_not_called()
    assert "AAPL" in pending_trades  # still waiting


def test_process_pending_trades_executes_approved_tier2_buy_and_opens_position():
    fake_bar = MagicMock(close=101.0)  # within 2% of the 100.0 proposal price
    pending_trades = {
        "AAPL": {
            "issue_number": 4, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-08",
        },
    }
    open_positions = {}
    tier_pools = {1: 0.0, 2: 500.0, 3: 0.0}
    cycle_trades = []
    symbol_statuses = {}
    trading_client = MagicMock()
    drawdown_breaker = MagicMock()
    drawdown_breaker.can_open_new_trade.return_value = True
    with patch("live_loop.trade_approval.get_owner_reaction", return_value="approved"), \
         patch("live_loop.trade_approval.close_issue") as mock_close, \
         patch("live_loop.fetch_bars", return_value=[fake_bar]):
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=trading_client,
            drawdown_breaker=drawdown_breaker, github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools=tier_pools, open_positions=open_positions,
            data_client=MagicMock(), cycle_trades=cycle_trades, symbol_statuses=symbol_statuses,
        )
    trading_client.submit_order.assert_called_once()
    assert tier_pools[2] == 500.0 - 5.0 * 101.0
    assert open_positions["AAPL"] == {
        "entry_price": 101.0, "shares": 5.0, "stop": 95.0, "target": 110.0,
        "opened_date": "2024-01-08",
    }
    assert cycle_trades[0]["symbol"] == "AAPL"
    assert cycle_trades[0]["side"] == "buy"
    mock_close.assert_called_once()
    assert pending_trades == {}


def test_process_pending_trades_executes_approved_tier1_buy_without_opening_position():
    fake_bar = MagicMock(close=100.0)
    pending_trades = {
        "SPY": {
            "issue_number": 5, "side": "buy", "qty": 1.0, "price_at_proposal": 100.0,
            "stop_price": None, "target_price": None, "tier": 1, "proposed_date": "2024-01-08",
        },
    }
    open_positions = {}
    tier_pools = {1: 500.0, 2: 0.0, 3: 0.0}
    trading_client = MagicMock()
    drawdown_breaker = MagicMock()
    drawdown_breaker.can_open_new_trade.return_value = True
    with patch("live_loop.trade_approval.get_owner_reaction", return_value="approved"), \
         patch("live_loop.trade_approval.close_issue"), \
         patch("live_loop.fetch_bars", return_value=[fake_bar]):
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=trading_client,
            drawdown_breaker=drawdown_breaker, github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools=tier_pools, open_positions=open_positions,
            data_client=MagicMock(),
        )
    trading_client.submit_order.assert_called_once()
    assert tier_pools[1] == 400.0  # 500.0 - 1.0 * 100.0
    assert open_positions == {}  # tier-1 holdings are tracked via Alpaca, not open_positions


def test_process_pending_trades_rejects_approved_buy_on_stale_price():
    fake_bar = MagicMock(close=110.0)  # 10% above the 100.0 proposal price -- exceeds 2% tolerance
    pending_trades = {
        "AAPL": {
            "issue_number": 6, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-08",
        },
    }
    trading_client = MagicMock()
    drawdown_breaker = MagicMock()
    drawdown_breaker.can_open_new_trade.return_value = True
    with patch("live_loop.trade_approval.get_owner_reaction", return_value="approved"), \
         patch("live_loop.trade_approval.close_issue") as mock_close, \
         patch("live_loop.fetch_bars", return_value=[fake_bar]):
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=trading_client,
            drawdown_breaker=drawdown_breaker, github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 500.0, 3: 0.0}, open_positions={},
            data_client=MagicMock(),
        )
    trading_client.submit_order.assert_not_called()
    mock_close.assert_called_once()
    assert "price moved" in mock_close.call_args.args[1]
    assert pending_trades == {}


def test_process_pending_trades_rejects_approved_buy_when_drawdown_breaker_blocks():
    fake_bar = MagicMock(close=100.0)
    pending_trades = {
        "AAPL": {
            "issue_number": 7, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-08",
        },
    }
    trading_client = MagicMock()
    drawdown_breaker = MagicMock()
    drawdown_breaker.can_open_new_trade.return_value = False
    with patch("live_loop.trade_approval.get_owner_reaction", return_value="approved"), \
         patch("live_loop.trade_approval.close_issue") as mock_close, \
         patch("live_loop.fetch_bars", return_value=[fake_bar]):
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=trading_client,
            drawdown_breaker=drawdown_breaker, github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 500.0, 3: 0.0}, open_positions={},
            data_client=MagicMock(),
        )
    trading_client.submit_order.assert_not_called()
    mock_close.assert_called_once()
    assert "drawdown" in mock_close.call_args.args[1]


def test_process_pending_trades_rejects_approved_buy_when_position_already_open():
    fake_bar = MagicMock(close=100.0)
    pending_trades = {
        "AAPL": {
            "issue_number": 8, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-08",
        },
    }
    open_positions = {"AAPL": _position()}
    trading_client = MagicMock()
    drawdown_breaker = MagicMock()
    drawdown_breaker.can_open_new_trade.return_value = True
    with patch("live_loop.trade_approval.get_owner_reaction", return_value="approved"), \
         patch("live_loop.trade_approval.close_issue") as mock_close, \
         patch("live_loop.fetch_bars", return_value=[fake_bar]):
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=trading_client,
            drawdown_breaker=drawdown_breaker, github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 500.0, 3: 0.0}, open_positions=open_positions,
            data_client=MagicMock(),
        )
    trading_client.submit_order.assert_not_called()
    mock_close.assert_called_once()
    assert "already opened" in mock_close.call_args.args[1]


def test_process_pending_trades_removes_row_on_issue_not_found():
    pending_trades = {
        "AAPL": {
            "issue_number": 9, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-08",
        },
    }
    with patch("live_loop.trade_approval.get_owner_reaction", side_effect=trade_approval.IssueNotFound("gone")):
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=MagicMock(),
            drawdown_breaker=MagicMock(), github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 0.0, 3: 0.0}, open_positions={},
            data_client=MagicMock(),
        )
    assert pending_trades == {}


def test_process_pending_trades_one_symbols_api_failure_does_not_block_others():
    pending_trades = {
        "AAPL": {
            "issue_number": 10, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-08",
        },
        "SERV": {
            "issue_number": 11, "side": "buy", "qty": 20.0, "price_at_proposal": 40.0,
            "stop_price": 38.0, "target_price": 44.0, "tier": 3, "proposed_date": "2024-01-08",
        },
    }

    def fake_get_owner_reaction(issue_number, *args, **kwargs):
        if issue_number == 10:
            raise RuntimeError("transient GitHub API error")
        return "rejected"

    with patch("live_loop.trade_approval.get_owner_reaction", side_effect=fake_get_owner_reaction), \
         patch("live_loop.trade_approval.close_issue") as mock_close:
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=MagicMock(),
            drawdown_breaker=MagicMock(), github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 0.0, 3: 0.0}, open_positions={},
            data_client=MagicMock(),
        )
    assert "AAPL" in pending_trades  # its own error left it untouched, retried next cycle
    assert "SERV" not in pending_trades  # rejected and closed despite AAPL's error
    mock_close.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -v -k "process_pending_trades"`
Expected: FAIL — `ImportError: cannot import name 'process_pending_trades' from 'live_loop'`.

- [ ] **Step 3: Implement `process_pending_trades`**

Add this function to `live_loop.py`, after `run_tier1_rebalance` and before `main()`:

```python
PRICE_STALENESS_TOLERANCE = 0.02


def process_pending_trades(pending_trades, today, trading_client, drawdown_breaker,
                            github_token, repo, owner_username, tier_pools, open_positions,
                            data_client, cycle_trades=None, symbol_statuses=None, session=requests):
    """Resolves every open trade-approval proposal once per cycle: expires a
    stale (not-today) proposal, closes a rejected one, executes an approved
    one only after re-validating price/drawdown/position-not-already-open
    against fresh current state (time has passed since the proposal was
    created). One symbol's API failure must not block resolving the others
    this cycle -- same fail-isolation convention as the WATCHLIST loop in
    main().
    """
    if cycle_trades is None:
        cycle_trades = []
    if symbol_statuses is None:
        symbol_statuses = {}

    for symbol in list(pending_trades.keys()):
        trade = pending_trades[symbol]
        try:
            if trade["proposed_date"] != today.isoformat():
                trade_approval.close_issue(
                    trade["issue_number"], "expired -- no decision by end of trading day.",
                    github_token, repo, session=session,
                )
                del pending_trades[symbol]
                continue

            try:
                decision = trade_approval.get_owner_reaction(
                    trade["issue_number"], owner_username, github_token, repo, session=session,
                )
            except trade_approval.IssueNotFound:
                del pending_trades[symbol]
                continue

            if decision == "rejected":
                trade_approval.close_issue(
                    trade["issue_number"], "rejected.", github_token, repo, session=session,
                )
                del pending_trades[symbol]
                continue

            if decision != "approved":
                continue  # still waiting, leave it open

            now = datetime.now(ET)
            bars = fetch_bars(data_client, symbol, now - SIGNAL_LOOKBACK, now)
            if not bars:
                continue  # can't re-validate without a current price -- try again next cycle
            current_price = bars[-1].close
            price_drift = abs(current_price - trade["price_at_proposal"]) / trade["price_at_proposal"]

            failure_reason = None
            if price_drift > PRICE_STALENESS_TOLERANCE:
                failure_reason = (
                    f"price moved {price_drift:.1%} since proposal, "
                    f"exceeding {PRICE_STALENESS_TOLERANCE:.0%} tolerance"
                )
            elif not drawdown_breaker.can_open_new_trade():
                failure_reason = "drawdown breaker no longer allows new trades"
            elif symbol in open_positions:
                failure_reason = "position already opened since this proposal was made"

            if failure_reason is not None:
                trade_approval.close_issue(
                    trade["issue_number"], f"not executed: {failure_reason}.", github_token, repo, session=session,
                )
                del pending_trades[symbol]
                continue

            order = MarketOrderRequest(
                symbol=symbol, qty=trade["qty"], side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
            )
            trading_client.submit_order(order)
            tier_pools[trade["tier"]] -= trade["qty"] * current_price
            if trade["tier"] != 1:
                open_positions[symbol] = {
                    "entry_price": current_price, "shares": trade["qty"],
                    "stop": trade["stop_price"], "target": trade["target_price"],
                    "opened_date": today.isoformat(),
                }
                symbol_statuses[symbol] = {
                    "position_open": True, "shares": trade["qty"], "entry_price": current_price,
                    "current_price": current_price, "action": "buy", "reason": "approved via GitHub issue",
                }
            cycle_trades.append({
                "timestamp": now.isoformat(), "symbol": symbol, "side": "buy",
                "qty": trade["qty"], "price": current_price, "reason": "approved via GitHub issue",
            })
            trade_approval.close_issue(
                trade["issue_number"],
                f"approved and executed: bought {trade['qty']} shares at ~{current_price}.",
                github_token, repo, session=session,
            )
            del pending_trades[symbol]
            print(f"{symbol}: executed approved buy for {trade['qty']} shares")
        except Exception as exc:
            print(f"{symbol}: error resolving pending trade, will retry next cycle: {exc}", file=sys.stderr)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -v -k "process_pending_trades"`
Expected: PASS.

- [ ] **Step 5: Wire it into `main()`**

In `live_loop.py`'s `main()`, add the import of `load_pending_trades`/`save_pending_trades` to
the existing `from graywind_strategy.state_store import (...)` block:

```python
from graywind_strategy.state_store import (
    load_state, save_state, load_tier_pools, save_tier_pools,
    load_rebalance_state, save_rebalance_state,
    load_pending_trades, save_pending_trades,
)
```

Right after `state_dir = os.environ.get("GRAYWIND_STATE_DIR", "state")` (added by the
dual-account plan's Task 3), add:

```python
    github_token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    owner_username = repo.split("/")[0] if repo else ""
    account_label = "small" if state_dir == "state/small" else "100k"
```

Right after `state = load_state(state_dir=state_dir)`, add:

```python
    pending_trades = load_pending_trades(state_dir=state_dir)
```

Right after `open_positions = reconcile_positions(trading_client, open_positions)` (and before
the existing `drawdown_breaker = DrawdownBreaker(...)` line), the function still needs
`drawdown_breaker`/`equity` to exist before `process_pending_trades` can run — those aren't
computed until inside the `try:` block below. Add the call **inside** the existing `try:`
block, immediately after `drawdown_breaker.update_equity(equity)`:

```python
        process_pending_trades(
            pending_trades, today, trading_client, drawdown_breaker, github_token, repo,
            owner_username, tier_pools, open_positions, data_client,
            cycle_trades=cycle_trades, symbol_statuses=symbol_statuses,
        )
```

Update the `run_tier1_rebalance` call site (still inside that same `try:` block) to thread the
new params through:

```python
        if should_rebalance_this_month(rebalance_state["last_rebalance_month"], today):
            try:
                run_tier1_rebalance(
                    trading_client, data_client, tier_pools, pending_trades=pending_trades,
                    github_token=github_token, repo=repo, account_label=account_label, today=today,
                )
                rebalance_state["last_rebalance_month"] = today.strftime("%Y-%m")
            except Exception as exc:
                print(f"tier1 rebalance: error, will retry next cycle: {exc}", file=sys.stderr)
```

Update the `process_symbol(...)` call inside the `for symbol in WATCHLIST:` loop to thread the
new params through:

```python
                process_symbol(
                    symbol=symbol, signal=latest["signal"], current_price=latest["close"],
                    today=today, open_positions=open_positions, equity=equity,
                    pdt_throttle=pdt_throttle, position_sizer=position_sizer,
                    drawdown_breaker_ok=drawdown_breaker.can_open_new_trade(),
                    fred_api_key=fred_api_key, news_client=news_client,
                    finnhub_api_key=finnhub_api_key, trading_client=trading_client,
                    drawdown_breaker=drawdown_breaker,
                    cycle_timestamp=cycle_timestamp, cycle_trades=cycle_trades,
                    symbol_statuses=symbol_statuses, tier_pools=tier_pools,
                    pending_trades=pending_trades, github_token=github_token, repo=repo,
                    account_label=account_label,
                )
```

Finally, in the `finally:` block, add the save call alongside the existing three:

```python
        save_state({...}, state_dir=state_dir)  # unchanged
        save_tier_pools(tier_pools, state_dir=state_dir)  # unchanged
        save_rebalance_state(rebalance_state, state_dir=state_dir)  # unchanged
        save_pending_trades(pending_trades, state_dir=state_dir)
```

- [ ] **Step 6: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS. `main()` itself is not unit-tested (real network/Alpaca calls) — this
project's standing "integration validation via a real run" discipline, same as every prior
`main()`-touching task in this codebase's history.

- [ ] **Step 7: Commit**

```bash
git add live_loop.py tests/test_live_loop.py
git commit -m "feat: resolve pending trade-approval proposals every cycle"
```

---

## Task 6: Thread `GITHUB_TOKEN` into both workflow jobs

**Files:**
- Modify: `.github/workflows/live-trading.yml`

**Interfaces:**
- Produces: both `live-cycle` and `live-cycle-small` jobs' `env:` blocks include
  `GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}`. `GITHUB_REPOSITORY` needs no wiring — GitHub
  Actions sets it automatically as an environment variable in every job's process environment,
  no `env:` entry required.

No test framework covers this file — validate syntactically, verify behaviorally post-merge
via a manual `workflow_dispatch` run, matching this project's existing precedent for workflow
changes (see the dual-account plan's Task 4).

- [ ] **Step 1: Add `GITHUB_TOKEN` to the `live-cycle` job's env block**

In `.github/workflows/live-trading.yml`, find the existing `live-cycle` job's
`Run the live trading cycle` step and add one line to its `env:` block:

```yaml
      - name: Run the live trading cycle
        env:
          ALPACA_API_KEY: ${{ secrets.ALPACA_API_KEY }}
          ALPACA_API_SECRET: ${{ secrets.ALPACA_API_SECRET }}
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
          FINNHUB_API_KEY: ${{ secrets.FINNHUB_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: python3 live_loop.py
```

- [ ] **Step 2: Add `GITHUB_TOKEN` to the `live-cycle-small` job's env block**

Same change to the `live-cycle-small` job (added by the dual-account plan's Task 4):

```yaml
      - name: Run the live trading cycle
        env:
          ALPACA_API_KEY: ${{ secrets.ALPACA_API_KEY_SMALL }}
          ALPACA_API_SECRET: ${{ secrets.ALPACA_API_SECRET_SMALL }}
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
          FINNHUB_API_KEY: ${{ secrets.FINNHUB_API_KEY }}
          GRAYWIND_STATE_DIR: state/small
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: python3 live_loop.py
```

- [ ] **Step 3: Validate YAML syntax**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/live-trading.yml'))"`
Expected: no output, exit code 0.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/live-trading.yml
git commit -m "feat: pass GITHUB_TOKEN to live_loop.py for trade-approval issues"
```

- [ ] **Step 5: Manual verification note (not automatable here)**

After merge, trigger a `workflow_dispatch` run during market hours with conditions likely to
signal a buy. Confirm: a GitHub issue actually opens with the `pending-trade` label and
correct reasoning; reacting 👍 on it as the repo owner causes the *next* scheduled cycle to
execute the trade and close the issue with a confirmation comment; reacting 👍 as a different
account is ignored (ask a friend, or a throwaway second account, to react and confirm nothing
executes). Leave this step unchecked until that manual verification has actually happened.

---

## Self-review notes (for the plan author, already applied above)

- **Spec coverage:** proposal creation ✓ (Tasks 3/4), owner-only reaction filtering ✓ (Task
  2), same-day expiry ✓ (Task 5), price/drawdown/already-open re-validation ✓ (Task 5),
  duplicate-proposal suppression ✓ (Tasks 3/4), sells stay automatic ✓ (untouched in Tasks
  3/4, confirmed by Task 4's new sell regression test), `GITHUB_TOKEN` wiring ✓ (Task 6). No
  spec section without a task.
- **Type consistency:** `pending_trades` row shape (`issue_number, side, qty,
  price_at_proposal, stop_price, target_price, tier, proposed_date`) is identical across
  Task 1's persistence layer, Tasks 3/4's proposal creation, and Task 5's resolution — checked
  field-by-field against each task's code.
- **No placeholders:** every step above contains complete, runnable code — no TBD/TODO.
- **Gap the spec's prose didn't cover, resolved here:** `stop_price`/`target_price` threading
  and tier-1-vs-tier-2/3 branching in `open_positions` handling (see Global Constraints) —
  without this, an approved tier-2/3 buy would execute with `stop`/`target` set to `None`,
  crashing `process_symbol`'s very next stop/target-exit comparison
  (`current_price <= position["stop"]`) with a `TypeError`.
