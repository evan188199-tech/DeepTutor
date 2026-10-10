from __future__ import annotations

import asyncio
import dataclasses

import pytest

from deeptutor.learning import event_hub as event_hub_module
from deeptutor.learning.event_hub import (
    MasteryTopicEventHub,
    TopicSignal,
    TopicSubscription,
    mastery_topic_event_hub,
    publish_topic_signal,
)


@pytest.mark.asyncio
async def test_topic_hub_wakes_an_event_loop_from_a_worker_thread() -> None:
    hub = MasteryTopicEventHub()
    subscription = hub.subscribe("topic-one")
    try:
        await asyncio.to_thread(hub.publish, "topic-one", 7, "mastery.updated")
        signal = await asyncio.wait_for(subscription.get(), timeout=1)
    finally:
        subscription.close()

    assert signal.path_id == "topic-one"
    assert signal.revision == 7
    assert signal.reason == "mastery.updated"


@pytest.mark.asyncio
async def test_topic_hub_isolated_by_path_and_unsubscribes_cleanly() -> None:
    hub = MasteryTopicEventHub()
    first = hub.subscribe("first")
    second = hub.subscribe("second")
    first.close()

    hub.publish("first", 1)
    hub.publish("second", 2, "session.bound")

    signal = await asyncio.wait_for(second.get(), timeout=1)
    second.close()
    assert signal.path_id == "second"
    assert signal.sequence >= 1
    assert first.queue.empty()


@pytest.mark.asyncio
async def test_topic_hub_isolated_by_workspace_scope() -> None:
    hub = MasteryTopicEventHub()
    first = hub.subscribe("shared", scope="workspace-a")
    second = hub.subscribe("shared", scope="workspace-b")
    try:
        hub.publish("shared", 3, scope="workspace-a")
        signal = await asyncio.wait_for(first.get(), timeout=1)
    finally:
        first.close()
        second.close()

    assert signal.revision == 3
    assert second.queue.empty()


@pytest.mark.asyncio
async def test_topic_hub_coalesces_slow_subscriber_to_latest_signal() -> None:
    hub = MasteryTopicEventHub()
    subscription = hub.subscribe("topic-one")
    try:
        for revision in range(1, 51):
            hub.publish("topic-one", revision)
        await asyncio.sleep(0)
        signal = await asyncio.wait_for(subscription.get(), timeout=1)
    finally:
        subscription.close()

    assert signal.revision == 50
    assert subscription.queue.empty()


@pytest.mark.asyncio
async def test_revision_is_coerced_and_negatives_clamp_to_zero() -> None:
    hub = MasteryTopicEventHub()
    subscription = hub.subscribe("clamp")
    try:
        hub.publish("clamp", "9")
        coerced = await asyncio.wait_for(subscription.get(), timeout=1)
        hub.publish("clamp", -5)
        clamped = await asyncio.wait_for(subscription.get(), timeout=1)
    finally:
        subscription.close()

    assert coerced.revision == 9
    assert clamped.revision == 0


@pytest.mark.asyncio
async def test_empty_scope_resolves_to_the_default_scope() -> None:
    hub = MasteryTopicEventHub()
    default = hub.subscribe("shared")
    other = hub.subscribe("shared", scope="workspace-b")
    explicit_empty = hub.subscribe("empty-scope", scope="")
    try:
        hub.publish("shared", 4, scope="")
        signal = await asyncio.wait_for(default.get(), timeout=1)
        hub.publish("empty-scope", 5, scope="default")
        empty_scope_signal = await asyncio.wait_for(explicit_empty.get(), timeout=1)
    finally:
        default.close()
        other.close()
        explicit_empty.close()

    assert signal.revision == 4
    assert empty_scope_signal.revision == 5
    assert other.queue.empty()


@pytest.mark.asyncio
async def test_missing_reason_falls_back_to_topic_changed() -> None:
    hub = MasteryTopicEventHub()
    subscription = hub.subscribe("reasons")
    try:
        hub.publish("reasons", 1)
        default_reason = await asyncio.wait_for(subscription.get(), timeout=1)
        hub.publish("reasons", 2, reason="")
        empty_reason = await asyncio.wait_for(subscription.get(), timeout=1)
    finally:
        subscription.close()

    assert default_reason.reason == "topic.changed"
    assert empty_reason.reason == "topic.changed"


@pytest.mark.asyncio
async def test_publish_without_subscribers_is_harmless_and_keeps_sequence() -> None:
    hub = MasteryTopicEventHub()
    hub.publish("ghost", 1)
    hub.publish("ghost", 2)

    subscription = hub.subscribe("ghost")
    try:
        hub.publish("ghost", 3)
        signal = await asyncio.wait_for(subscription.get(), timeout=1)
    finally:
        subscription.close()

    assert signal.revision == 3
    assert signal.sequence >= 3


