"""Tests for the knowledge indexing progress ports (application layer)."""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.knowledge.progress_events import (
    broadcast_progress,
    emit_task_progress,
    install_progress_ports,
)


@pytest.fixture(autouse=True)
def _reset_progress_ports():
    """Every test starts and ends with the CLI/SDK no-op defaults installed."""
    install_progress_ports(broadcast=None, emit_task_event=None)
    yield
    install_progress_ports(broadcast=None, emit_task_event=None)


class TestNoOpDefaults:
    @pytest.mark.asyncio
    async def test_broadcast_without_port_is_silent(self) -> None:
        await broadcast_progress("kb", {"percent": 10})

    def test_emit_without_port_is_silent(self) -> None:
        emit_task_progress("task-1", {"percent": 10})


class TestInstalledPorts:
    @pytest.mark.asyncio
    async def test_broadcast_reaches_installed_port(self) -> None:
        seen: list[tuple[str, dict[str, Any]]] = []

        async def broadcast(kb_name: str, progress: dict[str, Any]) -> None:
            seen.append((kb_name, progress))

        install_progress_ports(broadcast=broadcast, emit_task_event=None)

        await broadcast_progress("kb-name", {"done": 3, "total": 9})

        assert seen == [("kb-name", {"done": 3, "total": 9})]

    def test_emit_reaches_installed_port_with_progress_kind(self) -> None:
        events: list[tuple[str, str, dict[str, Any]]] = []

        def emit(task_id: str, kind: str, progress: dict[str, Any]) -> None:
            events.append((task_id, kind, progress))

        install_progress_ports(broadcast=None, emit_task_event=emit)

        emit_task_progress("task-9", {"stage": "parse"})

        assert events == [("task-9", "progress", {"stage": "parse"})]

    @pytest.mark.asyncio
    async def test_reinstall_replaces_previous_ports(self) -> None:
        first_calls: list[str] = []

        async def first_broadcast(kb_name: str, progress: dict[str, Any]) -> None:
            first_calls.append(kb_name)

        install_progress_ports(broadcast=first_broadcast, emit_task_event=None)
        install_progress_ports(broadcast=None, emit_task_event=None)

        await broadcast_progress("kb", {})

        assert first_calls == []

    @pytest.mark.asyncio
    async def test_broadcast_exceptions_propagate(self) -> None:
        async def failing_broadcast(kb_name: str, progress: dict[str, Any]) -> None:
            raise RuntimeError("socket closed")

        install_progress_ports(broadcast=failing_broadcast, emit_task_event=None)

        with pytest.raises(RuntimeError, match="socket closed"):
            await broadcast_progress("kb", {})
