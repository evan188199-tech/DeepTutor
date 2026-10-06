"""Dual-backend regression for session status/capability reads (D2).

The SQLite store keeps no ``status``/``capability``/``active_turn_id`` columns
on ``sessions`` and derives all three from the ``turns`` table on every read
(``_get_session_sync`` / ``_SESSION_SUMMARY_SQL``). The PocketBase store
persists ``status``/``capability`` as collection columns that are written
exactly once — by ``create_session`` — and never revisited by
``begin_turn``/``transition_turn``; ``active_turn_id`` is always returned as
``""`` (``_session_record_to_dict``). Only ``get_session_summaries`` overlays
a live active-turn status, and only while a turn is still active, so on
PocketBase ``get_session`` reports the create-time status forever after.

These tests replay identical operation scripts against both backends — a real
``SQLiteSessionStore`` on a per-test database file and a
``PocketBaseSessionStore`` against an in-memory fake of the PocketBase SDK
(the real ``pocketbase`` package is not a test dependency, following
``test_pocketbase_isolation.py``) — and compare the session-level views each
backend reports after every step.

Scenarios where the two backends agree stay plain assertions. Scenarios where
D2 makes them diverge are marked ``xfail(strict=True, ...)``: the suite stays
green while the drift exists and fails (XPASS) the moment a fix lands, so the
mark must be removed together with the fix.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import re

import pytest

from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.session.pocketbase_store import PocketBaseSessionStore
from deeptutor.services.session.sqlite_store import SQLiteSessionStore

pytestmark = pytest.mark.asyncio

_VIEW_FIELDS = ("status", "active_turn_id", "capability")

_D2_REASON = (
    "the PocketBase sessions record keeps its create-time status/capability "
    "forever, so reads diverge from the SQLite derived view after any turn "
    "activity"
)


# ---------------------------------------------------------------------------
# In-memory fake of the PocketBase SDK (equality filters + sort)
# ---------------------------------------------------------------------------


_CLAUSE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
_WORKSPACE = re.compile(r'preferences_json\.workspace_id=("(?:\\.|[^"\\])*"|null)')


class _Record:
    def __init__(self, pb_id: str, data: dict) -> None:
        self.id = pb_id
        for key, value in data.items():
            setattr(self, key, value)


class _Result:
    def __init__(self, items: list[_Record], total_items: int) -> None:
        self.items = items
        self.total_items = total_items


class _Collection:
    def __init__(self) -> None:
        self._rows: list[_Record] = []
        self._seq = 0

    def _matches(self, record: _Record, query_params: dict | None) -> bool:
        flt = (query_params or {}).get("filter") or ""
        for raw in _WORKSPACE.findall(flt):
            expected = json.loads(raw) or ""
            prefs = getattr(record, "preferences_json", None)
            if isinstance(prefs, str):
                prefs = json.loads(prefs or "{}")
            if str((prefs or {}).get("workspace_id") or "") != expected:
                return False
        flt = _WORKSPACE.sub("", flt)
        for field, expected in _CLAUSE.findall(flt):
            if str(getattr(record, field, "")) != expected:
                return False
        return True

    @staticmethod
    def _sorted(rows: list[_Record], query_params: dict | None) -> list[_Record]:
        sort = str((query_params or {}).get("sort") or "")
        for part in reversed(sort.split(",")):
            if not part:
                continue
            field = part.lstrip("-")
            rows = sorted(rows, key=lambda r: getattr(r, field, 0), reverse=part.startswith("-"))
        return rows

    def create(self, data: dict) -> _Record:
        self._seq += 1
        record = _Record(f"pb{self._seq:04d}", data)
        self._rows.append(record)
        return record

    def get_full_list(self, query_params: dict | None = None) -> list[_Record]:
        matched = [r for r in self._rows if self._matches(r, query_params)]
        return self._sorted(matched, query_params)

    def get_list(self, page: int, per_page: int, query_params: dict | None = None) -> _Result:
        matched = self.get_full_list(query_params)
        start = (page - 1) * per_page
        return _Result(matched[start : start + per_page], len(matched))

    def update(self, pb_id: str, data: dict) -> _Record:
        record = next(r for r in self._rows if r.id == pb_id)
        for key, value in data.items():
            setattr(record, key, value)
        return record


class _FakeClient:
    def __init__(self) -> None:
        self._collections: dict[str, _Collection] = {}

    def collection(self, name: str) -> _Collection:
        return self._collections.setdefault(name, _Collection())


@pytest.fixture
def fake_pb(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(
        "deeptutor.services.pocketbase_client.get_pb_client", lambda: client, raising=True
    )
    return client


@contextmanager
def _as_user(uid: str, root: Path):
    scope = UserScope(kind="user", user_id=uid, root=root)
    token = set_current_user(CurrentUser(id=uid, username=uid, role="user", scope=scope))
    try:
        yield
    finally:
        reset_current_user(token)


# ---------------------------------------------------------------------------
# Shared operation scripts replayed on both backends
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    kind: str  # "begin" or "transition"
    capability: str = ""
    status: str = ""
    turn_id: str = ""
    pause: float = 0.0


@dataclass(frozen=True)
class Scenario:
    name: str
    steps: tuple[Step, ...]


_SCENARIOS: tuple[Scenario, ...] = (
    Scenario("fresh_create", ()),
    Scenario("turn_running", (Step("begin", capability="chat", turn_id="turn_1"),)),
    Scenario(
        "turn_awaits_input_then_resumes",
        (
            Step("begin", capability="chat", turn_id="turn_1"),
            Step("transition", status="waiting_input"),
            Step("transition", status="running"),
        ),
    ),
    Scenario(
        "turn_completed",
        (
            Step("begin", capability="chat", turn_id="turn_1"),
            Step("transition", status="completed"),
        ),
    ),
    Scenario(
        "turn_failed",
        (
            Step("begin", capability="chat", turn_id="turn_1"),
            Step("transition", status="failed"),
        ),
    ),
    Scenario(
        "turn_cancelled",
        (
            Step("begin", capability="chat", turn_id="turn_1"),
            Step("transition", status="cancelled"),
        ),
    ),
    Scenario(
        "second_turn_capability_wins",
        (
            Step("begin", capability="chat", turn_id="turn_1"),
            Step("transition", status="completed"),
            Step("begin", capability="mastery", turn_id="turn_2", pause=0.01),
            Step("transition", status="completed"),
        ),
    ),
)

#: Scenarios whose session-level views stay identical across the two backends.
#: Everything else diverges under D2 once a turn exists.
_CONSISTENT_SCENARIOS = frozenset({"fresh_create"})


async def _session_views(store, session_id: str) -> dict[str, tuple[str, str, str]]:
    session = await store.get_session(session_id)
    assert session is not None, f"session {session_id} missing"
    summaries = await store.get_session_summaries([session_id])
    assert len(summaries) == 1, "exactly one summary expected"
    return {
        "get_session": tuple(session[field] for field in _VIEW_FIELDS),
        "summaries": tuple(summaries[0][field] for field in _VIEW_FIELDS),
    }


async def _replay(store, session_id: str, steps: tuple[Step, ...]) -> dict:
    views = {"after_create": await _session_views(store, session_id)}
    active_turn = ""
    for index, step in enumerate(steps):
        if step.pause:
            await asyncio.sleep(step.pause)
        if step.kind == "begin":
            turn = await store.begin_turn(
                session_id, capability=step.capability, turn_id=step.turn_id
            )
            active_turn = turn["id"]
        else:
            assert await store.transition_turn(active_turn, step.status), (
                f"transition to {step.status} failed"
            )
        views[f"step_{index}_{step.kind}_{step.status or step.capability}"] = await _session_views(
            store, session_id
        )
    return views


async def _replay_sqlite(tmp_path: Path, scenario: Scenario) -> dict:
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    session = await store.create_session(title="d2 probe", session_id="sess_d2")
    return await _replay(store, session["id"], scenario.steps)


async def _replay_pocketbase(fake_pb, tmp_path: Path, scenario: Scenario) -> dict:
    store = PocketBaseSessionStore()
    with _as_user("d2-user", tmp_path / "d2-user"):
        session = await store.create_session(title="d2 probe", session_id="sess_d2")
        return await _replay(store, session["id"], scenario.steps)


# ---------------------------------------------------------------------------
# Dual-backend table-driven comparison
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param(
            item,
            id=item.name,
            marks=[]
            if item.name in _CONSISTENT_SCENARIOS
            else [pytest.mark.xfail(strict=True, reason=_D2_REASON)],
        )
        for item in _SCENARIOS
    ],
)
async def test_session_views_agree_across_backends(scenario, tmp_path, fake_pb) -> None:
    sqlite_views = await _replay_sqlite(tmp_path, scenario)
    pocketbase_views = await _replay_pocketbase(fake_pb, tmp_path, scenario)

    assert set(sqlite_views) == set(pocketbase_views)
    diverged = {
        checkpoint: {"sqlite": sqlite_views[checkpoint], "pocketbase": pocketbase_views[checkpoint]}
        for checkpoint in sqlite_views
        if sqlite_views[checkpoint] != pocketbase_views[checkpoint]
    }
    assert not diverged, f"session views diverged across backends: {diverged!r}"


# ---------------------------------------------------------------------------
# Single-backend pins that attribute any dual-backend divergence to D2
# ---------------------------------------------------------------------------


async def test_sqlite_derives_session_status_from_turns(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    await store.create_session(session_id="sess_sqlite")

    fresh = await store.get_session("sess_sqlite")
    assert (fresh["status"], fresh["active_turn_id"], fresh["capability"]) == ("idle", "", "")

    await store.begin_turn("sess_sqlite", capability="chat", turn_id="turn_1")
    running = await store.get_session("sess_sqlite")
    assert (running["status"], running["active_turn_id"], running["capability"]) == (
        "running",
        "turn_1",
        "chat",
    )
    await store.transition_turn("turn_1", "waiting_input")
    waiting = await store.get_session("sess_sqlite")
    assert (waiting["status"], waiting["active_turn_id"], waiting["capability"]) == (
        "waiting_input",
        "turn_1",
        "chat",
    )

    await store.transition_turn("turn_1", "completed")
    completed = await store.get_session("sess_sqlite")
    assert (completed["status"], completed["active_turn_id"], completed["capability"]) == (
        "completed",
        "",
        "chat",
    )


async def test_pocketbase_session_columns_are_only_written_at_create(fake_pb, tmp_path) -> None:
    store = PocketBaseSessionStore()
    with _as_user("d2-user", tmp_path / "d2-user"):
        await store.create_session(session_id="sess_pb")
        turn = await store.begin_turn("sess_pb", capability="chat", turn_id="turn_1")
        assert turn["status"] == "running"
        assert await store.transition_turn("turn_1", "completed")

    [session_row] = fake_pb.collection("sessions").get_full_list()
    assert session_row.status == "idle"
    assert session_row.capability == ""

    [turn_row] = fake_pb.collection("turns").get_full_list()
    assert turn_row.status == "completed"
    assert turn_row.capability == "chat"