def test_subscribe_requires_a_running_loop() -> None:
    hub = MasteryTopicEventHub()

    with pytest.raises(RuntimeError):
        hub.subscribe("no-loop")

    assert hub._subscriptions == {}


@pytest.mark.asyncio
async def test_close_is_idempotent_and_removing_unknown_subscription_is_safe() -> None:
    hub = MasteryTopicEventHub()
    subscription = hub.subscribe("dup-close")
    subscription.close()
    subscription.close()
    hub._remove(subscription)

    assert hub._subscriptions == {}

    hub.publish("dup-close", 1)
    await asyncio.sleep(0)

    assert subscription.queue.empty()
    assert hub._subscriptions == {}


@pytest.mark.asyncio
async def test_signal_in_flight_is_dropped_after_close() -> None:
    hub = MasteryTopicEventHub()
    subscription = hub.subscribe("late-close")

    hub.publish("late-close", 1)
    subscription.close()
    await asyncio.sleep(0)

    assert subscription.queue.empty()
    assert subscription._closed is True


@pytest.mark.asyncio
async def test_subscription_on_a_closed_loop_is_reaped_by_publish() -> None:
    hub = MasteryTopicEventHub()
    holder: dict[str, object] = {}

    async def _subscribe_on_private_loop() -> None:
        holder["sub"] = hub.subscribe("reap")

    await asyncio.to_thread(asyncio.run, _subscribe_on_private_loop())
    orphaned = holder["sub"]
    assert isinstance(orphaned, TopicSubscription)
    assert orphaned.loop.is_closed()

    hub.publish("reap", 1)
    await asyncio.sleep(0)

    assert orphaned._closed is True
    assert hub._subscriptions == {}


class _RaisingLoop:
    def is_closed(self) -> bool:
        return False

    def call_soon_threadsafe(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("loop shutting down")


class _BrokenSubscriber:
    def __init__(self, path_id: str) -> None:
        self.path_id = path_id
        self.scope = "default"
        self.queue: asyncio.Queue[TopicSignal] = asyncio.Queue(maxsize=1)
        self.loop = _RaisingLoop()
        self._closed = False

    def close(self) -> None:
        self._closed = True


@pytest.mark.asyncio
async def test_failed_loop_delivery_closes_broken_subscriber_without_hurting_others() -> None:
    hub = MasteryTopicEventHub()
    broken = _BrokenSubscriber("mixed")
    hub._add(broken)
    healthy = hub.subscribe("mixed")
    try:
        hub.publish("mixed", 2)
        signal = await asyncio.wait_for(healthy.get(), timeout=1)
    finally:
        healthy.close()

    assert signal.revision == 2
    assert broken._closed is True


@pytest.mark.asyncio
async def test_sequence_is_strictly_monotonic_across_topics_and_scopes() -> None:
    hub = MasteryTopicEventHub()
    first = hub.subscribe("t-a")
    second = hub.subscribe("t-b", scope="ws-2")
    try:
        hub.publish("t-a", 1)
        hub.publish("t-b", 1, scope="ws-2")
        first_signal = await asyncio.wait_for(first.get(), timeout=1)
        second_signal = await asyncio.wait_for(second.get(), timeout=1)
    finally:
        first.close()
        second.close()

    assert second_signal.sequence > first_signal.sequence


@pytest.mark.asyncio
async def test_uncoercible_revision_raises_and_hub_remains_usable() -> None:
    hub = MasteryTopicEventHub()

    with pytest.raises(TypeError):
        hub.publish("bad", None)  # type: ignore[arg-type]

    subscription = hub.subscribe("bad")
    try:
        hub.publish("bad", 6)
        signal = await asyncio.wait_for(subscription.get(), timeout=1)
    finally:
        subscription.close()

    assert signal.revision == 6


@pytest.mark.asyncio
async def test_module_level_publish_topic_signal_targets_the_singleton() -> None:
    subscription = mastery_topic_event_hub.subscribe("module-level")
    try:
        publish_topic_signal("module-level", 9)
        signal = await asyncio.wait_for(subscription.get(), timeout=1)
    finally:
        subscription.close()

    assert signal.path_id == "module-level"
    assert signal.revision == 9
    assert signal.reason == "topic.changed"


def test_topic_signal_is_frozen_and_public_surface_is_declared() -> None:
    signal = TopicSignal(path_id="p", revision=1, reason="r", sequence=1)

    with pytest.raises(dataclasses.FrozenInstanceError):
        signal.revision = 2

    assert set(event_hub_module.__all__) == {
        "MasteryTopicEventHub",
        "TopicSignal",
        "TopicSubscription",
        "mastery_topic_event_hub",
        "publish_topic_signal",
    }
