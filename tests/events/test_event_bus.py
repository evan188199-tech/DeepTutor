"""Direct unit tests for the asynchronous EventBus."""

from __future__ import annotations

import asyncio
import logging

import pytest

from deeptutor.events import event_bus as event_bus_module
from deeptutor.events.event_bus import Event, EventBus, EventType, get_event_bus


@pytest.fixture(autouse=True)
def _fresh_event_bus():
    """Give every test a pristine singleton and drop it again afterwards.

    The bus is a process-wide singleton whose queue binds to the running
    loop, so leftovers from one test would poison the next test's loop.
    ``EventBus.reset()`` alone does not clear the module-level accessor
    cache, so the fixture clears it explicitly.
    """
    EventBus.reset()
    event_bus_module._event_bus = None
    yield
    event_bus_module._event_bus = None
    EventBus.reset()


def _event(
    event_type: EventType = EventType.SOLVE_COMPLETE,
    task_id: str = "task-1",
) -> Event:
    return Event(
        type=event_type,
        task_id=task_id,
        user_input=f"input-{task_id}",
        agent_output=f"output-{task_id}",
    )


async def _noop_handler(_event: Event) -> None:
    return None


# ---------------------------------------------------------------------------
# Event payload
# ---------------------------------------------------------------------------


class TestEventPayload:
    def test_to_dict_serialises_core_fields(self) -> None:
        event = Event(
            type=EventType.QUESTION_COMPLETE,
            task_id="t1",
            user_input="question",
            agent_output="answer",
            tools_used=["search"],
            success=False,
            metadata={"capability": "echo"},
        )

        data = event.to_dict()

        assert data["type"] == "QUESTION_COMPLETE"
        assert data["task_id"] == "t1"
        assert data["user_input"] == "question"
        assert data["agent_output"] == "answer"
        assert data["tools_used"] == ["search"]
        assert data["success"] is False
        assert data["metadata"] == {"capability": "echo"}
        assert data["event_id"] == event.event_id
        assert data["timestamp"] == event.timestamp.isoformat()

    def test_to_dict_keeps_plain_string_event_type(self) -> None:
        event = Event(type="SOLVE_COMPLETE", task_id="t2", user_input="q", agent_output="a")

        assert event.to_dict()["type"] == "SOLVE_COMPLETE"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestBusSingleton:
    def test_constructor_returns_shared_instance(self) -> None:
        assert EventBus() is EventBus()

    def test_accessor_returns_the_singleton(self) -> None:
        bus = EventBus()

        assert get_event_bus() is bus


# ---------------------------------------------------------------------------
# Subscribe / unsubscribe
# ---------------------------------------------------------------------------


class TestSubscriptionLifecycle:
    @pytest.mark.asyncio
    async def test_subscribed_handler_receives_published_event(self) -> None:
        bus = EventBus()
        received: list[Event] = []

        async def _record(event: Event) -> None:
            received.append(event)

        bus.subscribe(EventType.SOLVE_COMPLETE, _record)
        event = _event()

        await bus.publish(event)
        await bus.flush(timeout=5)

        assert received == [event]

    @pytest.mark.asyncio
    async def test_unsubscribed_handler_receives_nothing(self) -> None:
        bus = EventBus()
        received: list[Event] = []

        async def _record(event: Event) -> None:
            received.append(event)

        bus.subscribe(EventType.SOLVE_COMPLETE, _record)
        bus.unsubscribe(EventType.SOLVE_COMPLETE, _record)

        await bus.publish(_event())
        await bus.flush(timeout=5)

        assert received == []
        assert _record not in bus._subscribers[EventType.SOLVE_COMPLETE]

    def test_unsubscribe_unknown_handler_is_noop(self) -> None:
        bus = EventBus()

        bus.unsubscribe(EventType.SOLVE_COMPLETE, _noop_handler)

        assert bus._subscribers[EventType.SOLVE_COMPLETE] == []

    @pytest.mark.asyncio
    async def test_duplicate_subscription_delivers_each_event_once(self) -> None:
        bus = EventBus()
        calls: list[str] = []

        async def _record(event: Event) -> None:
            calls.append(event.task_id)

        bus.subscribe(EventType.SOLVE_COMPLETE, _record)
        bus.subscribe(EventType.SOLVE_COMPLETE, _record)

        await bus.publish(_event())
        await bus.flush(timeout=5)

        assert bus._subscribers[EventType.SOLVE_COMPLETE] == [_record]
        assert calls == ["task-1"]


# ---------------------------------------------------------------------------
# Subscription isolation
# ---------------------------------------------------------------------------


class TestSubscriptionIsolation:
    @pytest.mark.asyncio
    async def test_subscriber_does_not_receive_other_event_types(self) -> None:
        bus = EventBus()
        received: list[str] = []

        async def _record(event: Event) -> None:
            received.append(event.task_id)

        bus.subscribe(EventType.SOLVE_COMPLETE, _record)

        for other in (EventType.QUESTION_COMPLETE, EventType.CAPABILITY_COMPLETE):
            await bus.publish(_event(other, f"task-{other.value}"))
        await bus.flush(timeout=5)
        assert received == []

        await bus.publish(_event(EventType.SOLVE_COMPLETE, "task-mine"))
        await bus.flush(timeout=5)
        assert received == ["task-mine"]

    @pytest.mark.asyncio
    async def test_one_handler_can_subscribe_to_multiple_event_types(self) -> None:
        """The bus has no wildcard subscription: fan-out is keyed strictly by
        EventType, so a listener that wants several types subscribes to each
        one explicitly.
        """
        bus = EventBus()
        received: list[str] = []

        async def _record(event: Event) -> None:
            received.append(event.task_id)

        for event_type in EventType:
            bus.subscribe(event_type, _record)

        for event_type in EventType:
            await bus.publish(_event(event_type, f"task-{event_type.value}"))
        await bus.flush(timeout=5)

        assert received == [f"task-{event_type.value}" for event_type in EventType]


