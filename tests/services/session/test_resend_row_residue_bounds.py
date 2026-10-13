"""Resend residue bounds for the session SQLite store.

Lost-ack resend of a failing submission (the #1793 binding,
``_begin_turn_sync`` / ``_reserve_submission_sync``) re-points the singleton
``turn_submissions`` row to a brand-new ``turns`` row on every attempt, and
nothing prunes the superseded failed turns or their ``turn_events`` under the
current no-vacuum strategy. These tests pin the resulting row-growth upper
bounds so a future retention design has a measured baseline to relax
deliberately (storage-growth audit findings R1/R5). They document current
behaviour; they do not endorse it.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

import pytest

from deeptutor.services.session.sqlite_store import SQLiteSessionStore

_TABLES = (
    "sessions",
    "messages",
    "turns",
    "turn_events",
    "turn_submissions",
)

_DIGEST = "digest-resend-residue"


def _table_counts(db_path: Path) -> dict[str, int]:
    with sqlite3.connect(db_path) as conn:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # nosec B608
            for table in _TABLES
        }


def _submission_row(db_path: Path) -> dict[str, Any] | None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT client_submission_id, session_id, turn_id FROM turn_submissions"
        ).fetchone()
    return dict(row) if row is not None else None


async def _run_failed_attempt(
    store: SQLiteSessionStore,
    session_id: str,
    submission_id: str,
    seq: int,
) -> str:
    """One resend cycle of the store-level write path: admit a fresh turn,
    stream one buffered event, then fail — mirroring the executor's failed
    resend sequence without any LLM/network."""
    turn = await store.begin_turn(session_id, submission_id=submission_id)
    await store.append_turn_event(
        turn["id"],
        {"type": "content", "content": f"delta-{seq}", "metadata": {}},
    )
    await store.transition_turn(
        turn["id"], "failed", error="provider unavailable", failure_code="provider_error"
    )
    return str(turn["id"])


async def _run_failed_resend_loop(
    store: SQLiteSessionStore, submission_id: str, attempts: int
) -> tuple[str, list[str]]:
    """Reserve once, then resend N times: each attempt re-reserves (as the
    resend path does) and must land on the same session."""
    session_id = await store.reserve_submission(submission_id, _DIGEST)
    turn_ids: list[str] = []
    for seq in range(attempts):
        assert await store.reserve_submission(submission_id, _DIGEST, session_id) == session_id
        turn_ids.append(await _run_failed_attempt(store, session_id, submission_id, seq))
    return session_id, turn_ids


@pytest.mark.asyncio
async def test_each_failed_resend_appends_exactly_one_turn_row(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path / "residue.db")
    session_id = await store.reserve_submission("sub-turns", _DIGEST)
    for seq in range(1, 6):
        await _run_failed_attempt(store, session_id, "sub-turns", seq)
        counts = _table_counts(store.db_path)
        assert counts["turns"] == seq
        assert counts["sessions"] == 1


@pytest.mark.asyncio
async def test_each_failed_resend_appends_exactly_one_turn_event_row(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path / "residue-events.db")
    session_id, turn_ids = await _run_failed_resend_loop(store, "sub-events", attempts=5)
    counts = _table_counts(store.db_path)
    assert counts["turn_events"] == 5
    failed_turns = await store.list_orphaned_failed_turns(session_id)
    assert sorted(turn["id"] for turn in failed_turns) == sorted(turn_ids)
    for turn in failed_turns:
        assert len(await store.get_turn_events(turn["id"])) == 1


@pytest.mark.asyncio
async def test_submission_row_stays_singleton_and_repoints_to_newest_turn(
    tmp_path: Path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "residue-sub.db")
    session_id, turn_ids = await _run_failed_resend_loop(store, "sub-single", attempts=3)
    assert _table_counts(store.db_path)["turn_submissions"] == 1
    row = _submission_row(store.db_path)
    assert row is not None
    assert row["client_submission_id"] == "sub-single"
    assert row["session_id"] == session_id
    assert row["turn_id"] == turn_ids[-1]


@pytest.mark.asyncio
async def test_failed_resend_reuses_the_original_session(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path / "residue-session.db")
    session_id, _ = await _run_failed_resend_loop(store, "sub-session", attempts=5)
    counts = _table_counts(store.db_path)
    assert counts["sessions"] == 1
    sessions = await store.list_sessions()
    assert [session["id"] for session in sessions] == [session_id]
    assert counts["messages"] == 0


@pytest.mark.asyncio
async def test_superseded_failed_turns_survive_a_final_successful_resend(
    tmp_path: Path,
) -> None:
    """After 3 failed resends, the 4th succeeds — failed turns and their
    events are still all retained (nothing prunes superseded attempts)."""
    store = SQLiteSessionStore(tmp_path / "residue-success.db")
    session_id, _ = await _run_failed_resend_loop(store, "sub-final", attempts=3)
    final_turn = await store.begin_turn(session_id, submission_id="sub-final")
    await store.append_turn_event(
        final_turn["id"], {"type": "result", "content": "answer", "metadata": {}}
    )
    await store.transition_turn(final_turn["id"], "completed")
    counts = _table_counts(store.db_path)
    assert counts["turns"] == 4
    assert counts["turn_events"] == 4
    assert counts["turn_submissions"] == 1
    submission = _submission_row(store.db_path)
    assert submission is not None
    assert submission["turn_id"] == str(final_turn["id"])
    assert len(await store.list_orphaned_failed_turns(session_id)) == 3


@pytest.mark.parametrize("attempts", [1, 3, 5])
@pytest.mark.asyncio
async def test_failed_resend_row_growth_upper_bound(tmp_path: Path, attempts: int) -> None:
    """Bound under the current no-vacuum strategy: N failed resends of one
    submission leave exactly N turn rows + N turn-event rows, 1 session and
    1 submission row — the growth is linear and never reclaimed."""
    store = SQLiteSessionStore(tmp_path / f"residue-bound-{attempts}.db")
    session_id, _ = await _run_failed_resend_loop(store, f"sub-bound-{attempts}", attempts)
    counts = _table_counts(store.db_path)
    assert counts["turns"] == attempts
    assert counts["turn_events"] == attempts
    assert counts["turn_submissions"] == 1
    assert counts["sessions"] == 1
    assert counts["messages"] == 0
    assert session_id == await store.reserve_submission(
        f"sub-bound-{attempts}", _DIGEST, session_id
    )
