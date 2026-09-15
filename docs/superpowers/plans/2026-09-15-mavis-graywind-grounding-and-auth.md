# MAVIS Graywind Grounding + Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend MAVIS's `/ask` endpoint so it can answer questions grounded in Graywind's own trading state (watchlist, latest per-symbol decisions, pending trade proposals) in addition to the existing Bullion financial-map grounding — and lock `/ask` down with an API key + rate limit before any of this becomes reachable from outside localhost.

**Architecture:** Mirror the existing Bullion grounding pattern exactly: a build-time extraction script snapshots Graywind's CSV state into a committed JSON file, and a retrieval module keyword-matches queries against that snapshot. No live CSV/account reads happen in the request path. `/ask` merges Bullion + Graywind grounding into one context string passed to Groq, and gains an `X-API-Key` dependency plus a per-key in-memory rate limiter.

**Tech Stack:** Python 3.14, FastAPI 0.141.1, pytest (new dev dependency), no new runtime dependencies.

**Spec:** No separate spec file — this plan's scope was set directly with the user in-session (2026-09-15): drop the original `mavis-cloud-avatar-plan_1.md` Fable-escalation architecture (superseded — see Global Constraints), fold Graywind's data into MAVIS's grounding now rather than later, and move auth ahead of the MCP wrapper in the build order because Graywind data is real-capital state, not public Bullion data.

## Global Constraints

