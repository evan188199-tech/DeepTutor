"""End-to-end verification of the issue #1359 fix chain (#1373 + #1413).

Reproduces the reported scenario through the production wiring — a real
``TurnEngine`` delegating to a real ``ChatOrchestrator`` — with only the
capability, LLM config and context builder stubbed:

1. A homepage-chat turn parks on ``ask_user`` (the card appears).
2. The owning worker loses the in-memory reply queue (restart/disconnect)
   while the coordinator lease stays alive.
3. The learner clicks the card on another worker: the reply is accepted
   but can never be delivered.

The merged chain must then terminalize the parked turn (#1373), actually
cancel the parked capability and unregister its bus (#1413), publish the
terminal ``error`` + ``done`` pair, and leave the session free for the
next message instead of locking the main conversation.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deeptutor.app.service import TurnApplicationService
from deeptutor.core.capability_protocol import CapabilityManifest, TurnCapability
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.runtime.coordination import MemoryCoordinator
from deeptutor.runtime.stream_bus import get_bus
from deeptutor.runtime.turn_engine import TurnEngine
from deeptutor.services.path_service import PathService
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager


class _ContextBuilder:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def build(self, **_kwargs):
        return SimpleNamespace(
            conversation_history=[],
            conversation_summary="",
            context_text="",
            token_count=0,
            budget=0,
        )


class _AskUserChatCapability(TurnCapability):
    """Stands in for the chat capability: parks on ask_user when told to."""

    manifest = CapabilityManifest(
        name="chat", description="Parks on ask_user like homepage chat.", stages=["responding"]
    )

    def __init__(self) -> None:
        self.park = True
        self.awaiting_reply = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def run(self, context, stream) -> None:  # noqa: ANN001
        await stream.content("thinking", source=self.name)
        if not self.park:
            return
        await stream.emit(
            StreamEvent(type=StreamEventType.WAIT_FOR_INPUT, source=self.name, content="Continue?")
        )
        self.awaiting_reply.set()
        try:
            reply = await context.runtime.wait_for_user_reply()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        await stream.content(f"reply:{reply['text']}", source=self.name)


class _CapabilityRegistry:
    def __init__(self, capability) -> None:  # noqa: ANN001
        self._capability = capability

    def get(self, name: str):  # noqa: ANN202
        return self._capability if name == "chat" else None

    def list_capabilities(self) -> list[str]:
        return ["chat"]


def _application(store, runtime, coordinator) -> TurnApplicationService:
    return TurnApplicationService(
        SimpleNamespace(get=lambda: store),
        SimpleNamespace(get=lambda _store: runtime),
        coordinator,
    )


def _payload(session_id: str | None = None) -> dict:
    payload = {
        "content": "hello",
        "capability": "chat",
        "tools": [],
        "knowledge_bases": [],
        "attachments": [],
        "language": "en",
        "config": {},
    }
    if session_id:
        payload["session_id"] = session_id
    return payload


@pytest.fixture(autouse=True)
def _workspace_root(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Keep the runtime workspace binding local to the test process."""
    paths = PathService(workspace_root=tmp_path / "data")
    paths.ensure_all_directories()
    monkeypatch.setattr("deeptutor.multi_user.paths.get_account_path_service", lambda: paths)
    monkeypatch.setattr("deeptutor.services.workspace.service.get_path_service", lambda: paths)
    monkeypatch.setattr(
        "deeptutor.services.workspace.data_migration.get_account_path_service", lambda: paths
    )
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("DEEPTUTOR_WORKSPACE_ROOT", str(root))
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS", raising=False)


@pytest.fixture(autouse=True)
def _patch_event_bus():
    mock_bus = MagicMock()
    mock_bus.publish = AsyncMock()
    with patch("deeptutor.runtime.orchestrator.get_event_bus", return_value=mock_bus):
        yield
    from deeptutor.events.event_bus import EventBus

    EventBus.reset()


@pytest.mark.asyncio
async def test_session_recovers_after_ask_user_reply_queue_loss(monkeypatch, tmp_path) -> None:
    capability = _AskUserChatCapability()
    engine = TurnEngine(capability_registry=_CapabilityRegistry(capability))
    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", _ContextBuilder
    )
    coordinator = MemoryCoordinator(lease_ttl_seconds=5)
    path = tmp_path / "shared.sqlite3"
    store_a = SQLiteSessionStore(path)
    store_b = SQLiteSessionStore(path)
    runtime_a = TurnRuntimeManager(
        store_a, coordinator=coordinator, owner_id="worker-a", turn_engine=engine
    )
    runtime_b = TurnRuntimeManager(
        store_b, coordinator=coordinator, owner_id="worker-b", turn_engine=engine
    )
    app_a = _application(store_a, runtime_a, coordinator)
    app_b = _application(store_b, runtime_b, coordinator)

    # The turn parks on ask_user; the card is shown and the turn is persisted
    # as waiting_input.
    session, turn = await app_a.start_turn(_payload())
    await asyncio.wait_for(capability.awaiting_reply.wait(), timeout=2)
    active = None
    for _ in range(100):
        active = await app_b.check_active_turn(session["id"])
        if active and active["status"] == "waiting_input":
            break
        await asyncio.sleep(0.01)
    assert active is not None
    assert active["status"] == "waiting_input"

    # The owning worker restarts and loses the in-memory reply queue while the
    # coordinator lease stays alive; the learner's card click is then accepted
    # but can never be delivered.
    dropped_queue = runtime_a._reply_queues.pop(turn["id"])
    assert dropped_queue is not None
    accepted = await app_b.submit_user_reply(turn["id"], "yes", command_id="card-click-after-loss")
    assert accepted is True

    # The coordination loop terminalizes the parked turn (#1373) and the
    # orchestrator takes the parked capability down with it (#1413).
    persisted = None
    for _ in range(100):
        persisted = await store_b.get_turn(turn["id"])
        if persisted and persisted["status"] in {"completed", "failed", "cancelled"}:
            break
        await asyncio.sleep(0.02)
    assert persisted is not None
    assert persisted["status"] == "cancelled"
    assert capability.cancelled.is_set(), "the parked capability must actually stop"
    assert get_bus(turn["id"]) is None, "the turn bus must not leak into the registry"

    # The client sees the terminal error + done pair on the parked turn.
    events = []
    for _ in range(100):
        events = await store_b.get_turn_events(turn["id"])
        if events and events[-1]["type"] == "done":
            break
        await asyncio.sleep(0.02)
    event_types = [event["type"] for event in events]
    assert "error" in event_types
    assert event_types.count("done") == 1
    assert event_types.index("error") < event_types.index("done")
    assert event_types[-1] == "done"

    # The main conversation is free again: the next message on the same
    # session starts a new turn instead of conflicting with the parked one.
    capability.park = False
    _same_session, following = await app_b.start_turn(_payload(session_id=session["id"]))
    assert following["id"] != turn["id"]
    completed = None
    for _ in range(100):
        completed = await store_b.get_turn(following["id"])
        if completed and completed["status"] in {"completed", "failed", "cancelled"}:
            break
        await asyncio.sleep(0.02)
    assert completed is not None
    assert completed["status"] == "completed"

    await runtime_a.close()
    await runtime_b.close()
