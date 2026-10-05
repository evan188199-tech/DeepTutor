"""Contract tests for ``TurnRequestPreparer.start_turn``.

Covers the three admission categories named by the coverage-gaps Top15 scan:

- illegal input: the transport envelope and unknown fields are rejected by
  ``TurnRequest``; a session id that belongs to nobody is refused.
- missing context: account language default, optional-tool back-fill, and the
  non-admin LLM selection pinning; reading and selection-tutor context that
  reference missing resources are refused.
- dependency failures: policy/config permission errors surface as
  ``RuntimeError``, a denied coordination lease rejects the turn, and store or
  publish failures roll the turn back to ``failed`` and release the lease.

Everything runs against a real ``SQLiteSessionStore`` in a temporary
directory; long-running collaborators (workspace bindings, capability
catalogs, the run phase itself) are replaced with in-memory stubs.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import ValidationError
import pytest

from deeptutor.core.stream import StreamEvent
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turns.request_preparer import TurnRequestPreparer

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _TurnRecorderStore(SQLiteSessionStore):
    """Store that remembers the turns created through it.

    Hooking ``begin_turn`` covers both admission paths: the lease-less
    ``create_turn`` delegates here, and the coordinator path calls it directly.
    """

    def __init__(self, db_path: Path) -> None:
        super().__init__(db_path=db_path)
        self.created_turns: list[dict[str, Any]] = []

    async def begin_turn(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        turn = await super().begin_turn(*args, **kwargs)
        self.created_turns.append(turn)
        return turn


class _NoBeginTurnStore(_TurnRecorderStore):
    """Store whose turn table is unreachable, simulating a store outage."""

    async def begin_turn(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("store offline")


class _StubCoordinator:
    """Turn-lease coordination stand-in for the preparer's acquire path."""

    def __init__(self, *, grant: bool = True) -> None:
        self.grant = grant
        self.acquired: list[str] = []
        self.released: list[Any] = []

    async def acquire_turn(self, turn_id: str, session_id: str, owner_id: str):
        self.acquired.append(turn_id)
        if not self.grant:
            return None
        return SimpleNamespace(
            turn_id=turn_id,
            session_id=session_id,
            owner_id=owner_id,
            fencing_token=1,
        )

    async def release_turn(self, lease) -> None:
        self.released.append(lease)


class _Binding:
    def __init__(self, workspace_id: str) -> None:
        self.workspace_id = workspace_id


class _StubWorkspaceService:
    def __init__(self) -> None:
        self.general = _Binding("general-ws")
        self.session_bindings: list[str] = []

    def general_binding(self) -> _Binding:
        return self.general

    def validate_chat_binding(self, workspace_id: str, *, existing: bool = False) -> _Binding:
        return _Binding(workspace_id)

    def session_binding(self, session_id: str) -> _Binding:
        self.session_bindings.append(session_id)
        return _Binding(f"ws-for-{session_id}")


class _PreparerHarness(TurnRequestPreparer):
    """``TurnRequestPreparer`` with the run phase replaced by a recorder."""

    def __init__(self, store: SQLiteSessionStore, coordinator: Any | None = None) -> None:
        self.store = store
        self.coordinator = coordinator
        self.owner_id = "test-owner"
        self._coordination_scope = "test-scope"
        self._lock = asyncio.Lock()
        self._executions: dict[str, Any] = {}
        self.update_blocked = False
        self.publish_error: BaseException | None = None
        self.published: list[StreamEvent] = []
        self.launched: list[Any] = []

    async def _ensure_accepting_turns(self) -> None:
        return None

    def _turns_blocked_for_update_locked(self) -> bool:
        return self.update_blocked

    async def _publish_live_event(self, execution: Any, event: StreamEvent) -> dict[str, Any]:
        if self.publish_error is not None:
            raise self.publish_error
        self.published.append(event)
        return {}

    async def _run_turn(self, execution: Any) -> None:
        self.launched.append(execution)

    async def _coordinate_execution(self, execution: Any) -> None:
        return None


