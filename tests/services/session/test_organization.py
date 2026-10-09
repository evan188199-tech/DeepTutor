"""Contract and boundary tests for session organization integrity helpers."""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.session.organization import (
    list_all_sessions_snapshot,
    validate_parent_assignment,
)


def _row(session_id: str, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"session_id": session_id, "updated_at": 0}
    row.update(extra)
    return row


class _FakeStore:
    """In-memory store fake covering the two protocol methods the integrity
    helpers call: list_sessions (flat ordered rows, sliced by offset) and
    get_session (row lookup by id). Every call is recorded for assertions.
    ``direct`` holds rows reachable only via get_session, e.g. rows stored
    under an id key the list page does not carry."""

    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        *,
        direct: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.rows = rows if rows is not None else []
        self.direct = direct or {}
        self.list_calls: list[tuple[int, int]] = []
        self.get_calls: list[str] = []

    async def list_sessions(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        self.list_calls.append((limit, offset))
        return self.rows[offset : offset + limit]

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        self.get_calls.append(session_id)
        if session_id in self.direct:
            return self.direct[session_id]
        for row in self.rows:
            key = str(row.get("session_id") or row.get("id") or "")
            if key == session_id:
                return row
        return None


# ---------------------------------------------------------------------------
# list_all_sessions_snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_short_first_page_returns_all_rows_with_single_call() -> None:
    rows = [_row(f"s-{index}") for index in range(3)]
    store = _FakeStore(rows)

    snapshot = await list_all_sessions_snapshot(store, page_size=200)

    assert snapshot == rows
    assert store.list_calls == [(200, 0)]


@pytest.mark.asyncio
async def test_snapshot_walks_offsets_until_short_page() -> None:
    rows = [_row(f"s-{index}") for index in range(5)]
    store = _FakeStore(rows)

    snapshot = await list_all_sessions_snapshot(store, page_size=2)

    assert snapshot == rows
    assert store.list_calls == [(2, 0), (2, 2), (2, 4)]


@pytest.mark.asyncio
async def test_snapshot_exact_page_multiple_probes_one_trailing_page() -> None:
    rows = [_row(f"s-{index}") for index in range(4)]
    store = _FakeStore(rows)

    snapshot = await list_all_sessions_snapshot(store, page_size=2)

    assert snapshot == rows
    assert store.list_calls == [(2, 0), (2, 2), (2, 4)]
    assert snapshot[-1] is rows[-1]


@pytest.mark.asyncio
async def test_snapshot_empty_store_returns_empty_list() -> None:
    store = _FakeStore([])

    snapshot = await list_all_sessions_snapshot(store, page_size=3)

    assert snapshot == []
    assert store.list_calls == [(3, 0)]


# ---------------------------------------------------------------------------
# validate_parent_assignment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_parent_raises_lookup_error_and_stops_walking() -> None:
    store = _FakeStore([_row("session-1")])

    with pytest.raises(LookupError) as excinfo:
        await validate_parent_assignment(
            store,
            session_id="session-1",
            parent_session_id="ghost",
        )

    assert str(excinfo.value) == "ghost"
    assert store.get_calls == ["ghost"]


@pytest.mark.asyncio
async def test_parent_without_ancestors_is_returned_unchanged() -> None:
    parent = _row("parent")
    store = _FakeStore([parent, _row("session-1")])

    result = await validate_parent_assignment(
        store,
        session_id="session-1",
        parent_session_id="parent",
    )

    assert result is parent
    assert store.get_calls == ["parent"]


@pytest.mark.asyncio
async def test_self_assignment_is_rejected_as_cycle() -> None:
    row = _row("session-1")
    store = _FakeStore([row])

    with pytest.raises(ValueError, match="parent cycle"):
        await validate_parent_assignment(
            store,
            session_id="session-1",
            parent_session_id="session-1",
        )


@pytest.mark.asyncio
async def test_cycle_above_the_session_is_rejected() -> None:
    loop_a = _row("loop-a", preferences={"parent_session_id": "loop-b"})
    loop_b = _row("loop-b", preferences={"parent_session_id": "loop-a"})
    parent = _row("parent", preferences={"parent_session_id": "loop-a"})
    store = _FakeStore([parent, loop_a, loop_b, _row("session-1")])

    with pytest.raises(ValueError, match="parent cycle"):
        await validate_parent_assignment(
            store,
            session_id="session-1",
            parent_session_id="parent",
        )


@pytest.mark.asyncio
async def test_orphaned_ancestor_is_not_a_cycle() -> None:
    parent = _row("parent", preferences={"parent_session_id": "ghost"})
    store = _FakeStore([parent, _row("session-1")])

    result = await validate_parent_assignment(
        store,
        session_id="session-1",
        parent_session_id="parent",
    )

    assert result is parent
    assert store.get_calls == ["parent", "ghost"]


@pytest.mark.asyncio
async def test_duplicate_parent_branches_sharing_a_root_both_validate() -> None:
    root = _row("root")
    branch_a = _row("branch-a", preferences={"parent_session_id": "root"})
    branch_b = _row("branch-b", preferences={"parent_session_id": "root"})
    child_a = _row("child-a", preferences={"parent_session_id": "branch-a"})
    child_b = _row("child-b", preferences={"parent_session_id": "branch-b"})
    store = _FakeStore([root, branch_a, branch_b, child_a, child_b])

    result_a = await validate_parent_assignment(
        store,
        session_id="child-a",
        parent_session_id="branch-a",
    )
    result_b = await validate_parent_assignment(
        store,
        session_id="child-b",
        parent_session_id="branch-b",
    )

    assert result_a is branch_a
    assert result_b is branch_b
    assert store.get_calls == [
        "branch-a",
        "root",
        "branch-b",
        "root",
    ]


@pytest.mark.asyncio
async def test_row_using_id_key_fallback_and_blank_ancestor_treated_as_root() -> None:
    parent = {"id": "parent", "preferences": {"parent_session_id": "   "}}
    store = _FakeStore([parent, _row("session-1")])

    result = await validate_parent_assignment(
        store,
        session_id="session-1",
        parent_session_id="parent",
    )

    assert result is parent
    assert store.get_calls == ["parent"]


@pytest.mark.asyncio
async def test_ancestor_row_without_any_id_is_rejected() -> None:
    parent = _row("parent", preferences={"parent_session_id": "root"})
    anonymous_root = {"preferences": {}}
    store = _FakeStore(
        [parent, _row("session-1")],
        direct={"root": anonymous_root},
    )

    with pytest.raises(ValueError, match="parent cycle"):
        await validate_parent_assignment(
            store,
            session_id="session-1",
            parent_session_id="parent",
        )
