"""Regression pinning the message parent-chain default asymmetry (D3).

Source: the session-schema-drift-20261005 report (§2.2, finding D3). This
file pins the CURRENT per-backend contract — it deliberately does not unify
the semantics.

Contract being locked in:

- SQLite (``deeptutor/services/session/sqlite_store.py:1899-1924``):
  ``add_message`` defaults ``parent_message_id`` to the ``_PARENT_AUTO``
  sentinel. An omitted parent auto-chains off the latest row in the session
  (``None`` for the very first message), so the linear thread stays
  connected. The parent lives in a real ``parent_message_id`` column and
  ``get_messages`` ALWAYS returns the key (``None`` marks a root, ints
  otherwise). Explicit ``None`` means "attach at the session root" and is
  distinct from omitting the argument — the sentinel exists exactly for
  that distinction.

- PocketBase (``deeptutor/services/session/pocketbase_store.py:45-47,
  867-873, 1207-1224``): ``add_message`` defaults to ``None`` and no chain
  is written at all. The collection has no parent column; when a parent IS
  passed it is hidden under the ``_parent_message_id`` key inside
  ``metadata_json`` (as a string) and re-surfaced on read. Root messages
  simply LACK the ``parent_message_id`` key, and because the default is
  plain ``None`` (no sentinel), an explicit ``None`` is indistinguishable
  from omitting the argument — PB callers cannot pin a message to the root.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import re
import uuid

import pytest

from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.session.pocketbase_store import PocketBaseSessionStore
from deeptutor.services.session.sqlite_store import SQLiteSessionStore

pytestmark = pytest.mark.asyncio

# Parent designations used in the scenario seeds below.
_AUTO = object()  # omit parent_message_id entirely — the default path
_ROOT_EXPLICIT = "root"  # pass parent_message_id=None explicitly

_USER = "user"
_ASSISTANT = "assistant"

# (role, content, parent designation) per scenario, in append order. Parents
# reference an earlier message by content so the seeds stay id-agnostic.
_SEEDS = {
    # Explicitly parented messages chain on both backends — the one shape
    # the two stores agree on.
    "explicit": [
        (_USER, "q1", _AUTO),
        (_ASSISTANT, "a1", "q1"),
        (_USER, "q2", "a1"),
    ],
    # Omitted parent: SQLite auto-chains into a linear thread; PocketBase
    # writes no chain at all — every message stays a root.
    "default": [
        (_USER, "q1", _AUTO),
        (_ASSISTANT, "a1", _AUTO),
        (_USER, "q2", _AUTO),
    ],
    # First-message flow: the opening message is a root on both backends;
    # then an explicit None (the "edit the very first message" path) pins a
    # root on SQLite, and a following default append chains onto that latest
    # row — on PocketBase the explicit None is absorbed into the default and
    # nothing ever chains.
    "first message": [
        (_USER, "q1", _AUTO),
        (_ASSISTANT, "a1", _ROOT_EXPLICIT),
        (_USER, "q2", _AUTO),
    ],
}

# Expected parent chain shape per backend × scenario. Each entry is one of:
#   an int — index (in creation order) of the parent message
#   None  — key present, no parent (a pinned root)
#   "absent" — the parent_message_id key is missing from the read dict
_EXPECTED_SHAPES = {
    "sqlite": {
        # explicit parent → parent column; first message default → None;
        # explicit None → None; later default chains onto latest row (a1).
        "explicit": [None, 0, 1],
        "default": [None, 0, 1],
        "first message": [None, None, 1],
    },
    "pocketbase": {
        # Only explicitly passed parents chain (as strings via metadata);
        # omitted AND explicit-None parents both leave the key absent.
        "explicit": ["absent", 0, 1],
        "default": ["absent", "absent", "absent"],
        "first message": ["absent", "absent", "absent"],
    },
}


# ── PocketBase fake (in-memory, mirrors test_pocketbase_isolation.py) ──

_CLAUSE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


@contextmanager
def as_user(uid: str):
    scope = UserScope(kind="user", user_id=uid, root=Path("/tmp") / uid)  # noqa: S108
    token = set_current_user(CurrentUser(id=uid, username=uid, role="user", scope=scope))
    try:
        yield
    finally:
        reset_current_user(token)


class _Record:
    def __init__(self, pb_id: str, data: dict) -> None:
        self.id = pb_id
        for key, value in data.items():
            setattr(self, key, value)


class _Collection:
    """In-memory stand-in for a PocketBase collection (equality filters only)."""

    def __init__(self) -> None:
        self._rows: list[_Record] = []
        self._seq = 0

    def _matches(self, record: _Record, query_params: dict | None) -> bool:
        flt = (query_params or {}).get("filter") or ""
        workspace = re.search(r'preferences_json\.workspace_id=("(?:\\.|[^"\\])*"|null)', flt)
        if workspace:
            expected = json.loads(workspace.group(1)) or ""
            prefs = getattr(record, "preferences_json", {}) or {}
            if isinstance(prefs, str):
                prefs = json.loads(prefs)
            if (prefs.get("workspace_id") or "") != expected:
                return False
            flt = re.sub(r'preferences_json\.workspace_id=("(?:\\.|[^"\\])*"|null)', "", flt)
        for field, expected in _CLAUSE.findall(flt):
            if str(getattr(record, field, "")) != expected:
                return False
        return True

    def create(self, data: dict) -> _Record:
        self._seq += 1
        record = _Record(f"pb{self._seq:04d}", data)
        self._rows.append(record)
        return record

    def get_full_list(self, query_params: dict | None = None) -> list[_Record]:
        return [r for r in self._rows if self._matches(r, query_params)]

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


# ── Backend adapters: identical surface over both stores ─────────────


class _SqliteBackend:
    name = "sqlite"

    def __init__(self, tmp_path: Path) -> None:
        self.store = SQLiteSessionStore(db_path=tmp_path / "chain.db")

    async def create_session(self) -> str:
        return (await self.store.create_session())["id"]

    async def add_message(self, sid: str, role: str, content: str, parent_message_id=_AUTO) -> int:
        kwargs = {} if parent_message_id is _AUTO else {"parent_message_id": parent_message_id}
        return await self.store.add_message(sid, role, content, **kwargs)

    async def get_messages(self, sid: str) -> list[dict]:
        return await self.store.get_messages(sid)

    def raw_rows(self) -> list[dict]:
        return [dict(row) for row in self._raw_messages()]

    def _raw_messages(self):
        import sqlite3

        with sqlite3.connect(self.store.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute("SELECT * FROM messages ORDER BY id").fetchall()


class _PocketBaseBackend:
    name = "pocketbase"
    _uid = "d3tester"

    def __init__(self, client: _FakeClient) -> None:
        self._client = client
        self.store = PocketBaseSessionStore()

    async def create_session(self) -> str:
        with as_user(self._uid):
            session_id = f"s_{uuid.uuid4().hex[:8]}"
            return (await self.store.create_session(session_id=session_id))["id"]

    async def add_message(self, sid: str, role: str, content: str, parent_message_id=_AUTO) -> str:
        kwargs = {} if parent_message_id is _AUTO else {"parent_message_id": parent_message_id}
        with as_user(self._uid):
            return await self.store.add_message(sid, role, content, **kwargs)

    async def get_messages(self, sid: str) -> list[dict]:
        with as_user(self._uid):
            return await self.store.get_messages(sid)

    def raw_rows(self) -> list[dict]:
        return [
            {"id": r.id, "metadata_json": getattr(r, "metadata_json", None) or {}}
            for r in self._client.collection("messages").get_full_list()
        ]


@pytest.fixture(params=["sqlite", "pocketbase"])
def backend(request, tmp_path: Path, fake_pb):
    if request.param == "sqlite":
        return _SqliteBackend(tmp_path)
    return _PocketBaseBackend(fake_pb)


# ── Helpers ───────────────────────────────────────────────────────────


async def _seed(backend, spec) -> str:
    """Append the scenario's messages; parents resolve to earlier ids."""
    sid = await backend.create_session()
    ids_by_content: dict[str, int | str] = {}
    for role, content, parent in spec:
        if parent is _AUTO:
            kwargs = {}
        elif parent == _ROOT_EXPLICIT:
            kwargs = {"parent_message_id": None}
        else:
            kwargs = {"parent_message_id": ids_by_content[parent]}
        ids_by_content[content] = await backend.add_message(sid, role, content, **kwargs)
    return sid


