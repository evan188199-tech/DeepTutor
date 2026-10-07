"""Managed ``opencode serve`` instances — one live server per (CLI, workdir).

The opencode family (opencode and its fork MiMo-Code) exposes its best
streaming through a local HTTP server: ``<cli> serve`` + an SSE ``/event``
firehose with true token-level ``message.part.delta`` events — richer than the
part-granular ``run --format json`` subprocess mode. This module owns those
server processes so the backend can treat "a reachable server" as a primitive:

* One server per (CLI command, working directory), spawned lazily on first
  consult and **reused across consults and turns** — resumed sessions hit a
  warm server instead of paying a cold start each question.
* Loopback only, with a random per-spawn password passed via the CLI's server
  env vars, so another local user can't drive the agent through our port.
* Reaped after an idle TTL (checked on each acquire), terminated and reaped
  atexit (SIGTERM, escalating to SIGKILL), and
  respawned transparently if the process died in between.

Sessions live on the CLI's own disk storage (keyed by the workdir), so a
respawned server still resumes them — the server is a stateless doorway.
"""

from __future__ import annotations

import asyncio
import atexit
from dataclasses import dataclass, field
import logging
import os
import secrets
import socket
import time

import httpx

from deeptutor.services.subagent.process import resolve_cli_command

logger = logging.getLogger(__name__)

# How long a server may sit unused before the next acquire() reaps it.
_IDLE_TTL_SECONDS = 15 * 60
# How long we wait for a fresh spawn to start answering HTTP.
_READY_TIMEOUT_SECONDS = 30.0
_READY_POLL_SECONDS = 0.3
_TERMINATE_GRACE_SECONDS = 5.0
_REAP_POLL_SECONDS = 0.05


@dataclass(slots=True)
class ServerHandle:
    """One live ``<cli> serve`` process and how to talk to it."""

    base_url: str
    username: str
    password: str
    process: asyncio.subprocess.Process
    last_used: float = field(default_factory=time.monotonic)

    @property
    def alive(self) -> bool:
        return self.process.returncode is None

    def touch(self) -> None:
        self.last_used = time.monotonic()

    @property
    def auth(self) -> tuple[str, str]:
        return (self.username, self.password)


_servers: dict[tuple[str, str], ServerHandle] = {}
_lock = asyncio.Lock()


async def acquire_server(
    cli_command: str,
    *,
    cwd: str,
    env_prefix: str,
    username: str,
) -> ServerHandle:
    """A reachable server for this CLI + workdir — reused, or spawned fresh.

    ``env_prefix`` names the CLI's server env-var family (``OPENCODE`` /
    ``MIMOCODE``); ``username`` is the basic-auth user the CLI expects.
    """
    key = (cli_command, cwd or "")
    async with _lock:
        _reap_stale(except_key=key)
        handle = _servers.get(key)
        if handle is not None and handle.alive:
            handle.touch()
            return handle
        if handle is not None:  # died in between — clean up before respawn
            _terminate_sync(handle)
            _servers.pop(key, None)
        handle = await _spawn(cli_command, cwd=cwd, env_prefix=env_prefix, username=username)
        _servers[key] = handle
        return handle


async def _spawn(cli_command: str, *, cwd: str, env_prefix: str, username: str) -> ServerHandle:
    port = _free_port()
    password = secrets.token_urlsafe(16)
    env = {
        **os.environ,
        f"{env_prefix}_SERVER_PASSWORD": password,
        f"{env_prefix}_SERVER_USERNAME": username,
    }
    cli = resolve_cli_command([cli_command], path=env.get("PATH"))[0]
    process = await asyncio.create_subprocess_exec(
        cli,
        "serve",
        "--port",
        str(port),
        "--hostname",
        "127.0.0.1",
        cwd=cwd or None,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    handle = ServerHandle(
        base_url=f"http://127.0.0.1:{port}",
        username=username,
        password=password,
        process=process,
    )
    try:
        await _wait_ready(handle)
    except Exception:
        _terminate_sync(handle)
        raise
    logger.info("%s serve started on %s (cwd=%s)", cli_command, handle.base_url, cwd or ".")
    return handle


async def _wait_ready(handle: ServerHandle) -> None:
    """Poll until the server answers HTTP (any status means it's listening)."""
    deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
    async with httpx.AsyncClient(base_url=handle.base_url, auth=handle.auth) as client:
        while True:
            if not handle.alive:
                raise RuntimeError(
                    f"server exited during startup (code {handle.process.returncode})"
                )
            try:
                await client.get("/doc", timeout=2.0)
                return
            except httpx.HTTPError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("server did not become ready in time") from None
                await asyncio.sleep(_READY_POLL_SECONDS)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _reap_stale(*, except_key: tuple[str, str] | None = None) -> None:
    """Terminate servers idle past the TTL (called under the lock)."""
    now = time.monotonic()
    for key, handle in list(_servers.items()):
        if key == except_key:
            continue
        if not handle.alive or now - handle.last_used > _IDLE_TTL_SECONDS:
            _terminate_sync(handle)
            _servers.pop(key, None)


def _terminate_sync(handle: ServerHandle) -> None:
    if not handle.alive:
        return
    try:
        handle.process.terminate()
    except ProcessLookupError:
        pass


async def shutdown_servers() -> None:
    """Terminate every managed server and wait briefly (tests, app shutdown)."""
    async with _lock:
        handles = list(_servers.values())
        _servers.clear()
    for handle in handles:
        _terminate_sync(handle)
    for handle in handles:
        try:
            await asyncio.wait_for(handle.process.wait(), timeout=_TERMINATE_GRACE_SECONDS)
        except (TimeoutError, asyncio.TimeoutError):
            try:
                handle.process.kill()
            except ProcessLookupError:
                pass


def _wait_exit_sync(process: asyncio.subprocess.Process, timeout: float) -> bool:
    """Bounded synchronous wait for an asyncio child process to be gone.

    Watches the transport's ``returncode`` (set by the child watcher) and, on
    POSIX, probes the pid directly so teardown still converges once the owning
    event loop is closed.
    """
    deadline = time.monotonic() + timeout
    while True:
        if process.returncode is not None:
            return True
        pid = getattr(process, "pid", None)
        if pid is not None and os.name != "nt":
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
        if time.monotonic() >= deadline:
            return process.returncode is not None
        time.sleep(_REAP_POLL_SECONDS)


def _terminate_and_reap(handle: ServerHandle, *, grace_seconds: float) -> None:
    """Synchronous terminate → bounded wait → kill ladder for teardown paths."""
    process = handle.process
    if process.returncode is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        pass
    if _wait_exit_sync(process, grace_seconds):
        return
    try:
        process.kill()
    except ProcessLookupError:
        pass
    _wait_exit_sync(process, grace_seconds)


@atexit.register
def _atexit_cleanup() -> None:
    for handle in list(_servers.values()):
        _terminate_and_reap(handle, grace_seconds=_TERMINATE_GRACE_SECONDS)
    _servers.clear()


__all__ = ["ServerHandle", "acquire_server", "shutdown_servers"]
