"""Focused unit tests for ``deeptutor/app/facade.py``.

Covers facade initialization order (including container build failure),
capability resolution / turn dispatch, dependency-missing degradation, and
the exit-code branches of CLI commands that consume the facade. Everything
runs against fakes — no real backend, service, or network is started.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from typer.testing import CliRunner

from deeptutor.app import facade as facade_module
import deeptutor.app.container as container_module
from deeptutor.app.contracts import TurnRequest
from deeptutor.app.facade import CapabilityAvailability, DeepTutorApp, dumps_json
from deeptutor.runtime.coordination import RuntimeConfigurationError
from deeptutor.services.path_service import PathService
from deeptutor.services.workspace.models import WorkspaceError

# ---------------------------------------------------------------------------
# Fakes (mock backend)
# ---------------------------------------------------------------------------


class FakeTurns:
    """Stand-in for ``TurnApplicationService`` recording every dispatch."""

    def __init__(self) -> None:
        self.start_calls: list[dict] = []
        self.subscribed: list[tuple[str, int]] = []
        self.cancelled: list[str] = []
        self.replies: list[tuple[str, str | None, list | None]] = []
        self.renamed: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.listed: tuple[int, int] | None = None
        self.fetched: str | None = None
        self.active_checked: str | None = None
        self.regenerated: tuple[str, dict | None] | None = None
        self.stream_events: list[dict] = [{"type": "done"}]

    async def start_turn(self, payload: dict) -> tuple[dict, dict]:
        self.start_calls.append(payload)
        return {"id": "sess-1"}, {"id": "turn-1"}

    async def subscribe_turn(self, turn_id: str, after_seq: int = 0):
        self.subscribed.append((turn_id, after_seq))
        for item in self.stream_events:
            yield item

    async def cancel_turn(self, turn_id: str) -> bool:
        self.cancelled.append(turn_id)
        return True

    async def submit_user_reply(self, turn_id, text=None, answers=None) -> bool:
        self.replies.append((turn_id, text, answers))
        return True

    async def rename_session(self, session_id: str, title: str) -> bool:
        self.renamed.append((session_id, title))
        return True

    async def delete_session(self, session_id: str) -> bool:
        self.deleted.append(session_id)
        return True

    async def list_sessions(self, limit: int = 50, offset: int = 0) -> list[dict]:
        self.listed = (limit, offset)
        return [{"id": "sess-1", "title": "T"}]

    async def get_session(self, session_id: str):
        self.fetched = session_id
        return {"id": session_id, "title": "T"}

    async def check_active_turn(self, session_id: str):
        self.active_checked = session_id
        return None

    async def regenerate_last_turn(self, session_id: str, overrides=None):
        self.regenerated = (session_id, overrides)
        return {"id": "sess-1"}, {"id": "turn-2"}


class FakeRegistry:
    def __init__(self, manifests: list[dict] | None = None) -> None:
        self._manifests = manifests or [
            {"name": "chat", "cli_aliases": []},
            {"name": "math_animator", "cli_aliases": ["anim"]},
        ]

    def get_manifests(self) -> list[dict]:
        return [dict(manifest) for manifest in self._manifests]


class FakeContainer:
    def __init__(self) -> None:
        self.turns = FakeTurns()
        self.capability_registry = FakeRegistry()
        self.started = 0
        self.healthy = True

    async def start(self) -> None:
        if not self.healthy:
            raise RuntimeConfigurationError(
                "Turn coordination backend is unavailable; refusing to start"
            )
        self.started += 1


@dataclass
class FakeScope:
    workspace_id: str = ""
    archived: bool = False


@dataclass
class FakeNotebookManager:
    calls: list[str] = field(default_factory=list)

    def list_notebooks(self) -> list[dict]:
        self.calls.append("list")
        return [{"id": "nb-1", "name": "Reading", "record_count": 0}]

    def get_notebook(self, notebook_id: str):
        self.calls.append(f"get:{notebook_id}")
        return {"id": notebook_id, "name": "Reading", "records": []}

    def create_notebook(self, name: str, **kwargs) -> dict:
        self.calls.append(f"create:{name}")
        return {"id": "nb-1", "name": name, **kwargs}

    def add_record(self, **kwargs) -> dict:
        self.calls.append("add_record")
        return {"id": "rec-1", **kwargs}

    def update_record(self, notebook_id: str, record_id: str, **kwargs):
        self.calls.append(f"update:{notebook_id}:{record_id}")
        return {"id": record_id, **kwargs}

    def remove_record(self, notebook_id: str, record_id: str) -> bool:
        self.calls.append(f"remove:{notebook_id}:{record_id}")
        return True

    def get_records_by_references(self, notebook_references: list[dict]) -> list[dict]:
        self.calls.append(f"refs:{len(notebook_references)}")
        return [{"id": "rec-1"}]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _local_account_paths(tmp_path, monkeypatch: pytest.MonkeyPatch) -> PathService:
    """Keep workspace activity sqlite state inside the test's tmp tree."""
    paths = PathService(workspace_root=tmp_path / "data")
    paths.ensure_all_directories()
    monkeypatch.setattr("deeptutor.multi_user.paths.get_account_path_service", lambda: paths)
    monkeypatch.setattr(
        "deeptutor.services.workspace.data_migration.get_account_path_service", lambda: paths
    )
    return paths


