"""Fixture-level measurement of the session SQLite store growth surface.

Offline and deterministic: builds throwaway stores under tempfile.mkdtemp(),
drives the real SQLiteSessionStore write/delete paths, and reports row counts,
byte volumes and PRAGMA counters as JSON. No server, no network, no real user
data. Evidence only — this script is not part of the test suite.

Reproduce:
    PYTHONPATH=<repo root> python evidence/session-sqlite-growth-20261011/measure_store_growth.py
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import time
from pathlib import Path

from deeptutor.services.session.sqlite_store import SQLiteSessionStore

EVENT_PAYLOAD = "x" * 512  # representative streamed delta size


def table_counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        tables = [
            "sessions",
            "messages",
            "turns",
            "turn_events",
            "turn_submissions",
            "notebook_entries",
            "assessment_attempts",
        ]
        out = {}
        for t in tables:
            out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # nosec B608
        return out
    finally:
        conn.close()


def pragma_facts(db_path: Path) -> dict[str, object]:
    conn = sqlite3.connect(db_path)
    try:
        return {
            "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
            "auto_vacuum": conn.execute("PRAGMA auto_vacuum").fetchone()[0],
            "page_count": conn.execute("PRAGMA page_count").fetchone()[0],
            "freelist_count": conn.execute("PRAGMA freelist_count").fetchone()[0],
            "page_size": conn.execute("PRAGMA page_size").fetchone()[0],
            "wal_autocheckpoint": conn.execute("PRAGMA wal_autocheckpoint").fetchone()[0],
        }
    finally:
        conn.close()


def submission_columns(db_path: Path) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        return [row[1] for row in conn.execute("PRAGMA table_info(turn_submissions)").fetchall()]
    finally:
        conn.close()


def dangling_message_parents(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            """
            SELECT COUNT(*) FROM messages m
            WHERE m.parent_message_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM messages p WHERE p.id = m.parent_message_id)
            """
        ).fetchone()[0]
    finally:
        conn.close()


def dangling_turn_links(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            """
            SELECT COUNT(*) FROM turns t
            WHERE t.assistant_message_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.id = t.assistant_message_id)
            """
        ).fetchone()[0]
    finally:
        conn.close()


def turn_events_bytes(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT COALESCE(SUM(LENGTH(content) + LENGTH(metadata_json)), 0) FROM turn_events"
        ).fetchone()[0]
    finally:
        conn.close()


async def scenario_resend_fail_loop(root: Path) -> dict[str, object]:
    """Each lost-ack resend of a failed turn adds one turn + its events;
    nothing prunes the superseded failed turns."""
    store = SQLiteSessionStore(root / "resend.db")
    session_id = await store.reserve_submission("sub-1", "digest")
    counts = {}
    for attempt in range(5):
        turn = await store.begin_turn(session_id, submission_id="sub-1")
        # executor would stream events, then fail:
        await store.append_turn_event(
            turn["id"], {"type": "content", "content": EVENT_PAYLOAD, "metadata": {}}
        )
        await store.transition_turn(turn["id"], "failed", error="boom", failure_code="provider")
        counts[f"attempt_{attempt + 1}"] = table_counts(store.db_path)
    return {
        "turn_rows_after_each_failed_resend": {
            k: v["turns"] for k, v in counts.items()
        },
        "turn_event_rows_after_each_failed_resend": {
            k: v["turn_events"] for k, v in counts.items()
        },
        "turn_submissions_rows_stable": counts["attempt_5"]["turn_submissions"],
        "store_paths": ["sqlite_store.py:1359-1458 (begin_turn inserts new turn per resend)",
                         "sqlite_store.py:1432-1436 (submission re-pointed to newest turn)"],
    }


async def scenario_regenerate_supersede(root: Path) -> dict[str, object]:
    """Regenerate deletes only the assistant MESSAGE; the superseded turn row
    and its turn_events survive with a dangling assistant_message_id."""
    store = SQLiteSessionStore(root / "regen.db")
    session = await store.create_session()
    sid = session["id"]
    t1 = await store.begin_turn(sid)
    user_id = await store.add_message(sid, "user", "question one")
    a1 = await store.add_message(
        sid, "assistant", "answer one", parent_message_id=user_id,
        metadata={"turn_id": t1["id"]},
    )
    await store.link_turn_message(t1["id"], a1)
    await store.append_turn_event(t1["id"], {"type": "result", "content": EVENT_PAYLOAD, "metadata": {}})
    await store.transition_turn(t1["id"], "completed")

    # regenerate: new turn, old assistant row deleted (request_preparer.py:883)
    t2 = await store.begin_turn(sid)
    a2 = await store.add_message(
        sid, "assistant", "answer one v2", parent_message_id=user_id,
        metadata={"turn_id": t2["id"]},
    )
    await store.link_turn_message(t2["id"], a2)
    await store.transition_turn(t2["id"], "completed")
    deleted = await store.delete_message(a1)

    return {
        "old_assistant_message_deleted": deleted,
        "turn_rows": table_counts(store.db_path),
        "dangling_turn_assistant_links": dangling_turn_links(store.db_path),
        "note": "t1 row retained; t1.assistant_message_id points at deleted message; "
                "t1 turn_events retained (never trimmed)",
        "store_paths": ["sqlite_store.py:2236-2240 (bare DELETE, no child splice, no turn cleanup)",
                         "request_preparer.py:877-884 (regenerate deletes only the assistant row)"],
    }


async def scenario_delete_message_dangling_parent(root: Path) -> dict[str, object]:
    """delete_message leaves children's parent_message_id dangling; the LLM
    context walk (get_message_path) silently stops at the hole."""
    store = SQLiteSessionStore(root / "dangle.db")
    sid = (await store.create_session())["id"]
    u1 = await store.add_message(sid, "user", "q1")
    a1 = await store.add_message(sid, "assistant", "a1", parent_message_id=u1)
    u2 = await store.add_message(sid, "user", "q2", parent_message_id=a1)
    a2 = await store.add_message(sid, "assistant", "a2", parent_message_id=u2)

    await store.delete_message(a1)
    path = await store.get_message_path(sid, a2)

    return {
        "dangling_parent_rows": dangling_message_parents(store.db_path),
        "message_path_from_surviving_leaf": [m["content"] for m in path],
        "context_rows_lost": 2,
        "store_paths": ["sqlite_store.py:2236-2240", "sqlite_store.py:2643-2658 (walk breaks on missing parent)"],
    }


async def scenario_branch_delete_paired(root: Path) -> dict[str, object]:
    """Paired deletion (delete_turn_by_message) removes one resolved turn but
    regenerated sibling turns sharing the user row survive."""
    store = SQLiteSessionStore(root / "branch.db")
    sid = (await store.create_session())["id"]
    t1 = await store.begin_turn(sid)
    uid = await store.add_message(sid, "user", "question", metadata={"turn_id": t1["id"]})
    a1 = await store.add_message(sid, "assistant", "v1", parent_message_id=uid,
                                 metadata={"turn_id": t1["id"]})
    await store.link_turn_message(t1["id"], a1)
    await store.transition_turn(t1["id"], "completed")

    # regenerate #1 and #2: sibling answers under the same user row
    t2 = await store.begin_turn(sid)
    a2 = await store.add_message(sid, "assistant", "v2", parent_message_id=uid,
                                 metadata={"turn_id": t2["id"]})
    await store.link_turn_message(t2["id"], a2)
    await store.transition_turn(t2["id"], "completed")
    t3 = await store.begin_turn(sid)
    a3 = await store.add_message(sid, "assistant", "v3", parent_message_id=uid,
                                 metadata={"turn_id": t3["id"]})
    await store.link_turn_message(t3["id"], a3)
    await store.transition_turn(t3["id"], "completed")

    # user deletes the whole exchange via the user message:
    result = await store.delete_turn_by_message(sid, uid)
    after = table_counts(store.db_path)
    return {
        "delete_result_turn_id_resolved": bool(result["turn_id"]),
        "turns_before": 3,
        "turns_after": after["turns"],
        "messages_after": after["messages"],
        "orphan_turn_rows_left": after["turns"] - 1,
        "note": "delete resolves exactly one turn (metadata stamp -> legacy fallback, "
                "sqlite_store.py:2304-2336); regenerated sibling turns survive",
        "store_paths": ["sqlite_store.py:2245-2427"],
    }


async def scenario_hard_delete_residuals(root: Path) -> dict[str, object]:
    """Hard-deleting a session cascades messages/turns/events/submissions but
    keeps notebook + assessment rows (ON DELETE SET NULL) with dead turn refs."""
    store = SQLiteSessionStore(root / "hard.db")
    sid = (await store.create_session())["id"]
    await store.reserve_submission("sub-hard", "digest", sid)
    t1 = await store.begin_turn(sid)
    uid = await store.add_message(sid, "user", "q", metadata={"turn_id": t1["id"]})
    a1 = await store.add_message(sid, "assistant", "a", parent_message_id=uid)
    await store.link_turn_message(t1["id"], a1)
    await store.append_turn_event(t1["id"], {"type": "result", "content": EVENT_PAYLOAD, "metadata": {}})
    await store.transition_turn(t1["id"], "completed")
    await store.upsert_notebook_entries(
        sid,
        [
            {
                "origin_type": "conversation",
                "origin_ref": sid,
                "turn_id": t1["id"],
                "question_id": "q-1",
                "question": "q",
                "source": "deep_question",
                "created_at": time.time(),
                "updated_at": time.time(),
            }
        ],
    )
    before = table_counts(store.db_path)
    await store.soft_delete_session(sid)
    await store.hard_delete_session(sid)
    after = table_counts(store.db_path)
    conn = sqlite3.connect(store.db_path)
    try:
        notebook_turn_refs_alive = conn.execute(
            """
            SELECT COUNT(*) FROM notebook_entries n
            WHERE n.turn_id != '' AND NOT EXISTS
              (SELECT 1 FROM turns t WHERE t.id = n.turn_id)
            """
        ).fetchone()[0]
        submissions_left = conn.execute(
            "SELECT COUNT(*) FROM turn_submissions WHERE session_id = ?", (sid,)
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "rows_before_delete": before,
        "rows_after_hard_delete": after,
        "notebook_rows_surviving_with_session_id_null": after["notebook_entries"],
        "notebook_rows_referencing_deleted_turns": notebook_turn_refs_alive,
        "turn_submissions_cascaded_away": submissions_left == 0,
        "store_paths": ["sqlite_store.py:377 (notebook session_id ON DELETE SET NULL)",
                         "sqlite_store.py:424 (assessment session_id ON DELETE SET NULL)",
                         "sqlite_store.py:354-355 (turn_submissions CASCADE / SET NULL)",
                         "sqlite_store.py:1970-1977 (hard delete)"],
    }


async def scenario_soft_delete_forever(root: Path) -> dict[str, object]:
    """Recycle-bin sessions keep every row; nothing expires deleted_at."""
    store = SQLiteSessionStore(root / "soft.db")
    for i in range(3):
        sid = (await store.create_session(title=f"s{i}"))["id"]
        await store.add_message(sid, "user", f"q{i}")
        await store.soft_delete_session(sid)
    return {
        "rows_retained": table_counts(store.db_path),
        "listed_in_recycle_bin": len(await store.list_deleted_sessions()),
        "store_paths": ["sqlite_store.py:1945-1952 (soft delete = UPDATE deleted_at only)"],
    }


async def scenario_no_vacuum_after_mass_delete(root: Path) -> dict[str, object]:
    """After bulk hard deletes the main DB file keeps its size (freelist, no
    auto_vacuum, no VACUUM anywhere in the codebase)."""
    store = SQLiteSessionStore(root / "vacuum.db")
    sids = []
    for i in range(10):
        sid = (await store.create_session(title=f"bulk{i}"))["id"]
        t = await store.begin_turn(sid)
        await store.add_message(sid, "user", "q" * 4096)
        await store.add_message(sid, "assistant", "a" * 4096)
        for seq in range(20):
            await store.append_turn_event(
                t["id"], {"type": "content", "content": EVENT_PAYLOAD, "metadata": {}}
            )
        await store.transition_turn(t["id"], "completed")
        sids.append(sid)
    before = pragma_facts(store.db_path)
    for sid in sids:
        await store.soft_delete_session(sid)
        await store.hard_delete_session(sid)
    after = pragma_facts(store.db_path)
    return {
        "pragma_before_deletes": before,
        "pragma_after_deletes": after,
        "file_bytes_after_deletes": store.db_path.stat().st_size,
        "wal_bytes_after_deletes": (store.db_path.with_name(store.db_path.name + "-wal")).stat().st_size
        if (store.db_path.with_name(store.db_path.name + "-wal")).exists() else 0,
        "note": "page_count stays (freelist); file never shrinks without manual VACUUM",
        "store_paths": ["sqlite_store.py:287 (WAL on, no auto_vacuum/vacuum anywhere)"],
    }


async def scenario_placeholder_sessions(root: Path) -> dict[str, object]:
    """ensure_notebook_session mints real session rows that list as normal
    conversations with zero messages; no cleanup path."""
    store = SQLiteSessionStore(root / "ph.db")
    for i in range(3):
        await store.ensure_notebook_session(f"partner-sess-{i}", f"Partner {i}")
    sessions = await store.list_sessions()
    return {
        "placeholder_sessions": 3,
        "listed_as_regular_sessions": len(sessions),
        "rows": table_counts(store.db_path),
        "store_paths": ["sqlite_store.py:1241-1266"],
    }


async def scenario_turn_event_volume_per_turn(root: Path) -> dict[str, object]:
    """Every streamed CONTENT/THINKING/tool delta of a turn is persisted into
    turn_events and never trimmed after completion."""
    store = SQLiteSessionStore(root / "events.db")
    sid = (await store.create_session())["id"]
    t = await store.begin_turn(sid)
    deltas = 200
    for _ in range(deltas):
        await store.append_turn_event(
            t["id"], {"type": "content", "content": EVENT_PAYLOAD, "metadata": {}}
        )
    await store.transition_turn(t["id"], "completed")
    counts = table_counts(store.db_path)
    return {
        "deltas_streamed": deltas,
        "turn_event_rows": counts["turn_events"],
        "turn_events_payload_bytes": turn_events_bytes(store.db_path),
        "rows_surviving_after_completion": counts["turn_events"],
        "note": "lifecycle.py:655-691 buffers every non-DONE event; flush persists all "
                "(lifecycle.py:693-765); read-side caps (event_preview.py:14-15) do not bound storage",
        "store_paths": ["executor.py:1017-1049", "lifecycle.py:679-691", "sqlite_store.py:1677-1755"],
    }


async def scenario_submission_row_after_turn_delete(root: Path) -> dict[str, object]:
    """#1793 binding survives turn deletion: submission row persists with
    turn_id NULL; the next resend re-binds a fresh turn. Rows live until the
    session is deleted (no timestamp, no aging)."""
    store = SQLiteSessionStore(root / "sub.db")
    sid = await store.reserve_submission("sub-x", "digest-x")
    t1 = await store.begin_turn(sid, submission_id="sub-x")
    uid = await store.add_message(sid, "user", "q", metadata={"turn_id": t1["id"]})
    await store.add_message(sid, "assistant", "a", parent_message_id=uid)
    await store.transition_turn(t1["id"], "failed", failure_code="provider")
    await store.delete_turn_by_message(sid, uid)
    conn = sqlite3.connect(store.db_path)
    try:
        row = conn.execute(
            "SELECT turn_id FROM turn_submissions WHERE client_submission_id='sub-x'"
        ).fetchone()
    finally:
        conn.close()
    t2 = await store.begin_turn(sid, submission_id="sub-x")
    return {
        "submission_turn_id_after_turn_delete": row[0],
        "resend_created_new_turn": t2["id"] != t1["id"],
        "columns": submission_columns(store.db_path),
        "note": "no created_at column -> no retention/aging possible on turn_submissions",
        "store_paths": ["sqlite_store.py:350-356", "sqlite_store.py:1179-1223"],
    }


async def main() -> dict[str, object]:
    root = Path(tempfile.mkdtemp(prefix="dt-session-sqlite-scan-"))
    scenarios = {
        "schema_facts": None,
        "resend_fail_loop": scenario_resend_fail_loop,
        "regenerate_supersede": scenario_regenerate_supersede,
        "delete_message_dangling_parent": scenario_delete_message_dangling_parent,
        "branch_delete_paired": scenario_branch_delete_paired,
        "hard_delete_residuals": scenario_hard_delete_residuals,
        "soft_delete_forever": scenario_soft_delete_forever,
        "no_vacuum_after_mass_delete": scenario_no_vacuum_after_mass_delete,
        "placeholder_sessions": scenario_placeholder_sessions,
        "turn_event_volume_per_turn": scenario_turn_event_volume_per_turn,
        "submission_row_after_turn_delete": scenario_submission_row_after_turn_delete,
    }
    out: dict[str, object] = {}
    seed = SQLiteSessionStore(root / "schema.db")
    out["schema_facts"] = {
        **pragma_facts(seed.db_path),
        "turn_submissions_columns": submission_columns(seed.db_path),
    }
    for name, fn in scenarios.items():
        if fn is None:
            continue
        out[name] = await fn(root)
    return out


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), indent=2, ensure_ascii=False))
