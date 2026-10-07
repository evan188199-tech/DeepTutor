"""The SHARED_OWNER lock must not span a connection's whole lifecycle.

``reload`` re-reads the admin config and connects servers that were added or
changed. Connecting is slow — a transport open, a session handshake, a tool
listing, up to the 15s connect timeout per server. Holding the owner lock
across it made every other lock taker wait out that connect: a session whose
first turn called ``ensure_started`` (via the failed-server retry path) sat
behind an unrelated server's handshake before it could establish its own
connections. The tests here pin the lock's scope to the connection-table
changes instead.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deeptutor.runtime.registry.tool_registry import ToolRegistry
from deeptutor.services.mcp.config import MCPConfig, MCPServerConfig
from deeptutor.services.mcp.manager import (
    SHARED_OWNER,
    MCPConnectionManager,
    MCPToolAdapter,
    _ServerConnection,
)


@pytest.fixture(autouse=True)
def _isolated_data_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from deeptutor.multi_user import paths

    root = (tmp_path / "data").resolve()
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", root)
    monkeypatch.setattr(paths, "USERS_ROOT", root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", root / "system")


@pytest.fixture(autouse=True)
def _offline_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    monkeypatch.setattr(
        "deeptutor.services.mcp.network.socket.getaddrinfo",
        lambda host, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )


def _fake_run_server_factory(
    gates: dict[str, asyncio.Event], started: dict[str, asyncio.Event], sessions: list[str]
):
    """A ``_run_server`` whose per-name gates decide when connecting completes."""

    async def _fake_run_server(self, conn, ready) -> None:  # type: ignore[no-untyped-def]
        sessions.append(conn.name)
        gate = gates.get(conn.name)
        if gate is not None:
            signal = started.setdefault(conn.name, asyncio.Event())
            signal.set()
            await gate.wait()
        conn.session = object()
        conn.adapters = [
            MCPToolAdapter(
                manager=self,
                owner=conn.owner,
                server_name=conn.name,
                original_name="ping",
                description="d",
                input_schema=None,
                tool_timeout=5,
            )
        ]
        if not ready.done():
            ready.set_result(None)
        await conn.shutdown.wait()

    return _fake_run_server


@pytest.mark.asyncio
async def test_reload_in_progress_does_not_block_a_new_sessions_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new session's ``ensure_started`` must establish its own connection
    while an unrelated reload is still mid-handshake on another server."""
    monkeypatch.setattr(MCPConnectionManager, "_registry", staticmethod(ToolRegistry))

    slow_release = asyncio.Event()
    gates = {"slow": slow_release}
    started: dict[str, asyncio.Event] = {"slow": asyncio.Event()}
    sessions: list[str] = []
    monkeypatch.setattr(
        MCPConnectionManager,
        "_run_server",
        _fake_run_server_factory(gates, started, sessions),
    )

    cfg_slow = MCPServerConfig(url="https://slow.example/mcp")
    cfg_fast = MCPServerConfig(url="https://fast.example/mcp")
    monkeypatch.setattr(
        "deeptutor.services.mcp.manager.load_mcp_config",
        lambda: MCPConfig(servers={"slow": cfg_slow, "fast": cfg_fast}),
    )

    # The app is already running; "fast" failed earlier and is due for retry.
    manager = MCPConnectionManager()
    manager._started = True
    failed = _ServerConnection(
        name="fast",
        config=cfg_fast,
        signature=MCPConnectionManager._signature(cfg_fast, SHARED_OWNER),
        owner=SHARED_OWNER,
        status="error",
    )
    failed.retry_at = 0.0
    manager._connections[(SHARED_OWNER, "fast")] = failed

    # An administrator saves the config: reload starts connecting "slow".
    reload_task = asyncio.create_task(manager.reload())
    await asyncio.wait_for(started["slow"].wait(), timeout=5)

    # A new session begins its first turn while that connect is in flight.
    try:
        await asyncio.wait_for(manager.ensure_started(), timeout=2.0)
    except asyncio.TimeoutError:
        pytest.fail("ensure_started blocked behind reload's in-flight connection")
        return

    conn = manager._connections.get((SHARED_OWNER, "fast"))
    assert conn is not None and conn.status == "connected"
    # The table stayed consistent mid-reload: one entry per configured server.
    assert set(manager._connections) == {(SHARED_OWNER, "fast"), (SHARED_OWNER, "slow")}

    slow_release.set()
    await asyncio.wait_for(reload_task, timeout=5)
    assert manager._connections[(SHARED_OWNER, "slow")].status == "connected"
    assert sorted(sessions) == ["fast", "slow"]
    await manager.shutdown()


@pytest.mark.asyncio
async def test_concurrent_starts_connect_each_server_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two sessions starting at once must not double-connect a server.

    Narrowing the lock means the connect awaits overlap; the table insert
    under the lock is what keeps a server connected exactly once.
    """
    monkeypatch.setattr(MCPConnectionManager, "_registry", staticmethod(ToolRegistry))

    gates: dict[str, asyncio.Event] = {}
    started: dict[str, asyncio.Event] = {}
    sessions: list[str] = []
    monkeypatch.setattr(
        MCPConnectionManager,
        "_run_server",
        _fake_run_server_factory(gates, started, sessions),
    )

    cfg = MCPServerConfig(url="https://one.example/mcp")
    monkeypatch.setattr(
        "deeptutor.services.mcp.manager.load_mcp_config",
        lambda: MCPConfig(servers={"one": cfg}),
    )

    manager = MCPConnectionManager()
    await asyncio.gather(manager.ensure_started(), manager.ensure_started())

    assert sessions == ["one"], f"server connected {len(sessions)} times: {sessions}"
    conn = manager._connections.get((SHARED_OWNER, "one"))
    assert conn is not None and conn.status == "connected"
    await manager.shutdown()
