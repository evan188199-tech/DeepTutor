"""Assembly-order and missing-dependency degradation tests for app container."""

from __future__ import annotations

import asyncio
import os
import re
import socket
from types import SimpleNamespace
from typing import Any
import uuid

import pytest

import deeptutor.app.container as container_module
from deeptutor.app.container import (
    ApplicationContainer,
    RuntimeRegistry,
    StoreProvider,
    set_application_container,
)
from deeptutor.runtime.coordination import (
    CoordinationSettings,
    MemoryCoordinator,
    RuntimeConfigurationError,
)
from deeptutor.services.session.scope import StoreScope


class _RecordingCoordinator(MemoryCoordinator):
    """Memory coordinator that records close calls for ordering assertions."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.closed = False
        self.close_calls: list[str] = []

    async def close(self) -> None:
        self.closed = True
        self.close_calls.append("coordinator")


def _memory_container(**overrides: Any) -> tuple[ApplicationContainer, _RecordingCoordinator]:
    coordinator = _RecordingCoordinator()
    settings = CoordinationSettings(**overrides)
    container = ApplicationContainer(
        settings=settings, coordinator=coordinator, worker_id="host:1:deadbeef"
    )
    return container, coordinator


def test_build_memory_backend_assembles_dependency_chain(monkeypatch) -> None:
    monkeypatch.setattr(container_module, "load_system_settings", lambda: {"backend_workers": 1})
    monkeypatch.setattr(
        container_module,
        "load_integrations_settings",
        lambda: {"turn_coordination": {"backend": "memory"}},
    )

    container = ApplicationContainer.build()

    assert isinstance(container.coordinator, MemoryCoordinator)
    assert container.settings.backend == "memory"
    # worker id names the host, the pid, and a short random suffix.
    assert re.fullmatch(
        rf"{re.escape(socket.gethostname())}:{os.getpid()}:[0-9a-f]{{8}}",
        container.worker_id,
    )
    # Assembly order: catalog -> registry -> engine -> store provider -> runtimes -> service.
    assert "chat" in container.capability_registry.list_capabilities()
    assert container.runtime_registry.turn_engine is container.turn_engine
    assert container.turns.runtime_registry is container.runtime_registry
    assert container.turns.store_provider is container.store_provider
    assert container.turns.coordinator is container.coordinator
    assert container.runtime_registry.coordinator is container.coordinator
    assert container.runtime_registry.worker_id == container.worker_id
    assert container._started is False


def test_build_redis_backend_selects_redis_coordinator(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class _StubRedisCoordinator:
        def __init__(self, redis_url: str, **kwargs: Any) -> None:
            captured["redis_url"] = redis_url
            captured.update(kwargs)

    monkeypatch.setattr(
        container_module,
        "load_system_settings",
        lambda: {"backend_workers": 2},
    )
    monkeypatch.setattr(
        container_module,
        "load_integrations_settings",
        lambda: {
            "turn_coordination": {
                "backend": "redis",
                "redis_url": "redis://example.test:6379/0",
                "key_prefix": "tenant",
                "lease_ttl_seconds": 45,
                "stream_retention_seconds": 7200,
            }
        },
    )
    monkeypatch.setattr(container_module, "RedisCoordinator", _StubRedisCoordinator)

    container = ApplicationContainer.build()

    assert isinstance(container.coordinator, _StubRedisCoordinator)
    assert captured["redis_url"] == "redis://example.test:6379/0"
    assert captured["key_prefix"] == "tenant"
    assert captured["lease_ttl_seconds"] == 45
    assert captured["stream_retention_seconds"] == 7200


def test_build_rejects_invalid_coordination_settings(monkeypatch) -> None:
    monkeypatch.setattr(container_module, "load_system_settings", lambda: {})
    monkeypatch.setattr(
        container_module,
        "load_integrations_settings",
        lambda: {"turn_coordination": {"backend": "carrier-pigeon"}},
    )

    with pytest.raises(RuntimeConfigurationError):
        ApplicationContainer.build()


def test_start_refuses_unhealthy_coordinator_then_recovers() -> None:
    container, coordinator = _memory_container()

    async def unhealthy() -> bool:
        return False

    async def healthy() -> bool:
        return True

    async def main() -> None:
        coordinator.health = unhealthy  # type: ignore[method-assign]
        with pytest.raises(RuntimeConfigurationError, match="unavailable"):
            await container.start()
        assert container._started is False

        coordinator.health = healthy  # type: ignore[method-assign]
        await container.start()
        assert container._started is True

    asyncio.run(main())


def test_start_is_idempotent_and_close_drains_before_coordinator() -> None:
    container, coordinator = _memory_container()
    order: list[str] = []

    async def record_runtime_close(**kwargs: Any) -> None:
        order.append(f"runtimes:{kwargs['drain_timeout_seconds']}")

    async def record_coordinator_close() -> None:
        order.append("coordinator")

    async def main() -> None:
        await container.start()
        await container.start()  # second start is a no-op
        assert container._started is True

        coordinator.close = record_coordinator_close  # type: ignore[method-assign]
        monkey_close = SimpleNamespace(close=record_runtime_close)
        container.runtime_registry.close = monkey_close.close  # type: ignore[method-assign]
        await container.close()

        assert order == ["runtimes:60.0", "coordinator"]
        assert container._started is False
        assert coordinator.closed is False  # replaced method recorded instead

    asyncio.run(main())


def test_close_without_start_is_a_noop() -> None:
    container, coordinator = _memory_container()

    async def failing_close() -> None:
        raise AssertionError("close must not be called before start")

    coordinator.close = failing_close  # type: ignore[method-assign]

    async def main() -> None:
        await container.close()
        assert container._started is False

    asyncio.run(main())


def test_close_suppresses_coordinator_shutdown_errors() -> None:
    container, coordinator = _memory_container()

    async def broken_close() -> None:
        raise RuntimeError("backend already gone")

    async def main() -> None:
        await container.start()
        coordinator.close = broken_close  # type: ignore[method-assign]
        await container.close()
        assert container._started is False

    asyncio.run(main())


def test_store_provider_delegates_to_session_store(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setattr(container_module, "get_session_store", lambda: sentinel)
    assert StoreProvider().get() is sentinel


def _scoped_store(backend: str, resource: str, owner: str) -> SimpleNamespace:
    return SimpleNamespace(
        store_scope=StoreScope(backend=backend, resource=resource, owner_id=owner)
    )


def test_runtime_registry_reuses_one_runtime_per_store_scope() -> None:
    engine = object()
    registry = RuntimeRegistry(MemoryCoordinator(), "worker-1", engine)  # type: ignore[arg-type]

    first = _scoped_store("sqlite", "/tmp/a.db", "alice")
    same_scope = _scoped_store("sqlite", "/tmp/a.db", "alice")
    other_scope = _scoped_store("sqlite", "/tmp/b.db", "alice")

    runtime = registry.get(first)
    assert registry.get(same_scope) is runtime
    assert registry.get(other_scope) is not runtime

    assert runtime.store is first
    assert runtime.coordinator is registry.coordinator
    assert runtime.owner_id == "worker-1"
    assert runtime.turn_engine is engine


def test_runtime_registry_close_clears_cache_and_survives_failures() -> None:
    registry = RuntimeRegistry(MemoryCoordinator(), "worker-1", object())  # type: ignore[arg-type]
    store = _scoped_store("sqlite", "/tmp/a.db", "alice")
    runtime = registry.get(store)
    runtime._executions["turn-1"] = SimpleNamespace()
    runtime._executions["turn-2"] = SimpleNamespace()

    assert registry.owner_turn_count() == 2

    closed: list[str] = []

    async def failing_close(**kwargs: Any) -> None:
        closed.append("fail")
        raise RuntimeError("drain failed")

    runtime.close = failing_close  # type: ignore[method-assign]
    second = registry.get(_scoped_store("sqlite", "/tmp/b.db", "alice"))

    async def main() -> None:
        await registry.close(drain_timeout_seconds=1.0)

    asyncio.run(main())

    assert closed == ["fail"]  # one broken runtime did not stop the sweep
    assert registry._runtimes == {}
    # The failing runtime was still counted before the cache cleared.
    assert registry.owner_turn_count() == 0
    assert registry.get(store) is not runtime
    assert second is not runtime


def test_set_application_container_roundtrip(monkeypatch) -> None:
    container, _ = _memory_container()
    previous = container_module._default_container
    monkeypatch.setattr(container_module, "_default_container", previous)
    set_application_container(container)
    assert container_module.get_application_container() is container
    set_application_container(previous)
    # Restoring a None slot keeps the lazy-build semantics of the getter.
    assert container_module._default_container is previous