def _shape(messages: list[dict]) -> list[int | None | str]:
    """Reduce messages to their parent-chain shape (see _EXPECTED_SHAPES)."""
    index_by_id = {m["id"]: i for i, m in enumerate(messages)}
    shape: list[int | None | str] = []
    for message in messages:
        if "parent_message_id" not in message:
            shape.append("absent")
        elif message["parent_message_id"] is None:
            shape.append(None)
        else:
            shape.append(index_by_id[message["parent_message_id"]])
    return shape


# ── The regression table ──────────────────────────────────────────────


@pytest.mark.parametrize("scenario", list(_SEEDS))
async def test_parent_chain_shape_matches_backend_contract(scenario, backend) -> None:
    """Each scenario × backend asserts the current chain shape (D3).

    The table in ``_EXPECTED_SHAPES`` is the pinned contract: identical
    shapes would mean the backends converged; a shape change here is a
    deliberate contract change, not an accident.
    """
    sid = await _seed(backend, _SEEDS[scenario])
    messages = await backend.get_messages(sid)

    assert [m["content"] for m in messages] == [spec[1] for spec in _SEEDS[scenario]]
    assert _shape(messages) == _EXPECTED_SHAPES[backend.name][scenario], (
        f"{backend.name} backend diverged from the pinned D3 contract for the {scenario!r} scenario"
    )


