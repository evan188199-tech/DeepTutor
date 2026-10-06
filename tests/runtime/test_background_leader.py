from __future__ import annotations

import asyncio
from collections.abc import Callable
import inspect

import pytest

from deeptutor.runtime.background_leader import BackgroundLeaderSupervisor
from deeptutor.runtime.coordination import MemoryCoordinator

LEASE_TTL_SECONDS = 1.0
RENEW_INTERVAL_SECONDS = 0.1
ELECTION_INTERVAL_SECONDS = 0.05
WAIT_TIMEOUT_SECONDS = 5.0


async def wait_until(
    predicate: Callable[[], object],
    *,
    description: str,
    timeout: float = WAIT_TIMEOUT_SECONDS,
    interval: float = 0.01,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        result = predicate()
        if inspect.isawaitable(result):
            result = await result
        if result:
            return
        if loop.time() >= deadline:
            pytest.fail(f"timed out after {timeout}s waiting for {description}")
        await asyncio.sleep(interval)


@pytest.mark.asyncio
async def test_only_one_supervisor_runs_services_and_successor_takes_over() -> None:
    coordinator = MemoryCoordinator(lease_ttl_seconds=LEASE_TTL_SECONDS)
    running: set[str] = set()
    max_running = 0

    def callbacks(worker_id: str):
        async def start() -> None:
            nonlocal max_running
            running.add(worker_id)
            max_running = max(max_running, len(running))

        async def stop() -> None:
            running.discard(worker_id)

        return start, stop

    start_a, stop_a = callbacks("a")
    start_b, stop_b = callbacks("b")
    first = BackgroundLeaderSupervisor(
        coordinator,
        "a",
        start_callbacks=[start_a],
        stop_callbacks=[stop_a],
        renew_interval_seconds=RENEW_INTERVAL_SECONDS,
        election_interval_seconds=ELECTION_INTERVAL_SECONDS,
    )
    second = BackgroundLeaderSupervisor(
        coordinator,
        "b",
        start_callbacks=[start_b],
        stop_callbacks=[stop_b],
        renew_interval_seconds=RENEW_INTERVAL_SECONDS,
        election_interval_seconds=ELECTION_INTERVAL_SECONDS,
    )
    try:
        await first.start()
        await second.start()
        await wait_until(lambda: len(running) == 1, description="one supervisor holds services")
        assert max_running == 1

        leader = next(iter(running))
        successor = "b" if leader == "a" else "a"
        await (first if leader == "a" else second).close()
        await wait_until(
            lambda: running == {successor},
            description="successor takes over services",
        )
        assert max_running == 1
    finally:
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_background_commands_run_once_and_continue_after_leader_transfer() -> None:
    coordinator = MemoryCoordinator(lease_ttl_seconds=LEASE_TTL_SECONDS)
    handled: list[tuple[str, str]] = []

    def callback(worker_id: str):
        async def handle(command) -> None:
            handled.append((worker_id, command.command_id))

        return handle

    first = BackgroundLeaderSupervisor(
        coordinator,
        "a",
        control_callback=callback("a"),
        renew_interval_seconds=RENEW_INTERVAL_SECONDS,
        election_interval_seconds=ELECTION_INTERVAL_SECONDS,
    )
    second = BackgroundLeaderSupervisor(
        coordinator,
        "b",
        control_callback=callback("b"),
        renew_interval_seconds=RENEW_INTERVAL_SECONDS,
        election_interval_seconds=ELECTION_INTERVAL_SECONDS,
    )
    try:
        await coordinator.submit_background_command("cron_reload", command_id="before")
        await first.start()
        await second.start()
        await wait_until(
            lambda: [command_id for _, command_id in handled] == ["before"],
            description="the leader handles the pending command exactly once",
        )

        leader = await coordinator.leader_id()
        assert leader in {"a", "b"}
        successor = "b" if leader == "a" else "a"
        await (first if leader == "a" else second).close()
        await wait_until(
            lambda: coordinator.leader_id(),
            description="successor acquires the leader lease",
        )
        assert await coordinator.leader_id() == successor
        await coordinator.submit_background_command("cron_reload", command_id="after")
        await wait_until(
            lambda: [command_id for _, command_id in handled] == ["before", "after"],
            description="the new leader handles the follow-up command",
        )

        assert handled[-1][0] != leader
    finally:
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_slow_service_start_keeps_leader_lease_alive() -> None:
    coordinator = MemoryCoordinator(lease_ttl_seconds=LEASE_TTL_SECONDS)
    started = asyncio.Event()
    release_start = asyncio.Event()
    contenders: list[str] = []

    async def slow_start() -> None:
        started.set()
        await release_start.wait()

    supervisor = BackgroundLeaderSupervisor(
        coordinator,
        "leader",
        start_callbacks=[slow_start],
        stop_callbacks=[lambda: asyncio.sleep(0)],
        renew_interval_seconds=RENEW_INTERVAL_SECONDS,
        election_interval_seconds=ELECTION_INTERVAL_SECONDS,
    )
    try:
        await supervisor.start()
        await asyncio.wait_for(started.wait(), timeout=WAIT_TIMEOUT_SECONDS)
        initial_lease = supervisor.lease
        assert initial_lease is not None
        await wait_until(
            lambda: (
                supervisor.lease is not None
                and supervisor.lease.expires_at
                >= initial_lease.expires_at + 2 * RENEW_INTERVAL_SECONDS
            ),
            description="heartbeat pushes the lease expiry past its original deadline",
        )
        contender = await coordinator.acquire_leader("contender")
        if contender is not None:
            contenders.append(contender.owner_id)

        assert contenders == []
        assert await coordinator.leader_id() == "leader"
    finally:
        release_start.set()
        await supervisor.close()
