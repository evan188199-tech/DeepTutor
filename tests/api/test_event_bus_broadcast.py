"""Unit tests for the API process-wide event bus broadcast.

``deeptutor.api.main`` starts/stops the singleton ``EventBus`` for the whole
API process; every module broadcast flows through it. These tests pin the
delivery contract the API layer relies on:

* event serialization (``Event.to_dict`` must stay wire-serializable),
* subscriber exception isolation — one handler raising must not prevent the
  remaining subscribers (or later events) from being delivered,
* backpressure / drop policy — the queue is unbounded and retains events;
  ``flush`` surfaces a timeout instead of dropping, ``stop`` drains.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import json

import pytest
import pytest_asyncio

from deeptutor.events import event_bus as event_bus_module
from deeptutor.events.event_bus import Event, EventBus, EventType, get_event_bus


def _make_event(**overrides) -> Event:
    defaults = dict(
        type=EventType.SOLVE_COMPLETE,
        task_id="task-1",
        user_input="hello",
        agent_output="world",
        tools_used=["rag"],
        success=True,
        metadata={"kb": "demo"},
    )
    defaults.update(overrides)
    return Event(**defaults)


@pytest_asyncio.fixture
async def fresh_bus():
    """A pristine singleton per test — the class and module globals reset."""
    event_bus_module._event_bus = None
    EventBus.reset()
    bus = get_event_bus()
    yield bus
    await bus.stop()
    event_bus_module._event_bus = None
    EventBus.reset()


# ---------------------------------------------------------------------------
# Event serialization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_to_dict_serializes_enum_type_and_timestamp(fresh_bus) -> None:
    event = _make_event()

    payload = event.to_dict()

    assert payload["type"] == "SOLVE_COMPLETE"
    assert payload["timestamp"] == event.timestamp.isoformat()
    assert payload["event_id"] == event.event_id
    assert payload["task_id"] == "task-1"
    assert payload["user_input"] == "hello"
    assert payload["agent_output"] == "world"
    assert payload["tools_used"] == ["rag"]
    assert payload["success"] is True
    assert payload["metadata"] == {"kb": "demo"}


@pytest.mark.asyncio
async def test_event_payload_is_json_serializable_for_wire(fresh_bus) -> None:
    """The bus payload crosses process/IPC boundaries — must stay JSON-safe."""
    event = _make_event()

    restored = json.loads(json.dumps(event.to_dict()))

    assert restored["type"] == "SOLVE_COMPLETE"
    # ISO timestamps parse back into a real datetime.
    datetime.fromisoformat(restored["timestamp"])


@pytest.mark.asyncio
async def test_event_to_dict_accepts_plain_string_type(fresh_bus) -> None:
    event = _make_event(type="CUSTOM_TYPE")

    assert event.to_dict()["type"] == "CUSTOM_TYPE"


@pytest.mark.asyncio
async def test_event_defaults_are_independent_per_instance(fresh_bus) -> None:
    def bare_event() -> Event:
        return Event(
            type=EventType.SOLVE_COMPLETE,
            task_id="t",
            user_input="in",
            agent_output="out",
        )

    first = bare_event()
    second = bare_event()

    assert first.tools_used == [] and second.tools_used == []
    first.tools_used.append("web_search")

    assert second.tools_used == []
    assert first.event_id != second.event_id


# ---------------------------------------------------------------------------
# Subscription lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_bus_is_a_singleton() -> None:
    assert EventBus() is get_event_bus()
    assert EventBus() is EventBus()


@pytest.mark.asyncio
async def test_duplicate_subscribe_only_registers_handler_once(fresh_bus) -> None:
    received: list[Event] = []

    async def handler(_event: Event) -> None:
        received.append(_event)

    fresh_bus.subscribe(EventType.SOLVE_COMPLETE, handler)
    fresh_bus.subscribe(EventType.SOLVE_COMPLETE, handler)

    await fresh_bus.publish(_make_event())
    await fresh_bus.flush(timeout=5.0)

    assert len(received) == 1


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery_for_that_handler(fresh_bus) -> None:
    received: list[Event] = []

    async def handler(_event: Event) -> None:
        received.append(_event)

    fresh_bus.subscribe(EventType.SOLVE_COMPLETE, handler)
    fresh_bus.unsubscribe(EventType.SOLVE_COMPLETE, handler)

    await fresh_bus.publish(_make_event())
    await fresh_bus.flush(timeout=5.0)

    assert received == []


@pytest.mark.asyncio
async def test_publish_auto_starts_the_bus_and_delivers(fresh_bus) -> None:
    received: list[Event] = []

    async def handler(_event: Event) -> None:
        received.append(_event)

    fresh_bus.subscribe(EventType.SOLVE_COMPLETE, handler)
    event = _make_event()
    await fresh_bus.publish(event)
    await fresh_bus.flush(timeout=5.0)

    assert fresh_bus._running is True
    assert received == [event]


@pytest.mark.asyncio
async def test_events_without_subscribers_are_consumed_not_requeued(fresh_bus) -> None:
    await fresh_bus.publish(_make_event())
    await fresh_bus.flush(timeout=5.0)

    assert fresh_bus._task_queue.qsize() == 0


# ---------------------------------------------------------------------------
# Subscriber exception isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscriber_error_does_not_affect_other_subscribers(fresh_bus) -> None:
    """The regression contract: one raising handler must not sink the rest."""
    received: list[Event] = []

    async def broken(_event: Event) -> None:
        raise RuntimeError("subscriber exploded")

    async def healthy(event: Event) -> None:
        received.append(event)

    fresh_bus.subscribe(EventType.SOLVE_COMPLETE, broken)
    fresh_bus.subscribe(EventType.SOLVE_COMPLETE, healthy)

    event = _make_event()
    await fresh_bus.publish(event)
    await fresh_bus.flush(timeout=5.0)

    # The healthy subscriber — registered *after* the broken one — still
    # received the very same event object.
    assert received == [event]

    # And the bus keeps delivering subsequent events.
    second = _make_event(task_id="task-2")
    await fresh_bus.publish(second)
    await fresh_bus.flush(timeout=5.0)

    assert received == [event, second]


@pytest.mark.asyncio
async def test_every_subscriber_sees_the_event_even_when_first_raises(
    fresh_bus,
) -> None:
    calls: list[str] = []

    async def broken(_event: Event) -> None:
        calls.append("broken")
        raise ValueError("bad handler")

    async def healthy(_event: Event) -> None:
        calls.append("healthy")

    fresh_bus.subscribe(EventType.QUESTION_COMPLETE, broken)
    fresh_bus.subscribe(EventType.QUESTION_COMPLETE, healthy)

    await fresh_bus.publish(_make_event(type=EventType.QUESTION_COMPLETE))
    await fresh_bus.flush(timeout=5.0)

    assert calls == ["broken", "healthy"]


# ---------------------------------------------------------------------------
# Backpressure / drop policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_times_out_and_retains_pending_events_instead_of_dropping(
    fresh_bus,
) -> None:
    """A slow subscriber backs up the unbounded queue; flush surfaces the
    timeout, no event is dropped, and draining finishes once it unblocks."""
    release = asyncio.Event()
    receipts: list[str] = []

    async def slow_then_fast(event: Event) -> None:
        receipts.append(event.task_id)
        if event.task_id == "blocked":
            await release.wait()

    fresh_bus.subscribe(EventType.CAPABILITY_COMPLETE, slow_then_fast)

    first = _make_event(type=EventType.CAPABILITY_COMPLETE, task_id="blocked")
    second = _make_event(type=EventType.CAPABILITY_COMPLETE, task_id="queued")
    await fresh_bus.publish(first)
    await fresh_bus.publish(second)

    # The blocked handler wedges the queue — flush must give up on timeout.
    await fresh_bus.flush(timeout=0.2)
    assert fresh_bus._running is True
    assert fresh_bus._task_queue.qsize() >= 1  # the queued event was retained

    release.set()
    await fresh_bus.flush(timeout=5.0)

    assert receipts == ["blocked", "queued"]
    assert fresh_bus._task_queue.qsize() == 0


@pytest.mark.asyncio
async def test_flush_is_immediate_when_the_bus_is_idle(fresh_bus) -> None:
    await fresh_bus.flush(timeout=0.1)

    assert fresh_bus._task_queue.qsize() == 0


@pytest.mark.asyncio
async def test_stop_drains_pending_events_before_shutdown(fresh_bus) -> None:
    received: list[Event] = []

    async def handler(_event: Event) -> None:
        received.append(_event)

    fresh_bus.subscribe(EventType.SOLVE_COMPLETE, handler)
    for index in range(5):
        await fresh_bus.publish(_make_event(task_id=f"task-{index}"))

    await fresh_bus.stop()

    assert [event.task_id for event in received] == [f"task-{index}" for index in range(5)]
    assert fresh_bus._running is False


@pytest.mark.asyncio
async def test_stop_is_idempotent_and_reset_clears_the_singleton(fresh_bus) -> None:
    await fresh_bus.start()
    await fresh_bus.stop()
    await fresh_bus.stop()  # no error on double stop

    EventBus.reset()
    event_bus_module._event_bus = None

    assert EventBus._instance is None
    assert EventBus._initialized is False
    revived = get_event_bus()
    assert revived is not fresh_bus
    assert revived._running is False
