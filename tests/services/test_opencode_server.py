"""Unit tests for the opencode serve manager (services/subagent/opencode_server).

Covers the lifecycle contract (lazy spawn, warm reuse, respawn after a crash,
idle reaping, shutdown) and the failure paths (exit during startup, readiness
timeout) with a fully faked dependency layer: ``asyncio.create_subprocess_exec``
and ``httpx.AsyncClient`` are replaced by in-memory fakes, so no real
``<cli> serve`` process is ever spawned and no real HTTP server is started.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Any

import httpx
import pytest

from deeptutor.services.subagent import opencode_server
from deeptutor.services.subagent.opencode_server import (
    ServerHandle,
    acquire_server,
    shutdown_servers,
)

CLI = "opencode-fake-cli"
USERNAME = "opencode"


class FakeProcess:
    """The slice of ``asyncio.subprocess.Process`` the module relies on."""

    def __init__(
        self,
        argv: tuple[str, ...],
        *,
        cwd: str | None,
        env: dict[str, str],
        spawn_kwargs: dict[str, Any],
    ) -> None:
        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.spawn_kwargs = spawn_kwargs
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_delay = 0.0
        self.ignores_terminate = False

    def exit(self, code: int = 1) -> None:
        """Simulate the process dying on its own (e.g. the CLI failed to boot)."""
        self.returncode = code

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self.returncode is None and not self.ignores_terminate:
            self.returncode = -15

    def kill(self) -> None:
        self.kill_calls += 1
        if self.returncode is None:
            self.returncode = -9

    async def wait(self) -> int | None:
        if self.wait_delay:
            await asyncio.sleep(self.wait_delay)
        return self.returncode


class SpawnFactory:
    """Stands in for ``asyncio.create_subprocess_exec`` — records and fakes."""

    def __init__(self) -> None:
        self.processes: list[FakeProcess] = []
        self.pending_exit_code: int | None = None

    async def __call__(
        self, *argv: str, cwd: str | None = None, env: dict[str, str] | None = None, **kwargs: Any
    ) -> FakeProcess:
        process = FakeProcess(argv, cwd=cwd, env=dict(env or {}), spawn_kwargs=dict(kwargs))
        if self.pending_exit_code is not None:
            process.exit(self.pending_exit_code)
            self.pending_exit_code = None
        self.processes.append(process)
        return process


@dataclass
class RecordedRequest:
    base_url: str | None
    auth: tuple[str, str] | None
    path: str


def _make_fake_client() -> tuple[type, list[RecordedRequest]]:
    calls: list[RecordedRequest] = []

    class FakeAsyncClient:
        #: Outcomes consumed by ``get`` — exceptions are raised, ints become
        #: response statuses. Empty script means "ready on every request".
        script: list[Any] = []

        def __init__(
            self,
            base_url: str | None = None,
            auth: tuple[str, str] | None = None,
            **kwargs: Any,
        ) -> None:
            self.base_url = base_url
            self.auth = auth

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *exc_info: Any) -> bool:
            return False

        async def get(self, path: str, **kwargs: Any) -> httpx.Response:
            calls.append(RecordedRequest(self.base_url, self.auth, path))
            outcome = self.script.pop(0) if self.script else 200
            if isinstance(outcome, Exception):
                raise outcome
            return httpx.Response(int(outcome))

    return FakeAsyncClient, calls


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch):
    """Fresh module registry per test and a fast readiness poll."""
    monkeypatch.setattr(opencode_server, "_servers", {})
    monkeypatch.setattr(opencode_server, "_lock", asyncio.Lock())
    monkeypatch.setattr(opencode_server, "_READY_POLL_SECONDS", 0.01)
    yield
    # Safety net (mirrors the atexit hook): never leave a "live" fake behind.
    for handle in opencode_server._servers.values():
        if handle.process.returncode is None:
            handle.process.terminate()
    opencode_server._servers.clear()


@pytest.fixture(autouse=True)
def fake_httpx(monkeypatch: pytest.MonkeyPatch) -> tuple[type, list[RecordedRequest]]:
    client_cls, calls = _make_fake_client()
    monkeypatch.setattr(httpx, "AsyncClient", client_cls)
    return client_cls, calls


@pytest.fixture
def spawn(monkeypatch: pytest.MonkeyPatch) -> SpawnFactory:
    factory = SpawnFactory()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", factory)
    return factory


async def _acquire(cli: str = CLI, cwd: str = "") -> ServerHandle:
    return await acquire_server(cli, cwd=cwd, env_prefix="OPENCODE", username=USERNAME)


class TestStartup:
    @pytest.mark.asyncio
    async def test_acquire_spawns_serve_process_and_returns_ready_handle(
        self, spawn: SpawnFactory, fake_httpx: tuple[type, list[RecordedRequest]]
    ) -> None:
        client_cls, calls = fake_httpx
        client_cls.script.extend([httpx.ConnectError("not up yet"), 200])

        handle = await _acquire(cwd="/tmp/dt-oc-test")

        assert len(spawn.processes) == 1
        process = spawn.processes[0]
        port = handle.base_url.rsplit(":", 1)[1]
        assert process.argv == (CLI, "serve", "--port", port, "--hostname", "127.0.0.1")
        assert process.cwd == "/tmp/dt-oc-test"
        assert process.spawn_kwargs["stdin"] == asyncio.subprocess.DEVNULL
        assert process.spawn_kwargs["stdout"] == asyncio.subprocess.DEVNULL
        assert process.spawn_kwargs["stderr"] == asyncio.subprocess.DEVNULL
        assert process.env["OPENCODE_SERVER_PASSWORD"] == handle.password
        assert process.env["OPENCODE_SERVER_USERNAME"] == USERNAME
        assert handle.alive
        assert handle.auth == (USERNAME, handle.password)
        assert opencode_server._servers == {(CLI, "/tmp/dt-oc-test"): handle}

        assert [call.path for call in calls] == ["/doc", "/doc"]
        assert calls[0].base_url == handle.base_url
        assert calls[0].auth == handle.auth

    @pytest.mark.asyncio
    async def test_warm_server_is_reused_without_respawn(
        self, spawn: SpawnFactory, fake_httpx: tuple[type, list[RecordedRequest]]
    ) -> None:
        handle = await _acquire()
        before = handle.last_used

        handle.touch()
        again = await _acquire()

        assert again is handle
        assert handle.last_used >= before
        assert len(spawn.processes) == 1
        assert opencode_server._servers == {(CLI, ""): handle}

    @pytest.mark.asyncio
    async def test_ready_accepts_any_http_status(
        self, spawn: SpawnFactory, fake_httpx: tuple[type, list[RecordedRequest]]
    ) -> None:
        client_cls, _ = fake_httpx
        client_cls.script.append(404)

        handle = await _acquire()

        assert handle.alive
        assert len(spawn.processes) == 1


class TestEventStreamDoorway:
    @pytest.mark.asyncio
    async def test_handle_credentials_drive_event_stream_requests(
        self, spawn: SpawnFactory, fake_httpx: tuple[type, list[RecordedRequest]]
    ) -> None:
        client_cls, calls = fake_httpx
        handle = await _acquire()

        async with client_cls(base_url=handle.base_url, auth=handle.auth) as client:
            response = await client.get("/event")

        assert response.status_code == 200
        event_calls = [call for call in calls if call.path == "/event"]
        assert len(event_calls) == 1
        assert event_calls[0].base_url == handle.base_url
        assert event_calls[0].auth == (USERNAME, handle.password)

    @pytest.mark.asyncio
    async def test_each_workdir_gets_its_own_server_and_secret(
        self, spawn: SpawnFactory, fake_httpx: tuple[type, list[RecordedRequest]]
    ) -> None:
        first = await _acquire(cwd="/tmp/ws-a")
        second = await _acquire(cwd="/tmp/ws-b")

        assert first is not second
        assert first.base_url != second.base_url
        assert first.password != second.password
        assert first.process.env["OPENCODE_SERVER_PASSWORD"] == first.password
        assert second.process.env["OPENCODE_SERVER_PASSWORD"] == second.password
        assert set(opencode_server._servers) == {(CLI, "/tmp/ws-a"), (CLI, "/tmp/ws-b")}


class TestAbnormalExit:
    @pytest.mark.asyncio
    async def test_exit_during_startup_raises_and_leaves_no_handle(
        self, spawn: SpawnFactory, fake_httpx: tuple[type, list[RecordedRequest]]
    ) -> None:
        spawn.pending_exit_code = 1

        with pytest.raises(RuntimeError, match="exited during startup"):
            await _acquire()

        assert opencode_server._servers == {}
        process = spawn.processes[0]
        assert process.returncode == 1
        assert process.terminate_calls == 0

    @pytest.mark.asyncio
    async def test_startup_timeout_terminates_process_and_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
        spawn: SpawnFactory,
        fake_httpx: tuple[type, list[RecordedRequest]],
    ) -> None:
        monkeypatch.setattr(opencode_server, "_READY_TIMEOUT_SECONDS", 0.15)
        client_cls, _ = fake_httpx
        client_cls.script.extend([httpx.ConnectError("refused")] * 100)

        with pytest.raises(RuntimeError, match="did not become ready"):
            await _acquire()

        assert opencode_server._servers == {}
        assert spawn.processes[0].terminate_calls == 1

    @pytest.mark.asyncio
    async def test_crashed_server_is_respawned_on_next_acquire(
        self, spawn: SpawnFactory, fake_httpx: tuple[type, list[RecordedRequest]]
    ) -> None:
        handle = await _acquire()
        handle.process.exit(137)

        respawned = await _acquire()

        assert respawned is not handle
        assert respawned.alive
        assert respawned.base_url != handle.base_url
        assert len(spawn.processes) == 2
        assert handle.process.returncode == 137
        assert handle.process.terminate_calls == 0
        assert opencode_server._servers == {(CLI, ""): respawned}

    @pytest.mark.asyncio
    async def test_idle_stale_server_is_reaped_by_another_keys_acquire(
        self, spawn: SpawnFactory, fake_httpx: tuple[type, list[RecordedRequest]]
    ) -> None:
        stale = await _acquire(cwd="/tmp/ws-a")
        warm = await _acquire("mimo-fake-cli", cwd="/tmp/ws-b")
        stale.last_used = time.monotonic() - (opencode_server._IDLE_TTL_SECONDS + 1)

        again = await _acquire("mimo-fake-cli", cwd="/tmp/ws-b")

        assert again is warm
        assert len(spawn.processes) == 2
        assert stale.process.terminate_calls == 1
        assert stale.process.returncode == -15
        assert opencode_server._servers == {("mimo-fake-cli", "/tmp/ws-b"): warm}

    @pytest.mark.asyncio
    async def test_shutdown_terminates_every_server(
        self, spawn: SpawnFactory, fake_httpx: tuple[type, list[RecordedRequest]]
    ) -> None:
        first = await _acquire(cwd="/tmp/ws-a")
        second = await _acquire("mimo-fake-cli", cwd="/tmp/ws-b")

        await shutdown_servers()

        assert opencode_server._servers == {}
        for handle in (first, second):
            assert handle.process.terminate_calls == 1
            assert handle.process.returncode == -15

    @pytest.mark.asyncio
    async def test_shutdown_kills_processes_that_ignore_grace(
        self,
        monkeypatch: pytest.MonkeyPatch,
        spawn: SpawnFactory,
        fake_httpx: tuple[type, list[RecordedRequest]],
    ) -> None:
        monkeypatch.setattr(opencode_server, "_TERMINATE_GRACE_SECONDS", 0.05)
        handle = await _acquire()
        handle.process.ignores_terminate = True
        handle.process.wait_delay = 1.0

        await shutdown_servers()

        assert handle.process.terminate_calls == 1
        assert handle.process.kill_calls == 1
        assert handle.process.returncode == -9