@pytest.fixture
def fake_container(monkeypatch: pytest.MonkeyPatch) -> FakeContainer:
    container = FakeContainer()
    monkeypatch.setattr(facade_module, "get_application_container", lambda: container)
    return container


def install_fake_workspace_context(
    monkeypatch: pytest.MonkeyPatch, *, archived: bool = False, ambient: str = "ambient-ws"
) -> list[str]:
    """Patch workspace context helpers; returns the list of entered scope ids."""
    entered: list[str] = []

    @contextlib.contextmanager
    def fake_context(workspace_id=None):
        entered.append(str(workspace_id))
        yield FakeScope(workspace_id=str(workspace_id), archived=archived)

    monkeypatch.setattr("deeptutor.services.workspace.context.workspace_context", fake_context)
    monkeypatch.setattr(
        "deeptutor.services.workspace.context.current_workspace_id", lambda: ambient
    )
    return entered


# ---------------------------------------------------------------------------
# Facade initialization order / failure
# ---------------------------------------------------------------------------


def test_init_binds_container_turns_and_capabilities(fake_container) -> None:
    app = DeepTutorApp(workspace_id="ws-app")

    assert app.workspace_id == "ws-app"
    assert app.container is fake_container
    assert app.turns is fake_container.turns
    assert app.capabilities is fake_container.capability_registry
    assert app._turn_workspaces == {}


def test_init_instances_share_container_but_own_turn_map(fake_container) -> None:
    first = DeepTutorApp()
    second = DeepTutorApp()

    assert first.workspace_id is None
    assert second.workspace_id is None
    assert first.container is second.container is fake_container
    assert first._turn_workspaces == {}
    assert second._turn_workspaces == {}
    assert first._turn_workspaces is not second._turn_workspaces
    first._turn_workspaces["turn-x"] = "ws"
    assert second._turn_workspaces == {}


def test_get_application_container_builds_once_then_reuses(monkeypatch) -> None:
    sentinel = FakeContainer()
    builds: list[int] = []

    def fake_build(cls):
        builds.append(1)
        return sentinel

    monkeypatch.setattr(container_module.ApplicationContainer, "build", classmethod(fake_build))
    previous = container_module._default_container
    container_module.set_application_container(None)
    try:
        assert container_module.get_application_container() is sentinel
        assert container_module.get_application_container() is sentinel
        assert builds == [1]
    finally:
        container_module.set_application_container(previous)


def test_facade_init_fails_when_container_build_fails(monkeypatch) -> None:
    def failing_build(cls):
        raise RuntimeConfigurationError("no coordination backend configured")

    monkeypatch.setattr(
        container_module.ApplicationContainer, "build", classmethod(failing_build)
    )
    previous = container_module._default_container
    container_module.set_application_container(None)
    try:
        with pytest.raises(RuntimeConfigurationError):
            DeepTutorApp()
    finally:
        container_module.set_application_container(previous)


# ---------------------------------------------------------------------------
# Capability resolution and contracts (dispatch axis)
# ---------------------------------------------------------------------------


def test_resolve_capability_default_and_exact_name(fake_container) -> None:
    app = DeepTutorApp()

    assert app.resolve_capability(None) == "chat"
    assert app.resolve_capability("") == "chat"
    assert app.resolve_capability("   ") == "chat"
    assert app.resolve_capability("chat") == "chat"


