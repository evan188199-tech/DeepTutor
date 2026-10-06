"""Concurrency contract for the SQLite session store's lock split.

The store used to funnel every operation through one ``asyncio.Lock``, so a
single slow query blocked all sessions. These tests pin the two halves of the
contract introduced with the read/write split:

* read-path calls take no in-process lock, so a blocked read never keeps a
  write (or another read) waiting;
* write-path calls still serialize in-process, so read-modify-write
  sequences (event ``seq`` assignment, auto-parent chaining) stay correct
  under concurrent callers.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any

import pytest

from deeptutor.services.session.sqlite_store import SQLiteSessionStore


def _make_store(tmp_path: Path) -> SQLiteSessionStore:
    return SQLiteSessionStore(db_path=tmp_path / "chat-history.db")


async def _wait_for_event(event: threading.Event, timeout: float = 5.0) -> None:
    """Poll a threading.Event without blocking the running event loop."""
    deadline = time.monotonic() + timeout
    while not event.is_set():
        assert time.monotonic() < deadline, "timed out waiting for test event"
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_slow_read_does_not_block_write(tmp_path: Path) -> None:
    """A read stuck inside SQLite must not keep a concurrent write waiting.

    Under the old single store-wide lock the write would queue behind the
    blocked read and time out; the read path taking no lock lets the write
    finish while the read is still in flight.
    """
    store = _make_store(tmp_path)
    await store.create_session(session_id="session-a", title="A")

    read_entered = threading.Event()
    release_read = threading.Event()
    uninstrumented = store._list_sessions_sync

    def slow_list_sessions(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        read_entered.set()
        release_read.wait(timeout=10)
        return uninstrumented(*args, **kwargs)

    store._list_sessions_sync = slow_list_sessions  # type: ignore[method-assign]
    try:
        read_task = asyncio.create_task(store.list_sessions())
        await _wait_for_event(read_entered)

        await asyncio.wait_for(store.update_session_title("session-a", "Renamed"), timeout=5)

        release_read.set()
        rows = await asyncio.wait_for(read_task, timeout=5)
    finally:
        release_read.set()
        del store._list_sessions_sync  # type: ignore[method-assign]

    assert [row["id"] for row in rows] == ["session-a"]
    session = await store.get_session("session-a")
    assert session is not None
    assert session["title"] == "Renamed"


@pytest.mark.asyncio
async def test_slow_read_does_not_block_other_reads(tmp_path: Path) -> None:
    """Two read-path calls must be able to run at the same time."""
    store = _make_store(tmp_path)
    await store.create_session(session_id="session-a", title="A")

    read_entered = threading.Event()
    release_read = threading.Event()
    uninstrumented = store._get_session_sync

    def slow_get_session(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
        read_entered.set()
        release_read.wait(timeout=10)
        return uninstrumented(*args, **kwargs)

    store._get_session_sync = slow_get_session  # type: ignore[method-assign]
    try:
        blocked_task = asyncio.create_task(store.get_session("session-a"))
        await _wait_for_event(read_entered)

        # A different read-path call runs while the first read is blocked.
        concurrent = await asyncio.wait_for(store.list_sessions(), timeout=5)

        release_read.set()
        released = await asyncio.wait_for(blocked_task, timeout=5)
    finally:
        release_read.set()
        del store._get_session_sync  # type: ignore[method-assign]

    assert [row["id"] for row in concurrent] == ["session-a"]
    assert released is not None and released["id"] == "session-a"


@pytest.mark.asyncio
async def test_concurrent_writes_still_serialize(tmp_path: Path) -> None:
    """Write-path calls must never overlap, preserving the single writer."""
    store = _make_store(tmp_path)
    await store.create_session(session_id="session-a", title="A")

    guard = threading.Lock()
    active = 0
    max_active = 0
    uninstrumented = store._update_session_title_sync

    def instrumented_title_update(session_id: str, title: str) -> bool:
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.02)  # widen the window in which overlap could show up
            return uninstrumented(session_id, title)
        finally:
            with guard:
                active -= 1

    store._update_session_title_sync = instrumented_title_update  # type: ignore[method-assign]
    try:
        await asyncio.gather(
            *(store.update_session_title("session-a", f"title-{i}") for i in range(8))
        )
    finally:
        del store._update_session_title_sync  # type: ignore[method-assign]

    assert max_active == 1, "write-path calls overlapped"
    session = await store.get_session("session-a")
    assert session is not None
    assert session["title"].startswith("title-")


@pytest.mark.asyncio
async def test_concurrent_event_appends_keep_seq_unique(tmp_path: Path) -> None:
    """Interleaved writers and readers leave a gapless, unique event log.

    Event ``seq`` assignment is a read-modify-write (``MAX(seq) + 1``), so
    this doubles as a regression guard for the single-writer guarantee.
    """
    store = _make_store(tmp_path)
    await store.create_session(session_id="session-a")
    await store.begin_turn("session-a", "chat", turn_id="turn-a")

    write_count = 20
    writers = [
        store.append_events("turn-a", [{"type": "progress", "content": f"step-{i}"}])
        for i in range(write_count)
    ]
    readers = [store.get_turn_events("turn-a") for _ in range(10)]
    results = await asyncio.gather(*writers, *readers)

    appended = sorted(payload["seq"] for payloads in results[:write_count] for payload in payloads)
    assert appended == list(range(1, write_count + 1))

    final_events = await store.get_turn_events("turn-a")
    assert [event["seq"] for event in final_events] == list(range(1, write_count + 1))
    assert [event["content"] for event in final_events] == [f"step-{i}" for i in range(write_count)]

    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.asyncio
async def test_concurrent_auto_parent_messages_form_one_chain(tmp_path: Path) -> None:
    """Auto-parenting picks the latest row, so writes must stay serialized.

    With N concurrent ``add_message`` calls the session must end up with N
    messages in a single connected parent chain, not several roots.
    """
    store = _make_store(tmp_path)
    await store.create_session(session_id="session-a")

    message_count = 16
    writers = [store.add_message("session-a", "user", f"message-{i}") for i in range(message_count)]
    readers = [store.list_sessions() for _ in range(8)]
    await asyncio.gather(*writers, *readers)

    messages = await store.get_messages("session-a")
    assert len(messages) == message_count

    by_id = {message["id"]: message for message in messages}
    assert len(by_id) == message_count
    roots = [message for message in messages if message.get("parent_message_id") is None]
    assert len(roots) == 1, "concurrent auto-parent writes created multiple roots"

    chain: list[int] = []
    current = max(by_id)
    while current is not None:
        chain.append(current)
        current = by_id[current].get("parent_message_id")  # type: ignore[assignment]
    assert len(chain) == message_count, "parent chain is broken or loops"

    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
