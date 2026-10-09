from __future__ import annotations

import inspect
from typing import Any

import pytest

from deeptutor.runtime.coordination import (
    CoordinationSettings,
    MemoryCoordinator,
    RuntimeConfigurationError,
    RuntimeCoordinator,
    create_runtime_coordinator,
)
from deeptutor.runtime.coordination import settings as coordination_settings
from deeptutor.runtime.coordination.protocol import RuntimeCoordinator as ProtocolOrigin
from deeptutor.runtime.coordination.redis import RedisCoordinator

_METHOD_SPECS: dict[str, tuple[str, str]] = {
    "acquire_turn": ("turn_id, session_id, owner_id", "TurnLease | None"),
    "renew_turn": ("lease", "TurnLease | None"),
    "release_turn": ("lease", "bool"),
    "get_lease": ("turn_id", "TurnLease | None"),
    "list_expired_turn_ids": ("", "list[str]"),
    "acknowledge_expired_turn": ("turn_id", "None"),
    "publish_event": ("turn_id, event", "dict[str, Any]"),
    "read_events": ("turn_id, after_seq=0", "list[dict[str, Any]]"),
    "submit_command": (
        "turn_id, kind, payload=None, *, command_id=None",
        "TurnCommand | None",
    ),
    "read_commands": ("turn_id, after_id='0-0'", "list[tuple[str, TurnCommand]]"),
    "submit_background_command": (
        "kind, payload=None, *, command_id=None",
        "BackgroundCommand | None",
    ),
    "read_background_commands": (
        "after_id='0-0'",
        "list[tuple[str, BackgroundCommand]]",
    ),
    "acknowledge_background_command": ("stream_id, lease=None", "bool"),
    "acquire_leader": ("owner_id", "LeaderLease | None"),
    "renew_leader": ("lease", "LeaderLease | None"),
    "release_leader": ("lease", "bool"),
    "leader_id": ("", "str | None"),
    "health": ("", "bool"),
    "close": ("", "None"),
}


def _rendered_port_signature(method_name: str) -> tuple[str, str]:
    fn = getattr(RuntimeCoordinator, method_name)
    assert inspect.iscoroutinefunction(fn), f"{method_name} must be declared async"
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())[1:]
    rendered: list[str] = []
    saw_keyword_only = False
    for param in params:
        if param.kind is inspect.Parameter.KEYWORD_ONLY and not saw_keyword_only:
            rendered.append("*")
            saw_keyword_only = True
        if param.default is inspect.Parameter.empty:
            rendered.append(param.name)
        else:
            rendered.append(f"{param.name}={param.default!r}")
    returns = str(sig.return_annotation).replace("'", "")
    return ", ".join(rendered), returns


def test_protocol_module_exports_only_the_port() -> None:
    assert ProtocolOrigin.__module__ == "deeptutor.runtime.coordination.protocol"
    import deeptutor.runtime.coordination.protocol as protocol_module

    assert protocol_module.__all__ == ["RuntimeCoordinator"]


def test_protocol_members_cover_turn_event_command_and_leader_surface() -> None:
    members = set(RuntimeCoordinator.__protocol_attrs__)
    assert members == {"mode", *_METHOD_SPECS}


def test_protocol_methods_lock_signatures() -> None:
    assert set(_METHOD_SPECS) <= set(RuntimeCoordinator.__protocol_attrs__)
    for method_name, (expected_params, expected_return) in _METHOD_SPECS.items():
        params, returns = _rendered_port_signature(method_name)
        assert (params, returns) == (expected_params, expected_return), method_name


def test_concrete_coordinators_satisfy_the_runtime_protocol() -> None:
    memory = MemoryCoordinator()
    redis = RedisCoordinator("redis://127.0.0.1:6399/0", client=object())

    assert isinstance(memory, RuntimeCoordinator)
    assert isinstance(redis, RuntimeCoordinator)
    assert memory.mode == "memory"
    assert redis.mode == "redis"


def test_implementations_missing_members_are_rejected() -> None:
    class MissingClose:
        mode = "stub"

        def __getattr__(self, name: str) -> Any:
            if name == "close":
                raise AttributeError(name)
            return lambda *args: None

    class MissingMode:
        pass

    assert not isinstance(MissingClose(), RuntimeCoordinator)
    assert not isinstance(MissingMode(), RuntimeCoordinator)
    assert not isinstance(object(), RuntimeCoordinator)


@pytest.mark.asyncio
async def test_memory_assembly_returns_healthy_conforming_coordinator() -> None:
    coordinator = await create_runtime_coordinator(CoordinationSettings())

    assert isinstance(coordinator, MemoryCoordinator)
    assert isinstance(coordinator, RuntimeCoordinator)
    assert coordinator.mode == "memory"
    assert await coordinator.health() is True

    await coordinator.close()
    assert await coordinator.health() is False


@pytest.mark.asyncio
async def test_assembly_revalidates_directly_built_settings() -> None:
    settings = CoordinationSettings(backend="redis", redis_url="")

    with pytest.raises(RuntimeConfigurationError, match="redis_url is required"):
        await create_runtime_coordinator(settings)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "settings",
    [
        CoordinationSettings(backend="etcd"),
        CoordinationSettings(backend="redis", redis_url="redis://x/", lease_ttl_seconds=9),
        CoordinationSettings(renew_interval_seconds=0),
        CoordinationSettings(renew_interval_seconds=30),
    ],
    ids=["unsupported_backend", "ttl_below_minimum", "renew_not_positive", "renew_not_below_ttl"],
)
async def test_assembly_rejects_invalid_settings(settings: CoordinationSettings) -> None:
    with pytest.raises(RuntimeConfigurationError):
        await create_runtime_coordinator(settings)


class _StubRedisCoordinator:
    mode = "redis"
    healthy = True

    def __init__(self, redis_url: str, **kwargs: Any) -> None:
        self.redis_url = redis_url
        self.kwargs = kwargs
        self.close_calls = 0

    async def health(self) -> bool:
        return self.healthy

    async def close(self) -> None:
        self.close_calls += 1


@pytest.mark.asyncio
async def test_assembly_closes_unavailable_redis_coordinator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _StubRedisCoordinator.healthy = False
    monkeypatch.setattr(coordination_settings, "RedisCoordinator", _StubRedisCoordinator)
    settings = CoordinationSettings(
        backend="redis",
        redis_url="redis://127.0.0.1:6399/0",
        key_prefix="tutor-test",
    )

    with pytest.raises(RuntimeConfigurationError, match="unavailable"):
        await create_runtime_coordinator(settings)


@pytest.mark.asyncio
async def test_assembly_returns_healthy_redis_coordinator_without_closing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _StubRedisCoordinator.healthy = True
    created: list[_StubRedisCoordinator] = []

    class RecordingStub(_StubRedisCoordinator):
        def __init__(self, redis_url: str, **kwargs: Any) -> None:
            super().__init__(redis_url, **kwargs)
            created.append(self)

    monkeypatch.setattr(coordination_settings, "RedisCoordinator", RecordingStub)
    settings = CoordinationSettings(
        backend="redis",
        redis_url="redis://127.0.0.1:6399/0",
        key_prefix="tutor-test",
        lease_ttl_seconds=45,
    )

    coordinator = await create_runtime_coordinator(settings)

    assert coordinator is created[0]
    assert created[0].redis_url == "redis://127.0.0.1:6399/0"
    assert created[0].kwargs["key_prefix"] == "tutor-test"
    assert created[0].kwargs["lease_ttl_seconds"] == 45
    assert created[0].close_calls == 0