def test_resolve_capability_maps_cli_alias_to_canonical_name(fake_container) -> None:
    app = DeepTutorApp()

    assert app.resolve_capability("anim") == "math_animator"


def test_resolve_capability_unknown_raises_with_sorted_available(fake_container) -> None:
    app = DeepTutorApp()

    with pytest.raises(ValueError) as excinfo:
        app.resolve_capability("bogus")
    message = str(excinfo.value)
    assert "Unknown capability `bogus`" in message
    assert "chat, math_animator" in message


def test_capability_availability_sweeps_every_manifest(fake_container) -> None:
    app = DeepTutorApp()

    availabilities = {
        manifest["name"]: app.get_capability_availability(manifest["name"])
        for manifest in app.capabilities.get_manifests()
    }

    assert set(availabilities) == {"chat", "math_animator"}
    assert availabilities["chat"] == CapabilityAvailability(
        name="chat", available=True, install_hint=""
    )
    assert availabilities["math_animator"].name == "math_animator"


# ---------------------------------------------------------------------------
# Dependency-missing degradation
# ---------------------------------------------------------------------------


def test_math_animator_missing_dependency_degrades_with_install_hint(
    fake_container, monkeypatch
) -> None:
    probes: list[str] = []

    def fake_find_spec(name, *args, **kwargs):
        probes.append(name)
        return None

    monkeypatch.setattr(facade_module.importlib.util, "find_spec", fake_find_spec)
    app = DeepTutorApp()

    availability = app.get_capability_availability("math_animator")

    assert isinstance(availability, CapabilityAvailability)
    assert availability.available is False
    assert "pip install" in availability.install_hint
    assert probes == ["manim"]


def test_math_animator_present_dependency_reports_available_without_hint(
    fake_container, monkeypatch
) -> None:
    monkeypatch.setattr(facade_module.importlib.util, "find_spec", lambda name: object())
    app = DeepTutorApp()

    availability = app.get_capability_availability("math_animator")

    assert availability.available is True
    assert availability.install_hint == ""


def test_non_optional_capability_available_without_dependency_probe(
    fake_container, monkeypatch
) -> None:
    probes: list[str] = []

    def spy_find_spec(name, *args, **kwargs):
        probes.append(name)
        return object()

    monkeypatch.setattr(facade_module.importlib.util, "find_spec", spy_find_spec)
    app = DeepTutorApp()

    availability = app.get_capability_availability("chat")

    assert availability.available is True
    assert availability.install_hint == ""
    assert probes == []


# ---------------------------------------------------------------------------
# Turn dispatch (start / stream / cancel / reply)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_turn_accepts_dict_resolves_alias_and_pins_workspace(
    fake_container, monkeypatch
) -> None:
    entered = install_fake_workspace_context(monkeypatch)
    app = DeepTutorApp(workspace_id="ws-app")

    session, turn = await app.start_turn({"content": "hello", "capability": "anim"})

    assert (session, turn) == ({"id": "sess-1"}, {"id": "turn-1"})
    payload = fake_container.turns.start_calls[0]
    assert payload["capability"] == "math_animator"
    assert payload["workspace_id"] == "ws-app"
    assert payload["content"] == "hello"
    assert app._turn_workspaces == {"turn-1": "ws-app"}
    assert fake_container.started == 1
    assert entered == ["ws-app"]


@pytest.mark.asyncio
async def test_start_turn_workspace_selection_precedence(
    fake_container, monkeypatch
) -> None:
    install_fake_workspace_context(monkeypatch)
    app = DeepTutorApp(workspace_id="ws-app")

    await app.start_turn(TurnRequest(content="hi", workspace_id="ws-req"))
    assert fake_container.turns.start_calls[-1]["workspace_id"] == "ws-req"

    await app.start_turn(TurnRequest(content="hi"))
    assert fake_container.turns.start_calls[-1]["workspace_id"] == "ws-app"


@pytest.mark.asyncio
async def test_backend_start_failure_blocks_turn_before_dispatch(
    fake_container, monkeypatch
) -> None:
    install_fake_workspace_context(monkeypatch)
    fake_container.healthy = False
    app = DeepTutorApp(workspace_id="ws-app")

    with pytest.raises(RuntimeConfigurationError, match="refusing to start"):
        await app.start_turn({"content": "hello"})

    assert fake_container.started == 0
    assert fake_container.turns.start_calls == []
    assert app._turn_workspaces == {}