- **No Fable 5.1 escalation tier.** The original plan's "cheap tier + Fable escalation" architecture doesn't work as designed — Fable credit is an in-app Claude Code/claude.ai product credit, not an Anthropic Console API credit backend code can call. Stay Groq-only (`providers.py` is unchanged by this plan).
- **Grounding is a build-time snapshot, never a live read.** Matches the existing `extract_bullion_grounding.js` → `data/bullion_grounding.json` → `grounding.py` pattern. `graywind_grounding.py` reads only `data/graywind_grounding.json`, never `state/*.csv` directly at request time.
- **`state/tier_pools.csv` and `state/small/tier_pools.csv` are excluded from Graywind grounding entirely**, on both accounts. As of 2026-09-15 the 100k account's pool balances are known-wrong (`docs/superpowers/graywind-critical-review-punch-list-execution-handoff.md`) — grounding an answer on a number that's silently broken is worse than grounding on nothing. Do not add tier-pool cash figures to the extraction script.
- **`/status` stays open, unauthenticated.** It returns no sensitive data (`{"ok": True, "provider": ...}`).
- **`/ask` requires `X-API-Key`, and fails closed if the server-side key isn't configured.** An unset `MAVIS_API_KEY` must reject every request with a 500, never silently allow all requests through — this is the exact "unset secret expands to empty string" failure mode flagged in the Graywind punch-list handoff (item 6c), don't reintroduce it here.
- **Rate limiting is in-memory and per-process.** Fine for a single-instance personal VPS deployment; do not build for multi-instance/horizontal scaling.
- **Out of scope for this plan:** the MCP wrapper and the Three.js avatar frontend (original plan's Nights 3–4). Those come in a separate plan once this one is live-verified — don't start them here even if there's time left in a session.
- **Test runner:** `cd mavis && .venv/bin/python -m pytest -q` (an empty `mavis/conftest.py`, added in Task 1, is what makes `import app`, `import auth`, etc. resolve from `mavis/tests/*.py` — mirrors the repo root's own empty `conftest.py`).

---

## Task 1: Graywind grounding extraction script

**Files:**
- Create: `mavis/scripts/extract_graywind_grounding.py`
- Create: `mavis/conftest.py` (empty — enables `mavis/` on `sys.path` for all test files below)
- Create: `mavis/requirements-dev.txt`
- Test: `mavis/tests/test_extract_graywind_grounding.py`

**Interfaces:**
- Produces: `latest_decision_per_symbol(csv_path: Path) -> dict[str, dict]`, `read_pending_trades(csv_path: Path) -> list[dict]`, `extract_watchlist(live_loop_path: Path) -> list[str]`, `build_facts(accounts_data: list[tuple[str, dict, list[dict]]], watchlist: list[str]) -> list[dict]` — each fact dict has keys `id`, `tags` (list[str]), `text` (str). Task 2 imports the JSON these produce, not these functions directly.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Add pytest as a dev dependency**

Create `mavis/requirements-dev.txt`:

```
pytest==9.1.1
```

Run: `cd mavis && .venv/bin/pip install -r requirements-dev.txt`

- [ ] **Step 2: Create the empty conftest.py**

Create `mavis/conftest.py` with no content (0 bytes) — its presence at `mavis/` makes pytest add `mavis/` to `sys.path` when tests run from there, exactly like the repo root's own empty `conftest.py` does for `tests/*.py`.

- [ ] **Step 3: Write the failing tests**

Create `mavis/tests/test_extract_graywind_grounding.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from extract_graywind_grounding import (
    build_facts,
    extract_watchlist,
    latest_decision_per_symbol,
    read_pending_trades,
)

DECISION_HEADER = (
    "timestamp,symbol,action,reason,rsi,sma_fast,sma_slow,vix,sentiment,"
    "days_to_earnings,macro_breaches,sector_gates\n"
)
PENDING_HEADER = (
    "symbol,issue_number,side,qty,price_at_proposal,stop_price,"
    "target_price,tier,proposed_date\n"
)


def write_csv(path, header, rows):
    path.write_text(header + "\n".join(rows) + ("\n" if rows else ""))


def test_latest_decision_per_symbol_keeps_last_row_per_symbol(tmp_path):
    path = tmp_path / "decision_log.csv"
    write_csv(path, DECISION_HEADER, [
        "2026-09-14T10:00:00-04:00,AAPL,hold,no buy signal,50,330,331,,,,,",
        "2026-09-14T11:00:00-04:00,AAPL,buy,all checks passed,52,331,330,15.8,0.02,none,0,[]",
        "2026-09-14T11:00:00-04:00,SERV,hold,position size rounds to zero shares,48,4.4,4.43,15.8,0.0,none,0,[]",
    ])

    latest = latest_decision_per_symbol(path)

    assert set(latest.keys()) == {"AAPL", "SERV"}
    assert latest["AAPL"]["action"] == "buy"
    assert latest["AAPL"]["reason"] == "all checks passed"


def test_read_pending_trades_returns_empty_list_when_file_missing(tmp_path):
    assert read_pending_trades(tmp_path / "does_not_exist.csv") == []


def test_read_pending_trades_parses_rows(tmp_path):
    path = tmp_path / "pending_trades.csv"
    write_csv(path, PENDING_HEADER, [
        "AAPL,13,buy,78.7532,332.835,326.18,342.82,2,2026-09-14",
    ])

    rows = read_pending_trades(path)

    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["issue_number"] == "13"


def test_extract_watchlist_parses_the_assignment(tmp_path):
    path = tmp_path / "live_loop.py"
    path.write_text('SOME_OTHER = 1\nWATCHLIST = ["AAPL", "SERV"]\nMORE = 2\n')

    assert extract_watchlist(path) == ["AAPL", "SERV"]


def test_extract_watchlist_raises_when_missing(tmp_path):
    path = tmp_path / "live_loop.py"
    path.write_text("NOT_HERE = 1\n")

    try:
        extract_watchlist(path)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_build_facts_includes_watchlist_decisions_and_pending():
    latest_decisions = {
        "AAPL": {
            "action": "buy",
            "reason": "all checks passed",
            "timestamp": "2026-09-14T11:00:00-04:00",
        },
    }
    pending_trades = [
        {
            "symbol": "AAPL", "issue_number": "13", "side": "buy",
            "qty": "78.7532", "tier": "2", "proposed_date": "2026-09-14",
        },
    ]

    facts = build_facts([("100k", latest_decisions, pending_trades)], ["AAPL", "SERV"])

    ids = {f["id"] for f in facts}
    assert "watchlist" in ids
    assert "decision-100k-AAPL" in ids
    assert "pending-100k-13" in ids

    decision_fact = next(f for f in facts if f["id"] == "decision-100k-AAPL")
    assert "buy" in decision_fact["text"]
    assert "all checks passed" in decision_fact["text"]

    pending_fact = next(f for f in facts if f["id"] == "pending-100k-13")
    assert "78.7532" in pending_fact["text"]
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd mavis && .venv/bin/python -m pytest tests/test_extract_graywind_grounding.py -v`
Expected: FAIL/ERROR with `ModuleNotFoundError: No module named 'extract_graywind_grounding'`

- [ ] **Step 5: Write the extraction script**

Create `mavis/scripts/extract_graywind_grounding.py`:

```python
#!/usr/bin/env python3
"""Builds mavis/data/graywind_grounding.json from Graywind's own state
files, mirroring extract_bullion_grounding.js's build-time-snapshot
pattern -- no live account reads happen at request time. Excludes
state/tier_pools.csv on both accounts: as of 2026-09-15 the 100k
account's pool balances are known-wrong (see
docs/superpowers/graywind-critical-review-punch-list-execution-handoff.md),
and grounding an answer on a number that's silently broken is worse
than grounding on nothing.

Run with: python3 scripts/extract_graywind_grounding.py
"""
import ast
import csv
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "graywind_grounding.json"

ACCOUNTS = [
    ("100k", REPO_ROOT / "state"),
    ("small", REPO_ROOT / "state" / "small"),
]


def latest_decision_per_symbol(csv_path):
    """Returns {symbol: row_dict} for the last logged decision per symbol.

    decision_log.csv is append-only in timestamp order, so the last row
    seen for a symbol is its most recent decision.
    """
    latest = {}
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            latest[row["symbol"]] = row
    return latest


def read_pending_trades(csv_path):
    if not csv_path.exists():
        return []
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def extract_watchlist(live_loop_path):
    text = live_loop_path.read_text()
    match = re.search(r"^WATCHLIST\s*=\s*(\[.*\])", text, re.MULTILINE)
    if not match:
        raise ValueError(f"WATCHLIST assignment not found in {live_loop_path}")
    return ast.literal_eval(match.group(1))


def build_facts(accounts_data, watchlist):
    facts = [{
        "id": "watchlist",
        "tags": ["watchlist", "graywind"] + [s.lower() for s in watchlist],
        "text": f"Graywind's active trading watchlist is {', '.join(watchlist)}.",
    }]

    for account_name, latest_decisions, pending_trades in accounts_data:
        for symbol, row in sorted(latest_decisions.items()):
            facts.append({
                "id": f"decision-{account_name}-{symbol}",
                "tags": ["decision", "graywind", account_name.lower(), symbol.lower()],
                "text": (
                    f"[Graywind, {account_name} account] Most recent decision "
                    f"for {symbol}: {row['action']} — \"{row['reason']}\" "
                    f"(as of {row['timestamp']})."
                ),
            })

        for row in pending_trades:
            facts.append({
                "id": f"pending-{account_name}-{row['issue_number']}",
                "tags": ["pending", "graywind", account_name.lower(), row["symbol"].lower()],
                "text": (
                    f"[Graywind, {account_name} account] Pending trade proposal: "
                    f"{row['side']} {float(row['qty']):.4f} shares of {row['symbol']} "
                    f"(tier {row['tier']}), proposed {row['proposed_date']}, "
                    f"GitHub issue #{row['issue_number']} — awaiting manual approval."
                ),
            })

    return facts


def main():
    accounts_data = []
    for account_name, state_dir in ACCOUNTS:
        latest_decisions = latest_decision_per_symbol(state_dir / "decision_log.csv")
        pending_trades = read_pending_trades(state_dir / "pending_trades.csv")
        accounts_data.append((account_name, latest_decisions, pending_trades))

    watchlist = extract_watchlist(REPO_ROOT / "live_loop.py")
    facts = build_facts(accounts_data, watchlist)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({"facts": facts}, indent=2) + "\n")
    print(f"wrote {len(facts)} facts to {OUT_PATH}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd mavis && .venv/bin/python -m pytest tests/test_extract_graywind_grounding.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Generate the real snapshot and commit it**

Run: `cd mavis && .venv/bin/python scripts/extract_graywind_grounding.py`
Expected output: `wrote N facts to .../mavis/data/graywind_grounding.json` — inspect the file, confirm it has a `watchlist` fact plus `decision-*`/`pending-*` facts for both accounts and no tier-pool cash figures anywhere in it.

- [ ] **Step 8: Commit**

```bash
git add mavis/conftest.py mavis/requirements-dev.txt mavis/scripts/extract_graywind_grounding.py mavis/tests/test_extract_graywind_grounding.py mavis/data/graywind_grounding.json
git commit -m "feat(mavis): extract Graywind decision/pending/watchlist grounding snapshot"
```

---

## Task 2: Graywind grounding retrieval + merge into /ask

**Files:**
- Create: `mavis/graywind_grounding.py`
- Modify: `mavis/app.py`
- Test: `mavis/tests/test_graywind_grounding.py`
- Test: `mavis/tests/test_app.py` (new file — first test coverage for `app.py`)

**Interfaces:**
- Consumes: `mavis/data/graywind_grounding.json` (Task 1's output — must exist on disk before this module is imported).
- Produces: `graywind_grounding.retrieve(query: str, top_k: int = 5) -> list[dict]` (each hit: `{"type": "graywind_fact", "id": str, "text": str}`), `graywind_grounding.format_context(hits: list[dict]) -> str | None`. `app.py`'s `/ask` response `citations` field is now `bullion_hits + graywind_hits` (a flat list mixing `grounding.py`'s node/link hit shapes with `graywind_grounding.py`'s `graywind_fact` shape).

- [ ] **Step 1: Write the failing test for the retrieval module**

Create `mavis/tests/test_graywind_grounding.py`:

```python
import graywind_grounding


def test_retrieve_matches_watchlist_query():
    hits = graywind_grounding.retrieve("what is graywind's watchlist")

    assert any(h["id"] == "watchlist" for h in hits)


def test_retrieve_returns_empty_for_unrelated_query():
    hits = graywind_grounding.retrieve("!!! ??? ...")

    assert hits == []


def test_format_context_returns_none_for_no_hits():
    assert graywind_grounding.format_context([]) is None


def test_format_context_includes_hit_text():
    hits = [{"type": "graywind_fact", "id": "watchlist", "text": "Graywind's active trading watchlist is AAPL, SERV."}]

    context = graywind_grounding.format_context(hits)

    assert "AAPL, SERV" in context
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd mavis && .venv/bin/python -m pytest tests/test_graywind_grounding.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'graywind_grounding'`

- [ ] **Step 3: Write the retrieval module**

Create `mavis/graywind_grounding.py`:

```python
import json
import os

_GROUNDING_PATH = os.path.join(os.path.dirname(__file__), "data", "graywind_grounding.json")

with open(_GROUNDING_PATH) as f:
    _FACTS = json.load(f)["facts"]

MIN_SCORE = 1

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "and", "or",
    "in", "on", "for", "with", "what", "why", "how", "does", "do", "did",
    "it", "this", "that", "explain", "tell", "me", "about",
}


def _tokenize(text):
    words = "".join(c.lower() if c.isalnum() else " " for c in text).split()
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


def retrieve(query, top_k=5):
    """Keyword-match the query against Graywind's own decision/pending/
    watchlist facts (built at snapshot time by
    scripts/extract_graywind_grounding.py -- no live account read
    happens here or at request time).
    """
    q_tokens = _tokenize(query)
    if not q_tokens:
        return []

    scored = []
    for fact in _FACTS:
        haystack_tokens = set(fact["tags"]) | _tokenize(fact["text"])
        score = len(q_tokens & haystack_tokens)
        if score >= MIN_SCORE:
            scored.append((score, {
                "type": "graywind_fact",
                "id": fact["id"],
                "text": fact["text"],
            }))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for score, item in scored[:top_k]]


