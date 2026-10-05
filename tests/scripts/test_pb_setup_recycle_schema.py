"""The PocketBase bootstrap schema must back the recycle-bin contract.

``PocketBaseSessionStore`` implements the recycle bin on a single
``sessions.deleted_at`` column: soft-delete/restore write it, the active-list
filter compares it against ``null``, and the bin listing sorts by it. None of
that works when ``scripts/pb_setup.py`` creates the sessions collection
without the field — on a freshly bootstrapped server the ``deleted_at = null``
filter is rejected and soft-delete writes are dropped, so the bin stays empty.

These tests rebuild the bootstrap schema exactly as ``pb_setup.main()`` would
submit it (extracted via ``ast`` so the script's import-time settings load is
never executed) and drive the store against an in-memory PocketBase stand-in
that enforces two server behaviours the lenient fakes elsewhere don't:

- filters referencing a field missing from the collection schema fail, and
- writes of unknown fields are silently dropped.

No real PocketBase server is started.
"""

from __future__ import annotations

import ast
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

import pytest

from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.session.pocketbase_store import PocketBaseSessionStore

pytestmark = pytest.mark.asyncio

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "pb_setup.py"
_COMPARE = re.compile(r'([A-Za-z_][A-Za-z0-9_.]*)\s*=\s*("(?:\\.|[^"\\])*"|null)')
_SYSTEM_FIELDS = frozenset({"id", "created", "updated", "collectionId", "collectionName"})
_RECYCLE_INDEX_HINT = "idx_sessions_user_deleted"


@contextmanager
def as_user(uid: str):
    scope = UserScope(kind="user", user_id=uid, root=Path("/tmp") / uid)  # noqa: S108
    token = set_current_user(CurrentUser(id=uid, username=uid, role="user", scope=scope))
    try:
        yield
    finally:
        reset_current_user(token)


def _bootstrap_collections() -> list[dict]:
    """Return the collection schemas ``pb_setup.main()`` submits, unexecuted."""
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "collections" for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("collections list not found in scripts/pb_setup.py")


def _sessions_schema() -> dict:
    return next(item for item in _bootstrap_collections() if item["name"] == "sessions")


class _UnknownField(Exception):
    """Analog of PocketBase rejecting a filter over an unknown column."""


class _StrictCollection:
    """In-memory collection whose reads/writes obey the bootstrap schema."""

    def __init__(self, schema: dict) -> None:
        self._fields = {field["name"] for field in schema.get("schema", [])} | _SYSTEM_FIELDS
        self._rows: list[SimpleNamespace] = []
        self._seq = 0

    def _actual(self, row: SimpleNamespace, field: str):
        value = getattr(row, field.split(".")[0], None)
        for part in field.split(".")[1:]:
            value = value.get(part) if isinstance(value, dict) else None
        return value

    def _substitute(self, flt: str, row: SimpleNamespace) -> str:
        def replace(match: re.Match) -> str:
            field, raw = match.group(1), match.group(2)
            if field.split(".")[0] not in self._fields:
                raise _UnknownField(field)
            actual = self._actual(row, field)
            if raw == "null":
                return str(actual is None or actual == "")
            return str(actual == json.loads(raw) or str(actual) == json.loads(raw))

        return _COMPARE.sub(replace, flt)

    def _matches(self, row: SimpleNamespace, query_params: dict | None) -> bool:
        flt = str((query_params or {}).get("filter") or "")
        if not flt:
            return True
        expression = self._substitute(flt, row).replace("&&", " and ").replace("||", " or ")
        assert re.fullmatch(r"[()TrueFalsandor ]+", expression), expression
        return bool(eval(expression, {"__builtins__": {}}, {}))  # noqa: S307

    def _drop_unknown(self, data: dict) -> dict:
        # PocketBase ignores submitted keys that are not collection fields.
        return {key: value for key, value in data.items() if key in self._fields}

    def create(self, data: dict) -> SimpleNamespace:
        self._seq += 1
        row = SimpleNamespace(id=f"pb{self._seq:04d}", **self._drop_unknown(data))
        self._rows.append(row)
        return row

    def update(self, pb_id: str, data: dict) -> SimpleNamespace:
        row = next(row for row in self._rows if row.id == pb_id)
        for key, value in self._drop_unknown(data).items():
            setattr(row, key, value)
        return row

    def get_full_list(self, query_params: dict | None = None) -> list[SimpleNamespace]:
        return [row for row in self._rows if self._matches(row, query_params)]

    def get_list(self, page: int, per_page: int, query_params: dict | None = None):
        matched = self.get_full_list(query_params)
        sort = str((query_params or {}).get("sort") or "")
        for part in reversed(sort.split(",")):
            if not part:
                continue
            field = part.lstrip("-")
            matched.sort(
                key=lambda row: getattr(row, field, row.id),
                reverse=part.startswith("-"),
            )
        start = (page - 1) * per_page
        return SimpleNamespace(items=matched[start : start + per_page], total_items=len(matched))