def patch_workspace_service(monkeypatch: pytest.MonkeyPatch) -> _StubWorkspaceService:
    """Replace the content-workspace service with an in-memory double."""
    service = _StubWorkspaceService()
    import deeptutor.services.workspace as workspace_pkg

    monkeypatch.setattr(workspace_pkg, "get_content_workspace_service", lambda: service)
    return service


def _base_payload(**extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "content": "Explain this concept",
        "language": "en",
        "tools": [],
        "auto_route": False,
    }
    payload.update(extra)
    return payload


async def _await_launched_task(preparer: _PreparerHarness, turn_id: str) -> None:
    task = preparer._executions[turn_id].task
    assert task is not None
    await task


async def _stored_preferences(store: SQLiteSessionStore, session_id: str) -> dict[str, Any]:
    session = await store.get_session(session_id)
    assert session is not None
    return session["preferences"]


@pytest.fixture
def store(tmp_path: Path) -> _TurnRecorderStore:
    return _TurnRecorderStore(tmp_path / "request-preparer.db")


@pytest.fixture
def preparer(store: _TurnRecorderStore, monkeypatch: pytest.MonkeyPatch) -> _PreparerHarness:
    patch_workspace_service(monkeypatch)
    return _PreparerHarness(store)


@pytest.fixture
def leased(
    store: _TurnRecorderStore, monkeypatch: pytest.MonkeyPatch
) -> tuple[_PreparerHarness, _StubCoordinator]:
    coordinator = _StubCoordinator()
    patch_workspace_service(monkeypatch)
    return _PreparerHarness(store, coordinator), coordinator


# ---------------------------------------------------------------------------
# Illegal input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_content_is_rejected_before_anything_is_persisted(
    preparer: _PreparerHarness, store: _TurnRecorderStore
) -> None:
    payload = _base_payload()
    del payload["content"]

    with pytest.raises(ValidationError):
        await preparer.start_turn(payload)

    assert preparer._executions == {}
    assert store.created_turns == []
    assert preparer.launched == []


@pytest.mark.asyncio
async def test_unknown_payload_field_is_rejected(
    preparer: _PreparerHarness, store: _TurnRecorderStore
) -> None:
    with pytest.raises(ValidationError):
        await preparer.start_turn(_base_payload(unknown_field=1))

    assert store.created_turns == []


@pytest.mark.asyncio
async def test_transport_type_envelope_is_stripped_not_rejected(
    preparer: _PreparerHarness,
) -> None:
    session, turn = await preparer.start_turn(_base_payload(type="turn"))

    await _await_launched_task(preparer, turn["id"])
    assert turn["session_id"] == session["id"]
    assert turn["capability"] == "chat"
    assert preparer._executions[turn["id"]].payload["content"] == "Explain this concept"


@pytest.mark.asyncio
async def test_unknown_session_id_is_rejected(
    preparer: _PreparerHarness, store: _TurnRecorderStore
) -> None:
    with pytest.raises(RuntimeError, match="Conversation not found in this workspace."):
        await preparer.start_turn(_base_payload(session_id="no-such-conversation"))

    assert store.created_turns == []
    assert preparer._executions == {}


# ---------------------------------------------------------------------------
# Missing context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_language_is_filled_from_the_account_default(
    preparer: _PreparerHarness,
    store: _TurnRecorderStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.settings import interface_settings

    monkeypatch.setattr(interface_settings, "get_response_language", lambda default="en": "ko")
    payload = _base_payload()
    del payload["language"]

    session, turn = await preparer.start_turn(payload)

    await _await_launched_task(preparer, turn["id"])
    assert preparer._executions[turn["id"]].payload["language"] == "ko"
    assert (await _stored_preferences(store, session["id"]))["language"] == "ko"