@pytest.mark.asyncio
async def test_stream_and_cancel_route_via_mapped_turn_workspace(
    fake_container, monkeypatch
) -> None:
    install_fake_workspace_context(monkeypatch)
    app = DeepTutorApp(workspace_id="ws-app")
    await app.start_turn({"content": "hi"})

    events = [item async for item in app.stream_turn("turn-1", after_seq=3)]
    assert events == [{"type": "done"}]
    assert fake_container.turns.subscribed == [("turn-1", 3)]
    assert await app.cancel_turn("turn-1") is True
    assert fake_container.turns.cancelled == ["turn-1"]


@pytest.mark.asyncio
async def test_submit_user_reply_prefers_mapped_then_ambient_workspace(
    fake_container, monkeypatch
) -> None:
    entered = install_fake_workspace_context(monkeypatch, ambient="ambient-ws")
    app = DeepTutorApp()
    app._turn_workspaces["turn-9"] = "ws-seeded"

    assert await app.submit_user_reply("turn-9", text="answer") is True
    assert fake_container.turns.replies[0] == ("turn-9", "answer", None)
    assert entered[0] == "ws-seeded"

    assert await app.submit_user_reply("turn-unknown", answers=[{"questionId": "q1"}]) is True
    assert fake_container.turns.replies[1][2] == [{"questionId": "q1"}]
    assert entered[1] == "ambient-ws"


@pytest.mark.asyncio
async def test_session_read_and_mutation_methods_dispatch_to_backend(
    fake_container, monkeypatch
) -> None:
    install_fake_workspace_context(monkeypatch)
    app = DeepTutorApp(workspace_id="ws-app")

    sessions = await app.list_sessions(limit=5, offset=2)
    fetched = await app.get_session("sess-1")
    active = await app.get_active_turn("sess-1")
    deleted = await app.delete_session("sess-1")
    regen_session, regen_turn = await app.regenerate_last_turn("sess-1", {"temperature": 0})

    assert sessions == [{"id": "sess-1", "title": "T"}]
    assert fetched == {"id": "sess-1", "title": "T"}
    assert active is None
    assert deleted is True
    assert (regen_session, regen_turn) == ({"id": "sess-1"}, {"id": "turn-2"})
    assert fake_container.turns.listed == (5, 2)
    assert fake_container.turns.fetched == "sess-1"
    assert fake_container.turns.active_checked == "sess-1"
    assert fake_container.turns.deleted == ["sess-1"]
    assert fake_container.turns.regenerated == ("sess-1", {"temperature": 0})


def test_notebook_read_methods_delegate_to_manager(fake_container, monkeypatch) -> None:
    manager = FakeNotebookManager()
    monkeypatch.setattr(facade_module, "get_notebook_manager", lambda: manager)
    install_fake_workspace_context(monkeypatch)
    app = DeepTutorApp(workspace_id="ws-app")

    listed = app.list_notebooks()
    fetched = app.get_notebook("nb-1")
    records = app.get_records_by_references([{"notebook_id": "nb-1", "record_ids": ["rec-1"]}])

    assert listed[0]["name"] == "Reading"
    assert fetched["id"] == "nb-1"
    assert records == [{"id": "rec-1"}]
    assert manager.calls == ["list", "get:nb-1", "refs:1"]


def test_notebook_record_mutations_delegate_to_manager(fake_container, monkeypatch) -> None:
    manager = FakeNotebookManager()
    monkeypatch.setattr(facade_module, "get_notebook_manager", lambda: manager)
    install_fake_workspace_context(monkeypatch)
    app = DeepTutorApp(workspace_id="ws-app")

    added = app.add_record(notebook_ids=["nb-1"], record_type="chat", title="t")
    updated = app.update_record("nb-1", "rec-1", output="new")
    removed = app.remove_record("nb-1", "rec-1")

    assert added["id"] == "rec-1"
    assert updated == {"id": "rec-1", "output": "new"}
    assert removed is True
    assert manager.calls == ["add_record", "update:nb-1:rec-1", "remove:nb-1:rec-1"]