class _FreshBootstrapClient:
    """PocketBase stand-in whose collections come from the bootstrap schemas."""

    def __init__(self, schemas: list[dict]) -> None:
        self._collections = {schema["name"]: _StrictCollection(schema) for schema in schemas}

    def collection(self, name: str) -> _StrictCollection:
        return self._collections.setdefault(name, _StrictCollection({"name": name, "schema": []}))


@pytest.fixture
def fresh_pb(monkeypatch):
    client = _FreshBootstrapClient(_bootstrap_collections())
    monkeypatch.setattr(
        "deeptutor.services.pocketbase_client.get_pb_client", lambda: client, raising=True
    )
    return client


def test_sessions_schema_declares_recycle_bin_column_and_index() -> None:
    schema = _sessions_schema()
    fields = {field["name"]: field for field in schema["schema"]}
    assert fields["deleted_at"] == {"name": "deleted_at", "type": "number", "required": False}
    assert any(
        _RECYCLE_INDEX_HINT in index and "deleted_at" in index
        for index in schema.get("indexes", [])
    )


async def test_fresh_bootstrap_supports_soft_delete_restore_and_bin(fresh_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(title="Kept", session_id="s_kept")
        await store.create_session(title="Recycled", session_id="s_bin")

        assert await store.soft_delete_session("s_bin") is True

        # The active listing filters ``deleted_at = null`` server-side; on a
        # schema without the column that filter fails and the sidebar empties.
        assert [row["session_id"] for row in await store.list_sessions()] == ["s_kept"]
        assert await store.get_session("s_bin") is None

        bin_rows = await store.list_deleted_sessions()
        assert [row["session_id"] for row in bin_rows] == ["s_bin"]
        assert bin_rows[0]["is_deleted"] is True
        assert bin_rows[0]["deleted_at"] is not None

        assert await store.restore_session("s_bin") is True
        assert await store.get_session("s_bin") is not None
        assert await store.list_deleted_sessions() == []
        assert {row["session_id"] for row in await store.list_sessions()} == {
            "s_kept",
            "s_bin",
        }


def _load_pb_setup(monkeypatch):
    import deeptutor.services.config as config_module

    monkeypatch.setattr(
        config_module,
        "load_integrations_settings",
        lambda: {
            "pocketbase_url": "http://pocketbase.test",
            "pocketbase_admin_email": "admin@test",
            "pocketbase_admin_password": "secret",
        },
    )
    module_name = "pb_setup_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_rerun_appends_recycle_column_to_legacy_collection(monkeypatch) -> None:
    """Deployments bootstrapped before this field heal on a pb_setup re-run."""
    pb_setup = _load_pb_setup(monkeypatch)
    legacy_fields = [
        {"name": "session_id", "type": "text", "required": True},
        {"name": "user_id", "type": "text", "required": False},
        {"name": "session_updated_at", "type": "number", "required": False},
    ]
    record = SimpleNamespace(
        id="rec_sessions",
        name="sessions",
        schema=[SimpleNamespace(**field) for field in legacy_fields],
        indexes=["CREATE INDEX idx_sessions_legacy ON sessions (user_id)"],
    )
    collections_api = SimpleNamespace(get_full_list=lambda: [record], updates=[], update=None)
    collections_api.update = lambda rid, payload: collections_api.updates.append((rid, payload))
    pb = SimpleNamespace(collections=collections_api)

    pb_setup._sync_existing_collection(pb, _sessions_schema())

    schemas_written = [payload["schema"] for _, payload in collections_api.updates]
    assert any(
        {"name": "deleted_at", "type": "number", "required": False} in schema
        and {"name": "session_id", "type": "text", "required": True} in schema
        for schema in schemas_written
    ), schemas_written
    indexes_written = [payload["indexes"] for _, payload in collections_api.updates]
    assert any(
        any(_RECYCLE_INDEX_HINT in index for index in indexes) for indexes in indexes_written
    ), indexes_written