@pytest.mark.asyncio
async def test_missing_tools_are_backfilled_from_the_saved_preference(
    preparer: _PreparerHarness,
    store: _TurnRecorderStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.settings import interface_settings

    monkeypatch.setattr(interface_settings, "get_enabled_optional_tools", lambda: ["web_search"])
    payload = _base_payload()
    del payload["tools"]

    session, turn = await preparer.start_turn(payload)

    await _await_launched_task(preparer, turn["id"])
    assert preparer._executions[turn["id"]].payload["tools"] == ["web_search"]
    assert (await _stored_preferences(store, session["id"]))["tools"] == ["web_search"]


@pytest.mark.asyncio
async def test_non_admin_without_an_llm_grant_is_rejected(
    preparer: _PreparerHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.multi_user import context as mu_context
    from deeptutor.multi_user import model_access

    monkeypatch.setattr(
        mu_context,
        "get_current_user",
        lambda: SimpleNamespace(id="learner-1", is_admin=False),
    )
    monkeypatch.setattr(model_access, "has_capability_access", lambda capability: False)

    with pytest.raises(RuntimeError, match="No LLM model is assigned to your account"):
        await preparer.start_turn(_base_payload())


@pytest.mark.asyncio
async def test_non_admin_llm_selection_is_pinned_to_the_first_available_grant(
    preparer: _PreparerHarness,
    store: _TurnRecorderStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.multi_user import context as mu_context
    from deeptutor.multi_user import model_access, personal_models
    from deeptutor.services import config as config_pkg
    from deeptutor.services import model_selection

    monkeypatch.setattr(
        mu_context,
        "get_current_user",
        lambda: SimpleNamespace(id="learner-1", is_admin=False),
    )
    monkeypatch.setattr(model_access, "has_capability_access", lambda capability: True)
    monkeypatch.setattr(
        model_access,
        "redacted_model_access",
        lambda user_id: {
            "llm": [
                {"available": False, "profile_id": "p0", "model_id": "m0"},
                {"available": True, "profile_id": "p1", "model_id": "m1"},
            ]
        },
    )
    monkeypatch.setattr(personal_models, "merge_personal_llm_profiles", lambda catalog: catalog)
    monkeypatch.setattr(
        config_pkg, "get_model_catalog_service", lambda: SimpleNamespace(load=lambda: {})
    )
    applied: list[dict[str, str]] = []
    monkeypatch.setattr(
        model_selection,
        "apply_llm_selection_to_catalog",
        lambda catalog, selection: applied.append(selection.to_dict()),
    )

    session, turn = await preparer.start_turn(_base_payload())

    await _await_launched_task(preparer, turn["id"])
    pinned = {"profile_id": "p1", "model_id": "m1"}
    assert preparer._executions[turn["id"]].payload["llm_selection"] == pinned
    assert applied == [pinned]
    assert (await _stored_preferences(store, session["id"]))["llm_selection"] == pinned


@pytest.mark.asyncio
async def test_reading_turn_with_unknown_workspace_is_rejected(
    preparer: _PreparerHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    import deeptutor.reading as reading_pkg

    class _EmptyCatalog:
        def get_workspace(self, workspace_id: str) -> None:
            return None

    monkeypatch.setattr(reading_pkg, "ReadingCatalogStore", _EmptyCatalog)

    with pytest.raises(RuntimeError, match="The reading workspace is unavailable."):
        await preparer.start_turn(
            _base_payload(
                workspace_mode="immersive_reading",
                reading_workspace_id="rw-missing",
            )
        )


@pytest.mark.asyncio
async def test_reading_turn_with_material_outside_the_workspace_is_rejected(
    preparer: _PreparerHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    import deeptutor.reading as reading_pkg

    workspace = SimpleNamespace(
        active_material_id="mat-1",
        tabs=[SimpleNamespace(material=SimpleNamespace(material_id="mat-other"))],
    )

    class _Catalog:
        def get_workspace(self, workspace_id: str):
            return workspace

        def attach_session(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("attach_session must not run for a rejected material")

    monkeypatch.setattr(reading_pkg, "ReadingCatalogStore", _Catalog)

    with pytest.raises(RuntimeError, match="not part of this reading workspace"):
        await preparer.start_turn(
            _base_payload(
                workspace_mode="immersive_reading",
                reading_workspace_id="rw-1",
                reading_material_id="mat-1",
            )
        )


@pytest.mark.asyncio
async def test_selection_tutor_context_without_selected_text_is_rejected(
    preparer: _PreparerHarness, store: _TurnRecorderStore
) -> None:
    with pytest.raises(RuntimeError, match="Selection tutor context requires selected text"):
        await preparer.start_turn(
            _base_payload(selection_tutor_context={"parent_session_id": "s-1"})
        )

    assert store.created_turns == []


# ---------------------------------------------------------------------------
# Dependency failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_learning_policy_permission_error_surfaces_as_runtime_error(
    preparer: _PreparerHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.multi_user import learning_access

    def deny(payload: dict[str, Any]) -> dict[str, Any]:
        raise PermissionError("mode not allowed for this account")

    monkeypatch.setattr(learning_access, "apply_learning_policy", deny)

    with pytest.raises(RuntimeError, match="mode not allowed for this account") as excinfo:
        await preparer.start_turn(_base_payload())

    assert isinstance(excinfo.value.__cause__, PermissionError)


@pytest.mark.asyncio
async def test_capability_config_validation_error_surfaces_as_runtime_error(
    preparer: _PreparerHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.runtime import request_contracts

    def reject(capability: str, raw_config: dict[str, Any] | None) -> dict[str, Any]:
        raise ValueError("chat options are not valid for this capability")

    monkeypatch.setattr(request_contracts, "validate_capability_config", reject)

    with pytest.raises(RuntimeError, match="chat options are not valid for this capability"):
        await preparer.start_turn(_base_payload())


@pytest.mark.asyncio
async def test_invalid_llm_selection_value_error_surfaces_as_runtime_error(
    preparer: _PreparerHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    import deeptutor.services.session.turns.request_preparer as preparer_module

    def bad_selection(value: Any) -> dict[str, str] | None:
        raise ValueError("Invalid LLM selection: expected an object.")

    monkeypatch.setattr(preparer_module, "_llm_selection_dict", bad_selection)

    with pytest.raises(RuntimeError, match="Invalid LLM selection"):
        await preparer.start_turn(_base_payload())


@pytest.mark.asyncio
async def test_denied_coordination_lease_rejects_the_turn(
    store: _TurnRecorderStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator = _StubCoordinator(grant=False)
    patch_workspace_service(monkeypatch)
    preparer = _PreparerHarness(store, coordinator)

    with pytest.raises(RuntimeError, match="Session already has an active or recovering turn"):
        await preparer.start_turn(_base_payload())

    assert coordinator.acquired and not coordinator.released
    assert store.created_turns == []
    assert preparer._executions == {}


@pytest.mark.asyncio
async def test_store_failure_during_turn_creation_releases_the_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_workspace_service(monkeypatch)
    store = _NoBeginTurnStore(tmp_path / "request-preparer-store-offline.db")
    coordinator = _StubCoordinator()
    preparer = _PreparerHarness(store, coordinator)

    with pytest.raises(RuntimeError, match="store offline"):
        await preparer.start_turn(_base_payload())

    assert len(coordinator.acquired) == 1
    assert [lease.turn_id for lease in coordinator.released] == coordinator.acquired
    assert preparer._executions == {}


@pytest.mark.asyncio
async def test_publish_failure_fails_the_turn_and_releases_the_lease(
    store: _TurnRecorderStore,
    leased: tuple[_PreparerHarness, _StubCoordinator],
) -> None:
    preparer, coordinator = leased
    preparer.publish_error = RuntimeError("event bus down")

    with pytest.raises(RuntimeError, match="event bus down"):
        await preparer.start_turn(_base_payload())

    assert preparer._executions == {}
    assert [lease.turn_id for lease in coordinator.released] == coordinator.acquired
    persisted = await store.get_turn(store.created_turns[0]["id"])
    assert persisted is not None
    assert persisted["status"] == "failed"
    assert persisted["error"] == "event bus down"


@pytest.mark.asyncio
async def test_update_blocked_turn_is_failed_and_rejected(
    store: _TurnRecorderStore,
    leased: tuple[_PreparerHarness, _StubCoordinator],
) -> None:
    preparer, coordinator = leased
    preparer.update_blocked = True

    with pytest.raises(RuntimeError, match="DeepTutor is preparing an update"):
        await preparer.start_turn(_base_payload())

    assert preparer._executions == {}
    persisted = await store.get_turn(store.created_turns[0]["id"])
    assert persisted is not None
    assert persisted["status"] == "failed"
    assert persisted["failure_code"] == "rejected"