# ---------------------------------------------------------------------------
# Handler error propagation
# ---------------------------------------------------------------------------


class TestHandlerErrors:
    @pytest.mark.asyncio
    async def test_failing_handler_does_not_block_later_subscribers(self) -> None:
        bus = EventBus()
        received: list[str] = []

        async def _boom(_event: Event) -> None:
            raise RuntimeError("intentional handler failure")

        async def _record(event: Event) -> None:
            received.append(event.task_id)

        bus.subscribe(EventType.SOLVE_COMPLETE, _boom)
        bus.subscribe(EventType.SOLVE_COMPLETE, _record)

        await bus.publish(_event())
        await bus.flush(timeout=5)

        assert received == ["task-1"]

    @pytest.mark.asyncio
    async def test_failing_handler_does_not_block_later_events(self, caplog) -> None:
        bus = EventBus()
        received: list[str] = []

        async def _boom(event: Event) -> None:
            received.append(event.task_id)
            raise RuntimeError("intentional handler failure")

        bus.subscribe(EventType.SOLVE_COMPLETE, _boom)

        with caplog.at_level(logging.ERROR, logger="deeptutor.events.event_bus"):
            for task_id in ("task-1", "task-2", "task-3"):
                await bus.publish(_event(task_id=task_id))
            await bus.flush(timeout=5)

        assert received == ["task-1", "task-2", "task-3"]
        assert any("intentional handler failure" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# Delivery order and async handlers
# ---------------------------------------------------------------------------


class TestDeliveryOrderAndAsync:
    @pytest.mark.asyncio
    async def test_events_are_delivered_in_publish_order(self) -> None:
        bus = EventBus()
        received: list[str] = []

        async def _record(event: Event) -> None:
            received.append(event.task_id)

        bus.subscribe(EventType.QUESTION_COMPLETE, _record)

        for index in range(5):
            await bus.publish(_event(EventType.QUESTION_COMPLETE, f"task-{index}"))
        await bus.flush(timeout=5)

        assert received == [f"task-{index}" for index in range(5)]

    @pytest.mark.asyncio
    async def test_async_handler_is_awaited_to_completion(self) -> None:
        bus = EventBus()
        stages: list[str] = []

        async def _slow_handler(_event: Event) -> None:
            stages.append("start")
            await asyncio.sleep(0.05)
            stages.append("end")

        bus.subscribe(EventType.SOLVE_COMPLETE, _slow_handler)

        await bus.publish(_event())
        await bus.flush(timeout=5)

        assert stages == ["start", "end"]

    @pytest.mark.asyncio
    async def test_publish_returns_before_the_handler_runs(self) -> None:
        """Publishing only queues the event; delivery runs in the background."""
        bus = EventBus()
        received: list[str] = []

        async def _record(event: Event) -> None:
            received.append(event.task_id)

        bus.subscribe(EventType.SOLVE_COMPLETE, _record)

        await bus.publish(_event())
        assert received == []

        await bus.flush(timeout=5)
        assert received == ["task-1"]


# ---------------------------------------------------------------------------
# Bus lifecycle
# ---------------------------------------------------------------------------


class TestBusLifecycle:
    @pytest.mark.asyncio
    async def test_start_is_idempotent(self) -> None:
        bus = EventBus()

        await bus.start()
        first_task = bus._processor_task
        await bus.start()

        assert bus._processor_task is first_task
        await bus.stop()

    @pytest.mark.asyncio
    async def test_stop_is_idempotent_when_not_running(self) -> None:
        bus = EventBus()

        await bus.stop()

        assert bus._running is False

    @pytest.mark.asyncio
    async def test_publish_restarts_the_bus_after_stop(self) -> None:
        bus = EventBus()
        received: list[str] = []

        async def _record(event: Event) -> None:
            received.append(event.task_id)

        bus.subscribe(EventType.SOLVE_COMPLETE, _record)

        await bus.publish(_event())
        await bus.flush(timeout=5)
        await bus.stop()

        await bus.publish(_event(task_id="task-2"))
        await bus.flush(timeout=5)

        assert received == ["task-1", "task-2"]

    @pytest.mark.asyncio
    async def test_flush_times_out_when_a_handler_never_completes(self, caplog) -> None:
        bus = EventBus()

        async def _parked(_event: Event) -> None:
            await asyncio.Event().wait()

        bus.subscribe(EventType.SOLVE_COMPLETE, _parked)
        await bus.publish(_event())

        with caplog.at_level(logging.WARNING, logger="deeptutor.events.event_bus"):
            await bus.flush(timeout=0.2)

        assert any("flush timeout" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_flush_returns_immediately_when_idle(self) -> None:
        bus = EventBus()

        await bus.flush(timeout=5)

        assert bus._running is False

    @pytest.mark.asyncio
    async def test_survives_idle_poll_timeout_between_events(self) -> None:
        """The processor's 1s empty-queue poll must not stop the bus."""
        bus = EventBus()
        received: list[str] = []

        async def _record(event: Event) -> None:
            received.append(event.task_id)

        bus.subscribe(EventType.SOLVE_COMPLETE, _record)

        await bus.start()
        await asyncio.sleep(1.3)
        await bus.publish(_event())
        await bus.flush(timeout=5)

        assert received == ["task-1"]
