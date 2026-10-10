"""Unit contracts for workspace navigation with fully mocked storage.

read_workspace_indexes must scan the default scope plus every catalogued
workspace, annotate every row with its authoritative origin, and degrade to
"unavailable" per workspace instead of failing the whole account index.
session_index must merge store pages in bounded chunks, sort globally, and
paginate across workspace boundaries without touching real data directories.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from deeptutor.services.workspace import navigation
from deeptutor.services.workspace.context import (
    WorkspaceScope,
    current_workspace_id,
)
from deeptutor.services.workspace.navigation import (
    read_workspace_indexes,
    session_index,
)

NAVIGATION_LOGGER = "deeptutor.services.workspace.navigation"


def _catalog_row(workspace_id: str, display_name: str, kind: str = "workspace"):
    return {
        "workspace_id": workspace_id,
        "display_name": display_name,
        "kind": kind,
    }


class _FakeCatalogService:
    def __init__(self, rows):
        self._rows = rows
        self.list_calls = 0

    def list_workspaces(self):
        self.list_calls += 1
        return [dict(row) for row in self._rows]


def _install_catalog(monkeypatch, rows):
    service = _FakeCatalogService(rows)
    monkeypatch.setattr(navigation, "get_content_workspace_service", lambda: service)
    return service


def _install_scope(monkeypatch, tmp_path):
    def _resolve(workspace_id=None):
        return WorkspaceScope(str(workspace_id or ""), tmp_path, tmp_path / "content")

    from deeptutor.services.workspace import context as context_module

    monkeypatch.setattr(context_module, "resolve_workspace_scope", _resolve)


class _FakeSessionStore:
    def __init__(self, sessions, fail=False):
        self._sessions = sessions
        self._fail = fail
        self.list_calls = []
        self.search_calls = []
        self.total_reads = 0

    async def list_sessions(self, limit=50, offset=0):
        self.list_calls.append((limit, offset))
        if self._fail:
            raise RuntimeError("session index offline")
        return [dict(row) for row in self._sessions[offset : offset + limit]]

    async def search_sessions(self, query, limit=50, offset=0):
        self.search_calls.append((query, limit, offset))
        if self._fail:
            raise json.JSONDecodeError("malformed stored index", "", 0)
        self.total_reads += 1
        return {
            "sessions": [dict(row) for row in self._sessions[offset : offset + limit]],
            "total": len(self._sessions) + offset,
        }


def _install_store(monkeypatch, sessions_by_scope, fail_scopes=frozenset()):
    stores = {}

    def _factory():
        scope_id = current_workspace_id()
        if scope_id not in stores:
            stores[scope_id] = _FakeSessionStore(
                sessions_by_scope.get(scope_id, []), fail=scope_id in fail_scopes
            )
        return stores[scope_id]

    from deeptutor.services import session as session_package

    monkeypatch.setattr(session_package, "get_session_store", _factory)
    return stores


def _session(session_id: str, updated_at: float):
    return {"session_id": session_id, "updated_at": updated_at, "title": session_id}


@pytest.mark.asyncio
async def test_read_indexes_scans_default_then_workspaces_and_annotates_rows(monkeypatch, tmp_path):
    _install_catalog(monkeypatch, [_catalog_row("a", "Alpha"), _catalog_row("b", "Beta")])
    _install_scope(monkeypatch, tmp_path)
    visited = []

    async def reader():
        visited.append(current_workspace_id())
        return [{"session_id": f"s-{current_workspace_id()}", "updated_at": 1.0}]

    rows, unavailable = await read_workspace_indexes(reader)
    assert visited == ["", "a", "b"]
    assert unavailable == []
    assert [row["content_workspace_id"] for row in rows] == ["", "a", "b"]
    assert [row["content_workspace_name"] for row in rows] == ["", "Alpha", "Beta"]
    assert rows[0]["session_id"] == "s-"
    assert current_workspace_id() == ""


@pytest.mark.asyncio
async def test_read_indexes_dedupes_repeated_catalog_ids(monkeypatch, tmp_path):
    _install_catalog(
        monkeypatch,
        [_catalog_row("a", "First"), _catalog_row("a", "Second")],
    )
    _install_scope(monkeypatch, tmp_path)
    visited = []

    async def reader():
        visited.append(current_workspace_id())
        return []

    rows, unavailable = await read_workspace_indexes(reader)
    assert visited == ["", "a"]
    assert rows == []
    assert unavailable == []


@pytest.mark.asyncio
async def test_read_indexes_skips_non_workspace_catalog_kinds(monkeypatch, tmp_path):
    _install_catalog(
        monkeypatch,
        [
            _catalog_row("system-folder", "System", kind="system"),
            _catalog_row("a", "Alpha"),
        ],
    )
    _install_scope(monkeypatch, tmp_path)
    visited = []

    async def reader():
        visited.append(current_workspace_id())
        return []

    rows, unavailable = await read_workspace_indexes(reader)
    assert visited == ["", "a"]
    assert unavailable == []


@pytest.mark.asyncio
async def test_read_indexes_reader_failure_reports_workspace_and_keeps_rest(
    monkeypatch, tmp_path, caplog
):
    _install_catalog(monkeypatch, [_catalog_row("a", "Alpha"), _catalog_row("b", "Beta")])
    _install_scope(monkeypatch, tmp_path)

    async def reader():
        scope = current_workspace_id()
        if scope == "a":
            raise json.JSONDecodeError("malformed index payload", "{not json", 0)
        return [{"session_id": f"s-{scope}", "updated_at": 2.0}]

    with caplog.at_level(logging.WARNING, logger=NAVIGATION_LOGGER):
        rows, unavailable = await read_workspace_indexes(reader)
    assert [row["content_workspace_id"] for row in rows] == ["", "b"]
    assert unavailable == ["a"]
    warnings = [r for r in caplog.records if r.name == NAVIGATION_LOGGER]
    assert len(warnings) == 1
    assert warnings[0].exc_info is not None


@pytest.mark.asyncio
async def test_read_indexes_all_readers_failing_degrades_to_empty(monkeypatch, tmp_path, caplog):
    _install_catalog(monkeypatch, [_catalog_row("a", "Alpha")])
    _install_scope(monkeypatch, tmp_path)

    async def reader():
        raise RuntimeError("content store offline")

    with caplog.at_level(logging.WARNING, logger=NAVIGATION_LOGGER):
        rows, unavailable = await read_workspace_indexes(reader)
    assert rows == []
    assert unavailable == ["", "a"]
    assert len([r for r in caplog.records if r.name == NAVIGATION_LOGGER]) == 2


@pytest.mark.asyncio
async def test_read_indexes_empty_catalog_reads_only_default_scope(monkeypatch, tmp_path):
    _install_catalog(monkeypatch, [])
    _install_scope(monkeypatch, tmp_path)
    visited = []

    async def reader():
        visited.append(current_workspace_id())
        return [{"session_id": "only", "updated_at": 3.0}]

    rows, unavailable = await read_workspace_indexes(reader)
    assert visited == [""]
    assert len(rows) == 1
    assert rows[0]["content_workspace_id"] == ""
    assert rows[0]["content_workspace_name"] == ""
    assert unavailable == []


@pytest.mark.asyncio
async def test_read_indexes_returns_copies_and_keeps_reader_rows_intact(monkeypatch, tmp_path):
    _install_catalog(monkeypatch, [])
    _install_scope(monkeypatch, tmp_path)
    original = [{"session_id": "s1", "updated_at": 1.0}]

    async def reader():
        return original

    rows, _ = await read_workspace_indexes(reader)
    assert rows[0] is not original[0]
    rows[0]["session_id"] = "mutated"
    assert original[0]["session_id"] == "s1"


@pytest.mark.asyncio
async def test_session_index_merges_sorts_and_paginates_across_workspaces(monkeypatch, tmp_path):
    _install_catalog(monkeypatch, [_catalog_row("b", "Beta")])
    _install_scope(monkeypatch, tmp_path)
    _install_store(
        monkeypatch,
        {
            "": [_session("s-old", 10.0), _session("s-new", 30.0)],
            "b": [_session("b-mid", 20.0), _session("b-top", 40.0)],
        },
    )
    result = await session_index(2, 1)
    assert set(result) == {"sessions", "total", "limit", "offset", "unavailable_workspaces"}
    assert result["limit"] == 2
    assert result["offset"] == 1
    assert result["total"] == 0
    assert result["unavailable_workspaces"] == []
    assert [(row["content_workspace_id"], row["session_id"]) for row in result["sessions"]] == [
        ("", "s-new"),
        ("b", "b-mid"),
    ]


@pytest.mark.asyncio
async def test_session_index_pages_store_in_100_row_chunks(monkeypatch, tmp_path):
    _install_catalog(monkeypatch, [])
    _install_scope(monkeypatch, tmp_path)
    sessions = [_session(f"s{i:03d}", float(i)) for i in range(150)]
    stores = _install_store(monkeypatch, {"": sessions})
    result = await session_index(100, 50)
    assert stores[""].list_calls == [(100, 0), (50, 100)]
    assert len(result["sessions"]) == 100
    assert result["sessions"][0]["updated_at"] == 99.0
    assert result["sessions"][-1]["updated_at"] == 0.0


@pytest.mark.asyncio
async def test_session_index_stops_early_when_store_page_is_short(monkeypatch, tmp_path):
    _install_catalog(monkeypatch, [])
    _install_scope(monkeypatch, tmp_path)
    stores = _install_store(monkeypatch, {"": [_session("s0", 1.0), _session("s1", 2.0)]})
    result = await session_index(50, 500)
    assert stores[""].list_calls == [(100, 0)]
    assert result["sessions"] == []


@pytest.mark.asyncio
async def test_session_index_zero_limit_touches_no_store_pages(monkeypatch, tmp_path):
    _install_catalog(monkeypatch, [_catalog_row("a", "Alpha")])
    _install_scope(monkeypatch, tmp_path)
    stores = _install_store(monkeypatch, {"": [_session("s0", 1.0)], "a": [_session("s1", 2.0)]})
    result = await session_index(0, 0)
    assert all(store.list_calls == [] for store in stores.values())
    assert result["sessions"] == []
    assert result["limit"] == 0


@pytest.mark.asyncio
async def test_session_index_search_sums_total_once_per_workspace(monkeypatch, tmp_path):
    _install_catalog(monkeypatch, [_catalog_row("b", "Beta")])
    _install_scope(monkeypatch, tmp_path)
    stores = _install_store(
        monkeypatch,
        {
            "": [_session(f"d{i:03d}", float(i)) for i in range(110)],
            "b": [_session(f"b{i:03d}", float(i)) for i in range(110)],
        },
    )
    result = await session_index(100, 50, "needle")
    assert stores[""].total_reads == 2
    assert stores["b"].total_reads == 2
    assert stores[""].search_calls == [("needle", 100, 0), ("needle", 50, 100)]
    assert stores["b"].search_calls == [("needle", 100, 0), ("needle", 50, 100)]
    assert result["total"] == 220
    assert result["unavailable_workspaces"] == []
    assert len(result["sessions"]) == 100


@pytest.mark.asyncio
async def test_session_index_search_failure_in_one_workspace_still_serves_rest(
    monkeypatch, tmp_path, caplog
):
    _install_catalog(monkeypatch, [_catalog_row("a", "Alpha")])
    _install_scope(monkeypatch, tmp_path)
    stores = _install_store(
        monkeypatch,
        {
            "": [_session("keep", 5.0)],
            "a": [_session("hidden", 9.0)],
        },
        fail_scopes={"a"},
    )
    with caplog.at_level(logging.WARNING, logger=NAVIGATION_LOGGER):
        result = await session_index(10, 0, "needle")
    assert [row["session_id"] for row in result["sessions"]] == ["keep"]
    assert result["unavailable_workspaces"] == ["a"]
    assert result["total"] == 1
    assert stores["a"].search_calls == [("needle", 10, 0)]
    assert len([r for r in caplog.records if r.name == NAVIGATION_LOGGER]) == 1


@pytest.mark.asyncio
async def test_session_index_ties_sort_by_workspace_then_session_id(monkeypatch, tmp_path):
    _install_catalog(monkeypatch, [_catalog_row("b", "Beta")])
    _install_scope(monkeypatch, tmp_path)
    _install_store(
        monkeypatch,
        {
            "": [_session("z", 5.0), _session("m", 5.0)],
            "b": [_session("a", 5.0)],
        },
    )
    result = await session_index(10, 0)
    assert [(row["content_workspace_id"], row["session_id"]) for row in result["sessions"]] == [
        ("", "m"),
        ("", "z"),
        ("b", "a"),
    ]


def test_navigation_module_imports_are_storage_only():
    assert callable(read_workspace_indexes)
    assert callable(session_index)
    assert asyncio.iscoroutinefunction(read_workspace_indexes)
    assert asyncio.iscoroutinefunction(session_index)