async def test_parent_value_types_follow_backend_ids(backend) -> None:
    """SQLite parents are its integer rowids; PB parents are its string ids."""
    sid = await _seed(backend, _SEEDS["explicit"])
    messages = await backend.get_messages(sid)

    child = messages[1]
    assert child["content"] == "a1"
    if backend.name == "sqlite":
        assert isinstance(child["parent_message_id"], int)
        assert isinstance(messages[0]["id"], int)
    else:
        assert isinstance(child["parent_message_id"], str)
        assert child["parent_message_id"] == messages[0]["id"]


async def test_chain_lives_in_metadata_on_pb_column_on_sqlite(backend) -> None:
    """Storage carrier: SQLite chains via a column (metadata untouched); PB
    hides the link under ``_parent_message_id`` inside ``metadata_json``."""
    sid = await _seed(backend, _SEEDS["explicit"])
    messages = await backend.get_messages(sid)
    rows = {row["id"]: row for row in backend.raw_rows()}

    if backend.name == "sqlite":
        for message in messages:
            assert message["metadata"] == {}
            assert "parent_message_id" in message
    else:
        # Only the explicitly parented rows carry the hidden key; it holds
        # the string record id of the parent and is popped from the
        # read-side metadata dict.
        for row_id, row in rows.items():
            message = next(m for m in messages if m["id"] == row_id)
            hidden = row["metadata_json"].get("_parent_message_id")
            if message["content"] == "q1":
                assert hidden is None
                assert "parent_message_id" not in message
            else:
                assert hidden == str(message["parent_message_id"])
                assert "_parent_message_id" not in message["metadata"]


async def test_pb_explicit_none_is_absorbed_by_default(backend) -> None:
    """Why the sentinel matters: SQLite distinguishes explicit-None (pinned
    root) from the auto default; PB's plain-None default cannot, so callers
    on PB have no way to attach a message at the session root."""
    sid = await _seed(backend, _SEEDS["first message"])
    messages = await backend.get_messages(sid)

    edited = messages[1]  # appended with parent_message_id=None explicitly
    if backend.name == "sqlite":
        assert edited["parent_message_id"] is None
    else:
        assert "parent_message_id" not in edited
        assert "_parent_message_id" not in backend.raw_rows()[1]["metadata_json"]
