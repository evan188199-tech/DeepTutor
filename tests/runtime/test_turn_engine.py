"""Contract tests for the shared turn engine (deeptutor/runtime/turn_engine.py)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.runtime import turn_engine
from deeptutor.runtime.turn_engine import TurnEngine, get_turn_engine


def _event(content: str) -> StreamEvent:
    return StreamEvent(type=StreamEventType.CONTENT, content=content)


class _FakeOrchestrator:
    """Records construction/invocation and replays queued events."""

    construction_kwargs: list[dict[str, Any]] = []
    handle_calls: list[Any] = []
    events: list[StreamEvent] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _FakeOrchestrator.construction_kwargs.append({"args": args, "kwargs": kwargs})

    def handle(self, context: Any) -> Any:
        _FakeOrchestrator.handle_calls.append(context)

        async def _stream() -> Any:
            for event in _FakeOrchestrator.events:
                yield event

        return _stream()

    @staticmethod
    def reset(events: list[StreamEvent] | None = None) -> None:
        _FakeOrchestrator.construction_kwargs = []
        _FakeOrchestrator.handle_calls = []
        _FakeOrchestrator.events = events or []


# ---------------------------------------------------------------------------
# Singleton contract
# ---------------------------------------------------------------------------


def test_get_turn_engine_returns_stable_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = TurnEngine()
    monkeypatch.setattr(turn_engine, "_default_engine", engine)
    assert get_turn_engine() is engine
    assert get_turn_engine() is engine


def test_get_turn_engine_recreates_after_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(turn_engine, "_default_engine", None)
    first = get_turn_engine()
    assert isinstance(first, TurnEngine)
    assert get_turn_engine() is first
    monkeypatch.setattr(turn_engine, "_default_engine", None)
    second = get_turn_engine()
    assert second is not first


def test_engine_stores_capability_registry_reference() -> None:
    registry = object()
    assert TurnEngine(registry).capability_registry is registry
    assert TurnEngine().capability_registry is None


# ---------------------------------------------------------------------------
# Delegation contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_delegates_to_orchestrator_without_registry() -> None:
    _FakeOrchestrator.reset(events=[_event("a"), _event("b")])
    with patch("deeptutor.runtime.orchestrator.ChatOrchestrator", _FakeOrchestrator):
        engine = TurnEngine()
        context = {"session_id": "s1", "user_message": "hi"}
        yielded = [event async for event in engine.execute(context)]  # type: ignore[arg-type]

    assert [event.content for event in yielded] == ["a", "b"]
    assert len(_FakeOrchestrator.construction_kwargs) == 1
    construction = _FakeOrchestrator.construction_kwargs[0]
    assert construction["args"] == () and construction["kwargs"] == {}
    assert _FakeOrchestrator.handle_calls == [context]


@pytest.mark.asyncio
async def test_execute_forwards_capability_registry() -> None:
    _FakeOrchestrator.reset(events=[_event("x")])
    registry = object()
    with patch("deeptutor.runtime.orchestrator.ChatOrchestrator", _FakeOrchestrator):
        yielded = [
            event
            async for event in TurnEngine(registry).execute(object())  # type: ignore[arg-type]
        ]

    assert len(yielded) == 1
    construction = _FakeOrchestrator.construction_kwargs[0]
    assert construction["args"] == ()
    assert construction["kwargs"] == {"capability_registry": registry}


@pytest.mark.asyncio
async def test_execute_relays_events_in_stream_order() -> None:
    events = [_event(f"chunk-{i}") for i in range(5)]
    _FakeOrchestrator.reset(events=events)
    with patch("deeptutor.runtime.orchestrator.ChatOrchestrator", _FakeOrchestrator):
        yielded = [event async for event in TurnEngine().execute(object())]  # type: ignore[arg-type]

    assert yielded == events
    assert yielded[0].type is StreamEventType.CONTENT


# ---------------------------------------------------------------------------
# Malformed / edge input tolerance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_passes_malformed_context_through_uninspected() -> None:
    """The engine never inspects the context: arbitrary objects flow through as-is."""
    _FakeOrchestrator.reset()
    odd_inputs: list[Any] = [None, 42, {"unexpected": "shape"}, object()]
    with patch("deeptutor.runtime.orchestrator.ChatOrchestrator", _FakeOrchestrator):
        for odd in odd_inputs:
            yielded = [event async for event in TurnEngine().execute(odd)]
            assert yielded == []

    assert _FakeOrchestrator.handle_calls == odd_inputs
    assert _FakeOrchestrator.handle_calls[0] is odd_inputs[0]
    assert _FakeOrchestrator.handle_calls[2] is odd_inputs[2]


@pytest.mark.asyncio
async def test_execute_survives_empty_orchestrator_stream() -> None:
    _FakeOrchestrator.reset()
    with patch("deeptutor.runtime.orchestrator.ChatOrchestrator", _FakeOrchestrator):
        consumed = False
        async for _ in TurnEngine().execute(object()):  # type: ignore[arg-type]
            consumed = True
    assert consumed is False


@pytest.mark.asyncio
async def test_execute_propagates_orchestrator_failure_without_wrapping() -> None:
    class _ExplodingOrchestrator:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def handle(self, context: Any) -> Any:
            async def _stream() -> Any:
                yield _event("partial")
                raise RuntimeError("orchestrator exploded")

            return _stream()

    with patch("deeptutor.runtime.orchestrator.ChatOrchestrator", _ExplodingOrchestrator):
        engine = TurnEngine()
        agen = engine.execute(object())  # type: ignore[arg-type]
        first = await agen.__anext__()
        assert first.content == "partial"
        with pytest.raises(RuntimeError, match="orchestrator exploded"):
            await agen.__anext__()
