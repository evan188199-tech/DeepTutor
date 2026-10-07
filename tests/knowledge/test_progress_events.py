"""Contract tests for deeptutor.knowledge.progress_events.

The module owns the two progress ports installed by the API layer and the
no-op defaults used by CLI/SDK callers.  These tests are table-driven pure
logic tests: they cover installation, payload pass-through fidelity, and
tolerance of absent ports / arbitrary payloads.  No server is started.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import deeptutor.knowledge.progress_events as progress_events
from deeptutor.knowledge.progress_events import (
    broadcast_progress,
    emit_task_progress,
    install_progress_ports,
)

# Payloads ranging from well-formed progress dicts to shapes the module
# never validates: forwarding must tolerate all of them without raising.
PAYLOAD_TABLE: list[tuple[str, Any]] = [
    ("canonical_progress", {
        "stage": "processing_documents",
        "message": "Embedding batches: 2/8 complete",
        "percent": 25,
        "current": 2,
        "total": 8,
    }),
    ("nested_unicode", {"msg": "进度 50%", "meta": {"batches": [1, 2, 3], "ok": True}}),
    ("empty_dict", {}),
    ("none_payload", None),
    ("list_payload", [1, "two", {"three": 3}]),
    ("string_payload", "not-a-dict"),
    ("int_payload", 42),
]


class BroadcastRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def __call__(self, kb_name: str, progress: Any) -> None:
        self.calls.append((kb_name, progress))


class EmitRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    def __call__(self, task_id: str, event: str, progress: Any) -> None:
        self.calls.append((task_id, event, progress))


@pytest.fixture(autouse=True)
def isolated_progress_ports(monkeypatch: pytest.MonkeyPatch):
    """Reset the module-level ports so tests never leak state into others."""
    monkeypatch.setattr(progress_events, "_broadcast", None)
    monkeypatch.setattr(progress_events, "_emit_task_event", None)


def test_module_exports_public_surface() -> None:
    assert set(progress_events.__all__) == {
        "broadcast_progress",
        "emit_task_progress",
        "install_progress_ports",
    }


@pytest.mark.parametrize(("label", "payload"), PAYLOAD_TABLE, ids=[c[0] for c in PAYLOAD_TABLE])
def test_uninstalled_defaults_are_silent_noops(label: str, payload: Any) -> None:
    # Fresh process defaults (and explicit None installs) must tolerate any
    # call without ports attached — the CLI/SDK contract.
    install_progress_ports(broadcast=None, emit_task_event=None)

    asyncio.run(broadcast_progress("kb", payload))
    emit_task_progress("task-1", payload)


def test_install_progress_ports_routes_both_channels() -> None:
    broadcast = BroadcastRecorder()
    emit = EmitRecorder()
    install_progress_ports(broadcast=broadcast, emit_task_event=emit)

    asyncio.run(broadcast_progress("demo-kb", {"percent": 25}))
    emit_task_progress("task-9", {"percent": 50})

    assert broadcast.calls == [("demo-kb", {"percent": 25})]
    assert emit.calls == [("task-9", "progress", {"percent": 50})]


@pytest.mark.parametrize("install_emit", [True, False], ids=["emit_only", "broadcast_only"])
def test_partial_install_only_installed_channel_routes(install_emit: bool) -> None:
    broadcast = BroadcastRecorder()
    emit = EmitRecorder()
    install_progress_ports(
        broadcast=broadcast if not install_emit else None,
        emit_task_event=emit if install_emit else None,
    )

    asyncio.run(broadcast_progress("kb-a", {"p": 1}))
    emit_task_progress("t-a", {"p": 2})

    if install_emit:
        assert broadcast.calls == []
        assert emit.calls == [("t-a", "progress", {"p": 2})]
    else:
        assert broadcast.calls == [("kb-a", {"p": 1})]
        assert emit.calls == []


def test_payload_forwarded_untouched_same_object() -> None:
    broadcast = BroadcastRecorder()
    emit = EmitRecorder()
    install_progress_ports(broadcast=broadcast, emit_task_event=emit)

    payload: dict[str, Any] = {
        "stage": "indexing",
        "percent": 66.5,
        "meta": {"nested": ["值", None, False]},
    }
    asyncio.run(broadcast_progress("知识库", payload))
    emit_task_progress("task-x", payload)

    # No serialization round-trip: both channels receive the very same object.
    assert broadcast.calls[0][0] == "知识库"
    assert broadcast.calls[0][1] is payload
    assert emit.calls[0][2] is payload
    assert payload == {
        "stage": "indexing",
        "percent": 66.5,
        "meta": {"nested": ["值", None, False]},
    }


@pytest.mark.parametrize(("label", "payload"), PAYLOAD_TABLE[:3], ids=[c[0] for c in PAYLOAD_TABLE[:3]])
def test_emit_task_progress_pins_event_name_to_progress(label: str, payload: Any) -> None:
    emit = EmitRecorder()
    install_progress_ports(broadcast=None, emit_task_event=emit)

    for task_id in ("t1", "t2", "task-with-unicode-任务"):
        emit_task_progress(task_id, payload)

    assert [call[0] for call in emit.calls] == ["t1", "t2", "task-with-unicode-任务"]
    assert {call[1] for call in emit.calls} == {"progress"}
    assert [call[2] for call in emit.calls] == [payload, payload, payload]


@pytest.mark.parametrize(("label", "payload"), PAYLOAD_TABLE, ids=[c[0] for c in PAYLOAD_TABLE])
def test_installed_ports_tolerate_arbitrary_payloads(label: str, payload: Any) -> None:
    broadcast = BroadcastRecorder()
    emit = EmitRecorder()
    install_progress_ports(broadcast=broadcast, emit_task_event=emit)

    # The ports layer does no payload validation; "invalid" payloads are
    # forwarded verbatim and it is up to the adapters to cope.
    asyncio.run(broadcast_progress("kb", payload))
    emit_task_progress("task", payload)

    assert broadcast.calls == [("kb", payload)]
    assert emit.calls == [("task", "progress", payload)]


def test_reinstall_with_none_resets_to_noop() -> None:
    broadcast = BroadcastRecorder()
    emit = EmitRecorder()
    install_progress_ports(broadcast=broadcast, emit_task_event=emit)
    emit_task_progress("t1", {"p": 1})

    # Same call shape the API shutdown path uses (deeptutor/api/main.py).
    install_progress_ports(broadcast=None, emit_task_event=None)

    asyncio.run(broadcast_progress("kb", {"p": 2}))
    emit_task_progress("t2", {"p": 3})

    assert emit.calls == [("t1", "progress", {"p": 1})]
    assert broadcast.calls == []


def test_reinstall_replaces_previous_ports() -> None:
    first = EmitRecorder()
    install_progress_ports(broadcast=None, emit_task_event=first)

    second = EmitRecorder()
    install_progress_ports(broadcast=None, emit_task_event=second)
    emit_task_progress("t-after", {"p": 1})

    assert first.calls == []
    assert second.calls == [("t-after", "progress", {"p": 1})]
