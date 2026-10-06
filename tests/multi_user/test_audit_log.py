"""Focused unit tests for the multi-user audit log (``deeptutor/multi_user/audit.py``).

The audit module is a JSONL append-log under ``data/system/audit``. These
tests exercise the module directly — writing through :func:`log_usage`,
:func:`log_admin_action` and :func:`log_guardian_action`, then reading events
back from ``usage.jsonl`` and filtering them the way the admin consumers do —
with every path isolated under ``tmp_path`` by the shared ``mu_isolated_root``
fixture, so no real deployment data is ever touched.

Covered contracts:

* write → read-back roundtrip and field-based filtering;
* audit-field completeness: operator (user id/username, or actor
  id/username/role), action, object (resource_type/resource_id,
  target_user_id, guardian/learner ids) and a UTC timestamp on every event;
* admin self-access is intentionally not recorded by ``log_usage``;
* boundaries: empty/optional payload keys, very long and non-ASCII field
  values (a value containing a newline must still occupy exactly one JSONL
  line), concurrent appends from several threads (line integrity plus
  per-writer ordering), and a failing storage backend never raising into the
  caller ("auditing must never break a request").
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import threading

from deeptutor.multi_user.audit import (
    log_admin_action,
    log_guardian_action,
    log_usage,
)


def _audit_path(root: Path) -> Path:
    return root / "data" / "system" / "audit" / "usage.jsonl"


def _read_events(root: Path) -> list[dict]:
    path = _audit_path(root)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _assert_utc_timestamp(value: str) -> None:
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


# ---------------------------------------------------------------------------
# Write → query roundtrip and filtering
# ---------------------------------------------------------------------------


def test_log_usage_roundtrip_and_filters(mu_isolated_root, as_user):
    with as_user("u_alice", username="alice"):
        log_usage("book", "bk_1", "shared_edit", {"page": 3})
        log_usage("knowledge_base", "kb_1", "rag_query")
    with as_user("u_bob", username="bob"):
        log_usage("book", "bk_2", "page_chat")

    events = _read_events(mu_isolated_root)
    assert len(events) == 3

    alice_events = [e for e in events if e["user_id"] == "u_alice"]
    assert [e["resource_id"] for e in alice_events] == ["bk_1", "kb_1"]

    book_events = [e for e in events if e["resource_type"] == "book"]
    assert {e["user_id"] for e in book_events} == {"u_alice", "u_bob"}

    rag_queries = [e for e in events if e["action"] == "rag_query"]
    assert len(rag_queries) == 1
    assert rag_queries[0]["resource_id"] == "kb_1"
    assert "extra" not in rag_queries[0]


def test_log_usage_field_completeness(mu_isolated_root, as_user):
    with as_user("u_carol", username="carol"):
        log_usage("book", "bk_9", "page_chat", {"page_id": "p7"})

    (event,) = _read_events(mu_isolated_root)
    assert event["user_id"] == "u_carol"
    assert event["username"] == "carol"
    assert event["resource_type"] == "book"
    assert event["resource_id"] == "bk_9"
    assert event["action"] == "page_chat"
    assert event["extra"] == {"page_id": "p7"}
    _assert_utc_timestamp(event["time"])
    assert _audit_path(mu_isolated_root).is_relative_to(mu_isolated_root)


def test_log_usage_empty_extra_dict_omits_the_key(mu_isolated_root, as_user):
    with as_user("u_dave", username="dave"):
        log_usage("book", "bk_1", "shared_edit", {})

    (event,) = _read_events(mu_isolated_root)
    assert "extra" not in event


def test_log_usage_skips_admin_self_access(mu_isolated_root, as_user):
    with as_user("root", role="admin", username="root"):
        log_usage("book", "bk_admin", "shared_edit")

    assert not _audit_path(mu_isolated_root).exists()
    assert _read_events(mu_isolated_root) == []


def test_mixed_event_stream_supports_field_queries_and_appends_in_order(mu_isolated_root, as_user):
    with as_user("u_alice", username="alice"):
        log_usage("book", "bk_1", "page_chat")
    with as_user("root", role="admin", username="root"):
        log_admin_action("user_created", target_user_id="u_alice")
    with as_user("guardian1", username="guardian"):
        log_guardian_action("materials_assigned", "guardian1", "u_alice")

    events = _read_events(mu_isolated_root)
    assert [e["action"] for e in events] == [
        "page_chat",
        "user_created",
        "materials_assigned",
    ]

    by_action = {e["action"]: e for e in events}
    assert by_action["user_created"]["target_user_id"] == "u_alice"

    assert [e for e in events if "user_id" in e][0]["username"] == "alice"
    assert len([e for e in events if "actor_role" in e]) == 2
    guardian_event = by_action["materials_assigned"]
    assert guardian_event["guardian_user_id"] == "guardian1"
    assert guardian_event["learner_user_id"] == "u_alice"


# ---------------------------------------------------------------------------
# Admin and guardian events
# ---------------------------------------------------------------------------


def test_log_admin_action_records_actor_and_optional_keys(mu_isolated_root, as_user):
    with as_user("root", role="admin", username="root"):
        log_admin_action("user_created", target_user_id="u_new", summary={"role": "user"})
        log_admin_action("grants_updated")

    created, updated = _read_events(mu_isolated_root)

    assert created["actor_id"] == "root"
    assert created["actor_username"] == "root"
    assert created["actor_role"] == "admin"
    assert created["action"] == "user_created"
    assert created["target_user_id"] == "u_new"
    assert created["summary"] == {"role": "user"}
    _assert_utc_timestamp(created["time"])

    assert updated["action"] == "grants_updated"
    assert "target_user_id" not in updated
    assert "summary" not in updated
    _assert_utc_timestamp(updated["time"])


def test_log_guardian_action_records_actor_and_parties(mu_isolated_root, as_user):
    with as_user("guardian1", username="guardian"):
        log_guardian_action(
            "materials_assigned",
            "guardian1",
            "learner7",
            summary={"books": 2},
        )

    (event,) = _read_events(mu_isolated_root)
    assert event["actor_id"] == "guardian1"
    assert event["actor_username"] == "guardian"
    assert event["actor_role"] == "user"
    assert event["action"] == "materials_assigned"
    assert event["guardian_user_id"] == "guardian1"
    assert event["learner_user_id"] == "learner7"
    assert event["summary"] == {"books": 2}
    _assert_utc_timestamp(event["time"])


# ---------------------------------------------------------------------------
# Boundaries: overlong values, concurrency, storage failure
# ---------------------------------------------------------------------------


def test_overlong_and_multiline_values_stay_single_jsonl_lines(mu_isolated_root, as_user):
    long_id = "bk_" + "x" * 20000
    with as_user("u_alice", username="alice"):
        log_usage(
            "book",
            long_id,
            "shared_edit",
            {"note": "第一行\n第二行", "tags": ["阅读", "quiz"] * 50},
        )

    path = _audit_path(mu_isolated_root)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1

    (event,) = _read_events(mu_isolated_root)
    assert event["resource_id"] == long_id
    assert event["extra"]["note"] == "第一行\n第二行"
    assert len(event["extra"]["tags"]) == 100


def test_concurrent_writes_keep_line_integrity_and_per_writer_order(mu_isolated_root):
    from deeptutor.multi_user.context import set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope

    writers = 4
    per_writer = 25
    users = [
        CurrentUser(
            id=f"u_w{index}",
            username=f"w{index}",
            role="user",
            scope=UserScope(
                kind="user",
                user_id=f"u_w{index}",
                root=(mu_isolated_root / "data" / "users" / f"u_w{index}").resolve(),
            ),
        )
        for index in range(writers)
    ]
    errors: list[BaseException] = []

    def _write_events(user: CurrentUser, writer: int) -> None:
        set_current_user(user)
        try:
            for seq in range(per_writer):
                log_usage("book", f"bk_{writer}_{seq}", "page_chat", {"seq": seq})
        except BaseException as exc:  # surfaced after join, below
            errors.append(exc)

    threads = [
        threading.Thread(target=_write_events, args=(users[index], index))
        for index in range(writers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []

    events = _read_events(mu_isolated_root)
    assert len(events) == writers * per_writer

    for index in range(writers):
        seqs = [e["extra"]["seq"] for e in events if e["user_id"] == f"u_w{index}"]
        assert len(seqs) == per_writer
        assert seqs == sorted(seqs)


def test_audit_storage_failure_never_breaks_the_caller(mu_isolated_root, monkeypatch, as_user):
    from deeptutor.multi_user import paths as mu_paths

    def _broken_ensure() -> None:
        raise OSError("simulated storage outage")

    monkeypatch.setattr(mu_paths, "ensure_system_dirs", _broken_ensure)

    with as_user("u_alice", username="alice"):
        log_usage("book", "bk_1", "shared_edit")
        log_admin_action("grants_updated")
        log_guardian_action("materials_assigned", "g1", "l1")

    assert not _audit_path(mu_isolated_root).exists()
