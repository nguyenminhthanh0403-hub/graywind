import os

from graywind_strategy.manual_actions_log import (
    append_manual_action, has_idempotency_key, read_recent_manual_actions,
)


def test_append_creates_file_with_header_and_row(tmp_path):
    dashboard_dir = str(tmp_path)
    append_manual_action(dashboard_dir, {
        "timestamp": "2026-09-14T10:00:00-04:00", "symbol": "AAPL", "action": "close",
        "qty": "", "status": "submitted", "reason": "AAPL: sell order o-1 submitted",
        "idempotency_key": "key-1",
    })
    path = os.path.join(dashboard_dir, "manual_actions.csv")
    assert os.path.exists(path)
    rows = read_recent_manual_actions(dashboard_dir)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["idempotency_key"] == "key-1"


def test_append_is_additive_across_calls(tmp_path):
    dashboard_dir = str(tmp_path)
    for i in range(3):
        append_manual_action(dashboard_dir, {
            "timestamp": f"2026-09-14T10:0{i}:00-04:00", "symbol": "AAPL", "action": "close",
            "qty": "", "status": "submitted", "reason": "x", "idempotency_key": f"key-{i}",
        })
    rows = read_recent_manual_actions(dashboard_dir, limit=10)
    assert [r["idempotency_key"] for r in rows] == ["key-0", "key-1", "key-2"]


def test_read_recent_returns_empty_list_when_file_missing(tmp_path):
    assert read_recent_manual_actions(str(tmp_path)) == []


def test_read_recent_respects_limit(tmp_path):
    dashboard_dir = str(tmp_path)
    for i in range(5):
        append_manual_action(dashboard_dir, {
            "timestamp": f"2026-09-14T10:0{i}:00-04:00", "symbol": "AAPL", "action": "close",
            "qty": "", "status": "submitted", "reason": "x", "idempotency_key": f"key-{i}",
        })
    rows = read_recent_manual_actions(dashboard_dir, limit=2)
    assert [r["idempotency_key"] for r in rows] == ["key-3", "key-4"]


def test_has_idempotency_key_true_after_append(tmp_path):
    dashboard_dir = str(tmp_path)
    append_manual_action(dashboard_dir, {
        "timestamp": "t", "symbol": "AAPL", "action": "close", "qty": "",
        "status": "submitted", "reason": "x", "idempotency_key": "dup-key",
    })
    assert has_idempotency_key(dashboard_dir, "dup-key") is True
    assert has_idempotency_key(dashboard_dir, "never-seen") is False


def test_has_idempotency_key_false_when_file_missing(tmp_path):
    assert has_idempotency_key(str(tmp_path), "anything") is False
