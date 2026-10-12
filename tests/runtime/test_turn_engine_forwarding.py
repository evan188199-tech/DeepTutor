"""Tests for the shared TurnEngine execution and default-engine singleton."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.runtime import orchestrator as orchestrator_module
from deeptutor.runtime.turn_engine import TurnEngine, get_turn_engine


class FakeOrchestrator:
    """Records construction and replays a fixed event sequence."""

    instances: list["FakeOrchestrator"] = []
    init_kwargs: list[dict[str, Any]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
        self.handled: list[Any] = []
        FakeOrchestrator.instances.append(self)
        FakeOrchestrator.init_kwargs.append(kwargs)

    def handle(self, context: Any) -> AsyncIterator[StreamEvent]:
        self.handled.append(context)

        async def _events() -> AsyncIterator[StreamEvent]:
            for stage in ("a", "b"):
                yield StreamEvent(
                    type=StreamEventType.STAGE_START, stage=stage, source="chat"
                )

        return _events()


@pytest.fixture(autouse=True)
def _fake_orchestrator(monkeypatch: pytest.MonkeyPatch):
    FakeOrchestrator.instances = []
    FakeOrchestrator.init_kwargs = []
    monkeypatch.setattr(orchestrator_module, "ChatOrchestrator", FakeOrchestrator)
    yield FakeOrchestrator


class TestTurnEngineExecution:
    @pytest.mark.asyncio
    async def test_default_construction_passes_no_registry(self) -> None:
        engine = TurnEngine()
        context = UnifiedContext(session_id="s1", user_message="hi")

        events = [event.stage async for event in engine.execute(context)]

        assert events == ["a", "b"]
        assert len(FakeOrchestrator.instances) == 1
        assert FakeOrchestrator.init_kwargs[0] == {}
        assert FakeOrchestrator.instances[0].handled == [context]

    @pytest.mark.asyncio
    async def test_registry_is_forwarded_to_orchestrator(self) -> None:
        registry = object()
        engine = TurnEngine(capability_registry=registry)
        context = UnifiedContext(session_id="s2", user_message="run")

        events = [event async for event in engine.execute(context)]

        assert [event.stage for event in events] == ["a", "b"]
        assert FakeOrchestrator.init_kwargs[0] == {"capability_registry": registry}

    @pytest.mark.asyncio
    async def test_each_execution_builds_a_fresh_orchestrator(self) -> None:
        engine = TurnEngine()

        async for _ in engine.execute(UnifiedContext(session_id="s", user_message="1")):
            pass
        async for _ in engine.execute(UnifiedContext(session_id="s", user_message="2")):
            pass

        assert len(FakeOrchestrator.instances) == 2


class TestDefaultEngineSingleton:
    def test_get_turn_engine_returns_same_instance(self) -> None:
        first = get_turn_engine()
        second = get_turn_engine()
        assert first is second
        assert isinstance(first, TurnEngine)
        assert first.capability_registry is None