def format_context(hits):
    if not hits:
        return None
    lines = [
        "Live-ish state from your own Graywind trading bot (snapshot, may "
        "be stale by up to a build cycle -- not a live account read):"
    ]
    for h in hits:
        lines.append(f"- {h['text']}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd mavis && .venv/bin/python -m pytest tests/test_graywind_grounding.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Write the failing test for the /ask merge**

Create `mavis/tests/test_app.py`:

```python
import pytest
from fastapi.testclient import TestClient

import app as app_module


@pytest.fixture
def client():
    return TestClient(app_module.app)


async def _fake_groq_answer(query, context=None):
    return {"query": query, "context": context}


def test_ask_merges_bullion_and_graywind_citations(client, monkeypatch):
    async def fake_groq_answer(query, context=None):
        fake_groq_answer.seen_context = context
        return "fake answer"

    monkeypatch.setattr(app_module, "groq_answer", fake_groq_answer)

    resp = client.post("/ask", json={"query": "what is graywind's watchlist"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "fake answer"
    assert any(c.get("id") == "watchlist" for c in body["citations"])
    assert "Graywind trading bot" in fake_groq_answer.seen_context
```

(This test intentionally does not send `X-API-Key` — Task 3 will make it fail with 401 and it gets updated there. For now it verifies the merge logic works when auth doesn't exist yet.)

- [ ] **Step 6: Run test to verify it fails**

Run: `cd mavis && .venv/bin/python -m pytest tests/test_app.py -v`
Expected: FAIL — `citations` only contains Bullion-shaped hits (no `id` key on Bullion node hits either, so `any(...)` is `False`), or `graywind_grounding` isn't imported yet.

- [ ] **Step 7: Wire the merge into app.py**

Modify `mavis/app.py` to:

```python
from fastapi import FastAPI
from pydantic import BaseModel

import grounding
import graywind_grounding
from providers import GROQ_MODEL, groq_answer

app = FastAPI()


class AskRequest(BaseModel):
    query: str


@app.get("/status")
def status():
    return {"ok": True, "provider": GROQ_MODEL}


@app.post("/ask")
async def ask(req: AskRequest):
    bullion_hits = grounding.retrieve(req.query)
    graywind_hits = graywind_grounding.retrieve(req.query)

    context = "\n\n".join(filter(None, [
        grounding.format_context(bullion_hits),
        graywind_grounding.format_context(graywind_hits),
    ])) or None

    answer = await groq_answer(req.query, context)

    return {
        "answer": answer,
        "citations": bullion_hits + graywind_hits,
    }
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd mavis && .venv/bin/python -m pytest tests/test_app.py -v`
Expected: PASS

- [ ] **Step 9: Run the full mavis suite**

Run: `cd mavis && .venv/bin/python -m pytest -q`
Expected: all tests pass (10 total from Tasks 1-2)

- [ ] **Step 10: Commit**

```bash
git add mavis/graywind_grounding.py mavis/app.py mavis/tests/test_graywind_grounding.py mavis/tests/test_app.py
git commit -m "feat(mavis): merge Graywind grounding into /ask alongside Bullion"
```

---

## Task 3: API key auth on /ask

**Files:**
- Create: `mavis/auth.py`
- Modify: `mavis/app.py`
- Modify: `mavis/tests/test_app.py` (add `X-API-Key` header to the Task 2 test, which currently sends none)
- Test: `mavis/tests/test_auth.py`

**Interfaces:**
- Produces: `auth.require_api_key(x_api_key: str | None = Header(default=None)) -> str` — a FastAPI dependency; raises `HTTPException(500, ...)` if `auth.MAVIS_API_KEY` is falsy, `HTTPException(401, ...)` if the header doesn't match, else returns the key string. Task 4's rate limiter is keyed by this return value.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing tests**

Create `mavis/tests/test_auth.py`:

```python
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import auth


def make_app():
    app = FastAPI()

    @app.get("/protected")
    def protected(api_key: str = Depends(auth.require_api_key)):
        return {"ok": True}

    return app


def test_missing_key_is_rejected(monkeypatch):
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")
    client = TestClient(make_app())

    resp = client.get("/protected")

    assert resp.status_code == 401


def test_wrong_key_is_rejected(monkeypatch):
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")
    client = TestClient(make_app())

    resp = client.get("/protected", headers={"X-API-Key": "wrong"})

    assert resp.status_code == 401


def test_correct_key_is_accepted(monkeypatch):
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")
    client = TestClient(make_app())

    resp = client.get("/protected", headers={"X-API-Key": "secret123"})

    assert resp.status_code == 200


def test_unset_server_key_fails_closed(monkeypatch):
    monkeypatch.setattr(auth, "MAVIS_API_KEY", None)
    client = TestClient(make_app())

    resp = client.get("/protected", headers={"X-API-Key": "anything"})

    assert resp.status_code == 500
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd mavis && .venv/bin/python -m pytest tests/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'auth'`

- [ ] **Step 3: Write auth.py**

Create `mavis/auth.py`:

```python
import os

from fastapi import Header, HTTPException

MAVIS_API_KEY = os.environ.get("MAVIS_API_KEY")


def require_api_key(x_api_key: str = Header(default=None)):
    if not MAVIS_API_KEY:
        raise HTTPException(500, "MAVIS_API_KEY not set on the server")
    if x_api_key != MAVIS_API_KEY:
        raise HTTPException(401, "invalid or missing X-API-Key header")
    return x_api_key
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd mavis && .venv/bin/python -m pytest tests/test_auth.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Wire auth into /ask**

Modify `mavis/app.py`'s `/ask` route:

```python
from fastapi import Depends, FastAPI
from pydantic import BaseModel

import auth
import grounding
import graywind_grounding
from providers import GROQ_MODEL, groq_answer

app = FastAPI()


class AskRequest(BaseModel):
    query: str


@app.get("/status")
def status():
    return {"ok": True, "provider": GROQ_MODEL}


@app.post("/ask")
async def ask(req: AskRequest, api_key: str = Depends(auth.require_api_key)):
    bullion_hits = grounding.retrieve(req.query)
    graywind_hits = graywind_grounding.retrieve(req.query)

    context = "\n\n".join(filter(None, [
        grounding.format_context(bullion_hits),
        graywind_grounding.format_context(graywind_hits),
    ])) or None

    answer = await groq_answer(req.query, context)

    return {
        "answer": answer,
        "citations": bullion_hits + graywind_hits,
    }
```

- [ ] **Step 6: Update Task 2's /ask test to authenticate, and cover the 401 case**

Modify `mavis/tests/test_app.py` to match:

```python
import pytest
from fastapi.testclient import TestClient

import app as app_module
import auth


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")


@pytest.fixture
def client():
    return TestClient(app_module.app)


def test_status_is_open_without_auth(client):
    resp = client.get("/status")

    assert resp.status_code == 200


def test_ask_without_api_key_is_rejected(client):
    resp = client.post("/ask", json={"query": "what is graywind's watchlist"})

    assert resp.status_code == 401


def test_ask_merges_bullion_and_graywind_citations(client, monkeypatch):
    async def fake_groq_answer(query, context=None):
        fake_groq_answer.seen_context = context
        return "fake answer"

    monkeypatch.setattr(app_module, "groq_answer", fake_groq_answer)

    resp = client.post(
        "/ask",
        json={"query": "what is graywind's watchlist"},
        headers={"X-API-Key": "secret123"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "fake answer"
    assert any(c.get("id") == "watchlist" for c in body["citations"])
    assert "Graywind trading bot" in fake_groq_answer.seen_context
```

- [ ] **Step 7: Run the full mavis suite**

Run: `cd mavis && .venv/bin/python -m pytest -q`
Expected: all tests pass (17 total from Tasks 1-3)

- [ ] **Step 8: Commit**

```bash
git add mavis/auth.py mavis/app.py mavis/tests/test_auth.py mavis/tests/test_app.py
git commit -m "feat(mavis): require X-API-Key on /ask, fail closed if unset"
```

---

## Task 4: Rate limiting on /ask

**Files:**
- Create: `mavis/rate_limit.py`
- Modify: `mavis/app.py`
- Modify: `mavis/tests/test_app.py` (add one rate-limit test)
- Test: `mavis/tests/test_rate_limit.py`

**Interfaces:**
- Consumes: `auth.require_api_key`'s return value (the API key string) as the rate-limit key — `/ask` calls `check_rate_limit(api_key)` using the key `Depends(auth.require_api_key)` already resolved.
- Produces: `rate_limit.check_rate_limit(key: str) -> None` — raises `HTTPException(429, ...)` when the key has exceeded `rate_limit.MAX_REQUESTS_PER_WINDOW` calls in the trailing `rate_limit.WINDOW_SECONDS`; otherwise returns `None` and records the call.

- [ ] **Step 1: Write the failing tests**

Create `mavis/tests/test_rate_limit.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd mavis && .venv/bin/python -m pytest tests/test_rate_limit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rate_limit'`

- [ ] **Step 3: Write rate_limit.py**

Create `mavis/rate_limit.py`:

```python
import os
import time
from collections import defaultdict

from fastapi import HTTPException

WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = int(os.environ.get("MAVIS_RATE_LIMIT_PER_MINUTE", "20"))

_request_log = defaultdict(list)


def check_rate_limit(key):
    """Fixed-window limiter: at most MAX_REQUESTS_PER_WINDOW calls per key
    per WINDOW_SECONDS. In-memory and per-process -- fine for a single-VPS
    FastAPI instance, not for multiple workers/instances.
    """
    now = time.monotonic()
    window_start = now - WINDOW_SECONDS

    recent = [t for t in _request_log[key] if t > window_start]
    if len(recent) >= MAX_REQUESTS_PER_WINDOW:
        raise HTTPException(429, "rate limit exceeded, try again shortly")

    recent.append(now)
    _request_log[key] = recent
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd mavis && .venv/bin/python -m pytest tests/test_rate_limit.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Wire the rate limiter into /ask**

Modify `mavis/app.py`'s `/ask` route:

```python
from fastapi import Depends, FastAPI
from pydantic import BaseModel

import auth
import grounding
import graywind_grounding
from providers import GROQ_MODEL, groq_answer
from rate_limit import check_rate_limit

app = FastAPI()


class AskRequest(BaseModel):
    query: str


@app.get("/status")
def status():
    return {"ok": True, "provider": GROQ_MODEL}


@app.post("/ask")
async def ask(req: AskRequest, api_key: str = Depends(auth.require_api_key)):
    check_rate_limit(api_key)

    bullion_hits = grounding.retrieve(req.query)
    graywind_hits = graywind_grounding.retrieve(req.query)

    context = "\n\n".join(filter(None, [
        grounding.format_context(bullion_hits),
        graywind_grounding.format_context(graywind_hits),
    ])) or None

    answer = await groq_answer(req.query, context)

    return {
        "answer": answer,
        "citations": bullion_hits + graywind_hits,
    }
```

- [ ] **Step 6: Add the rate-limit test to test_app.py**

Add to `mavis/tests/test_app.py`:

```python
import rate_limit


@pytest.fixture(autouse=True)
def reset_rate_limit():
    rate_limit._request_log.clear()


def test_ask_is_rate_limited(client, monkeypatch):
    async def fake_groq_answer(query, context=None):
        return "fake answer"

    monkeypatch.setattr(app_module, "groq_answer", fake_groq_answer)
    monkeypatch.setattr(rate_limit, "MAX_REQUESTS_PER_WINDOW", 1)

    headers = {"X-API-Key": "secret123"}
    ok = client.post("/ask", json={"query": "hi"}, headers=headers)
    blocked = client.post("/ask", json={"query": "hi"}, headers=headers)

    assert ok.status_code == 200
    assert blocked.status_code == 429
```

- [ ] **Step 7: Run the full mavis suite**

Run: `cd mavis && .venv/bin/python -m pytest -q`
Expected: all tests pass (21 total from Tasks 1-4)

- [ ] **Step 8: Manual end-to-end smoke test**

```bash
cd mavis
export MAVIS_API_KEY=devkey123
export GROQ_API_KEY=<your real key>
.venv/bin/uvicorn app:app --reload &
curl -s http://127.0.0.1:8000/ask -X POST -H "Content-Type: application/json" -H "X-API-Key: devkey123" -d '{"query": "what is graywind watching right now"}' | python3 -m json.tool
curl -s http://127.0.0.1:8000/ask -X POST -H "Content-Type: application/json" -d '{"query": "hello"}'
```

Expected: first call returns 200 with an answer citing the `watchlist` fact; second call (no key) returns `{"detail":"invalid or missing X-API-Key header"}` with a 401. Stop the server (`kill %1`) when done.

- [ ] **Step 9: Commit**

```bash
git add mavis/rate_limit.py mavis/app.py mavis/tests/test_app.py
git commit -m "feat(mavis): add per-key rate limiting to /ask"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 covers Graywind data extraction (decisions, pending trades, watchlist; tier pools explicitly excluded per Global Constraints). Task 2 covers merging that into `/ask`'s context and citations. Task 3 covers the API-key requirement, including the fail-closed-on-unset-secret case. Task 4 covers rate limiting. The MCP wrapper and avatar frontend are explicitly out of scope (Global Constraints) — planned separately.
- **No placeholders:** every step has exact, complete code — no "add error handling" or "similar to Task N" shorthand.
- **Type/signature consistency checked:** `graywind_grounding.retrieve`/`format_context` signatures match how `app.py` calls them in every task from Task 2 onward; `auth.require_api_key`'s return value (`api_key: str`) is exactly what Task 4's `check_rate_limit(api_key)` consumes; `rate_limit.MAX_REQUESTS_PER_WINDOW` and `_request_log` are the two names both the module and its tests reference — kept identical throughout.