@pytest.mark.asyncio
async def test_start_turn_without_any_workspace_binding_uses_ambient_scope(
    fake_container, monkeypatch
) -> None:
    entered = install_fake_workspace_context(monkeypatch, ambient="ambient-ws")
    app = DeepTutorApp()

    await app.start_turn({"content": "hello"})

    assert fake_container.turns.start_calls[0]["workspace_id"] == "ambient-ws"
    assert app._turn_workspaces == {"turn-1": "ambient-ws"}
    assert entered == ["ambient-ws"]


# ---------------------------------------------------------------------------
# Workspace-scoped mutation gate (archived degradation)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archived_workspace_blocks_renames_before_backend_start(
    fake_container, monkeypatch
) -> None:
    install_fake_workspace_context(monkeypatch, archived=True)
    app = DeepTutorApp(workspace_id="ws-app")

    with pytest.raises(WorkspaceError, match="Restore this workspace"):
        await app.rename_session("sess-1", "renamed")

    assert fake_container.started == 0
    assert fake_container.turns.renamed == []


@pytest.mark.asyncio
async def test_active_workspace_rename_reaches_backend(fake_container, monkeypatch) -> None:
    install_fake_workspace_context(monkeypatch, archived=False)
    app = DeepTutorApp(workspace_id="ws-app")

    assert await app.rename_session("sess-1", "renamed") is True

    assert fake_container.started == 1
    assert fake_container.turns.renamed == [("sess-1", "renamed")]


@pytest.mark.asyncio
async def test_archived_workspace_blocks_notebook_creation_until_restored(
    fake_container, monkeypatch
) -> None:
    manager = FakeNotebookManager()
    monkeypatch.setattr(facade_module, "get_notebook_manager", lambda: manager)

    install_fake_workspace_context(monkeypatch, archived=True)
    app = DeepTutorApp(workspace_id="ws-app")
    with pytest.raises(WorkspaceError, match="Restore this workspace"):
        app.create_notebook("blocked")
    assert manager.calls == []

    install_fake_workspace_context(monkeypatch, archived=False)
    created = app.create_notebook("allowed", description="d")
    assert created["id"] == "nb-1"
    assert manager.calls == ["create:allowed"]


def test_notebooks_property_binds_manager_in_facade_workspace(
    fake_container, monkeypatch
) -> None:
    manager = FakeNotebookManager()
    monkeypatch.setattr(facade_module, "get_notebook_manager", lambda: manager)
    entered = install_fake_workspace_context(monkeypatch)
    app = DeepTutorApp(workspace_id="ws-app")

    assert app.notebooks is manager
    assert entered == ["ws-app"]


# ---------------------------------------------------------------------------
# Serialization helper
# ---------------------------------------------------------------------------


def test_dumps_json_keeps_unicode_and_stringifies_fallbacks() -> None:
    rendered = dumps_json({"name": "中文", "path": Path("/tmp/x")})

    assert "中文" in rendered
    assert rendered.startswith("{\n")
    assert '"/tmp/x"' in rendered


# ---------------------------------------------------------------------------
# CLI exit-code branches consuming the facade (mock backend)
# ---------------------------------------------------------------------------


def test_session_show_missing_session_exits_one(fake_container, monkeypatch) -> None:
    from deeptutor_cli.main import app as cli_app

    async def missing(self, session_id):
        return None

    monkeypatch.setattr(facade_module.DeepTutorApp, "get_session", missing)
    result = CliRunner().invoke(cli_app, ["session", "show", "ghost"])

    assert result.exit_code == 1
    assert "Session not found" in result.output


def test_session_rename_missing_session_exits_one(fake_container, monkeypatch) -> None:
    from deeptutor_cli.main import app as cli_app

    async def not_found(self, session_id, title):
        return False

    monkeypatch.setattr(facade_module.DeepTutorApp, "rename_session", not_found)
    result = CliRunner().invoke(cli_app, ["session", "rename", "ghost", "--title", "New"])

    assert result.exit_code == 1
    assert "Session not found" in result.output


def test_notebook_show_missing_notebook_exits_one(fake_container, monkeypatch) -> None:
    from deeptutor_cli.main import app as cli_app

    def missing(self, notebook_id):
        return None

    monkeypatch.setattr(facade_module.DeepTutorApp, "get_notebook", missing)
    result = CliRunner().invoke(cli_app, ["notebook", "show", "ghost"])

    assert result.exit_code == 1
    assert "Notebook not found" in result.output
