"""Concurrency behavior of the opencode/mimocode server pool.

No real ``opencode`` / ``mimocode`` process is spawned: ``_spawn`` is replaced
with controllable fakes, so these tests only exercise the pool's locking —
who waits on what while one (CLI, workdir) combination is spawning.

Lock-scan finding M4: the pool used to hold one module-level lock across
reaping *and* spawn, so a slow spawn of one key blocked every other key's
cache-hit fast path. The pool must keep spawn/reuse serialized per key only.
"""

from __future__ import annotations

import asyncio

import pytest

import deeptutor.services.subagent.opencode_server as pool
from deeptutor.services.subagent.opencode_server import ServerHandle, acquire_server


class _FakeProcess:
    """Minimal stand-in for ``asyncio.subprocess.Process``."""

    def __init__(self) -> None:
        self.returncode: int | None = None

    def terminate(self) -> None:
        self.returncode = 0

    async def wait(self) -> int:
        return 0


def _make_handle() -> ServerHandle:
    return ServerHandle(
        base_url="http://127.0.0.1:1",
        username="u",
        password="p",
        process=_FakeProcess(),
    )


def _reset_pool() -> None:
    pool._servers.clear()
    key_locks = getattr(pool, "_key_locks", None)
    if key_locks is not None:
        key_locks.clear()


@pytest.fixture(autouse=True)
def _clean_pool():
    _reset_pool()
    yield
    _reset_pool()


async def _acquire(cli: str, cwd: str) -> ServerHandle:
    return await acquire_server(cli, cwd=cwd, env_prefix="OPENCODE", username="dt")


@pytest.mark.asyncio
async def test_slow_spawn_does_not_block_other_key_cache_hit(monkeypatch) -> None:
    """While key A pays a cold spawn, key B's warm hit must return at once."""
    cached = _make_handle()
    pool._servers[("opencode", "/w/b")] = cached

    spawn_started = asyncio.Event()
    release_spawn = asyncio.Event()

    async def slow_spawn(cli_command, *, cwd, env_prefix, username):
        spawn_started.set()
        await release_spawn.wait()
        return _make_handle()

    monkeypatch.setattr(pool, "_spawn", slow_spawn)

    spawner = asyncio.create_task(_acquire("opencode", "/w/a"))
    await asyncio.wait_for(spawn_started.wait(), timeout=2.0)

    # A's spawn is in flight and holding its locks — B must not queue behind it.
    hit = await asyncio.wait_for(_acquire("opencode", "/w/b"), timeout=0.5)
    assert hit is cached

    release_spawn.set()
    fresh = await asyncio.wait_for(spawner, timeout=2.0)
    assert fresh is not cached


@pytest.mark.asyncio
async def test_same_key_concurrent_acquires_share_one_spawn(monkeypatch) -> None:
    """Per-key serialization stays: racing acquires of one key spawn exactly once."""
    spawn_started = asyncio.Event()
    release_spawn = asyncio.Event()
    calls = 0

    async def slow_spawn(cli_command, *, cwd, env_prefix, username):
        nonlocal calls
        calls += 1
        spawn_started.set()
        await release_spawn.wait()
        return _make_handle()

    monkeypatch.setattr(pool, "_spawn", slow_spawn)

    first = asyncio.create_task(_acquire("mimocode", "/w"))
    await asyncio.wait_for(spawn_started.wait(), timeout=2.0)

    second = asyncio.create_task(_acquire("mimocode", "/w"))
    await asyncio.sleep(0)  # let `second` start waiting before releasing

    release_spawn.set()
    h1 = await asyncio.wait_for(first, timeout=2.0)
    h2 = await asyncio.wait_for(second, timeout=2.0)
    assert calls == 1
    assert h1 is h2
    assert h2 is pool._servers[("mimocode", "/w")]


@pytest.mark.asyncio
async def test_dead_cached_handle_is_respawned(monkeypatch) -> None:
    """A process that died between consults is replaced, not handed back out."""
    dead = _make_handle()
    dead.process.returncode = 1
    pool._servers[("opencode", "/w")] = dead

    async def spawn(cli_command, *, cwd, env_prefix, username):
        return _make_handle()

    monkeypatch.setattr(pool, "_spawn", spawn)

    handle = await asyncio.wait_for(_acquire("opencode", "/w"), timeout=2.0)
    assert handle is not dead
    assert pool._servers[("opencode", "/w")] is handle
