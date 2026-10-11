"""PartnerGroupBackend consult orchestration: assembly, idle statuses, degradation."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import re
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.services.partner_groups.models import PartnerGroupConfig
from deeptutor.services.subagent import partner_group as partner_group_module
from deeptutor.services.subagent.partner_group import PartnerGroupBackend

GROUP = PartnerGroupConfig(
    group_id="panel",
    owner_id="owner",
    name="Panel",
    member_ids=["ada", "bob"],
)


class FakeWindow:
    def __init__(self, remaining_values: list[Any]) -> None:
        self.remaining_values = list(remaining_values)
        self.calls: list[dict[str, Any]] = []

    def remaining(self, *, busy: bool, revision: object) -> Any:
        self.calls.append({"busy": busy, "revision": revision})
        if len(self.remaining_values) > 1:
            return self.remaining_values.pop(0)
        return self.remaining_values[0]


class FakeOperation:
    def __init__(self, task: asyncio.Task | None = None) -> None:
        self.task = task


class FakeManager:
    def __init__(
        self,
        *,
        group: Any = GROUP,
        window: FakeWindow | None = None,
        message_snapshots: list[list[dict[str, Any]]] | None = None,
        invocation_snapshots: list[list[dict[str, Any]]] | None = None,
        operation_snapshots: list[list[FakeOperation]] | None = None,
    ) -> None:
        self.group = group
        self.window = window or FakeWindow([0])
        self.message_snapshots = message_snapshots or [[]]
        self.invocation_snapshots = invocation_snapshots or [[]]
        self.operation_snapshots = operation_snapshots or [[]]
        self.group_query: str | None = None
        self.live_turn_args: dict[str, Any] | None = None
        self.begin_calls: list[tuple[str, str]] = []
        self.end_calls: list[tuple[str, str, Any]] = []
        self.history_limits: list[int] = []
        self.invocation_limits: list[int] = []

    @staticmethod
    def _next(snapshots: list[Any]) -> Any:
        if len(snapshots) > 1:
            return snapshots.pop(0)
        return list(snapshots[0])

    def get_group(self, group_id: str) -> Any:
        self.group_query = group_id
        return self.group

    def start_live_turn(
        self, group_id: str, *, content: str, session_key: str, mentions=None
    ) -> None:
        self.live_turn_args = {
            "group_id": group_id,
            "content": content,
            "session_key": session_key,
            "mentions": list(mentions or []),
        }

    def begin_consultation(self, group_id: str, session_key: str) -> Any:
        self.begin_calls.append((group_id, session_key))
        return self.window

    def end_consultation(self, group_id: str, session_key: str, window: Any) -> None:
        self.end_calls.append((group_id, session_key, window))

    def history(self, group_id: str, session_key: str, *, limit: int = 200) -> list[dict]:
        self.history_limits.append(limit)
        return self._next(self.message_snapshots)

    def invocations(self, group_id: str, session_key: str, *, limit: int = 200) -> list[dict]:
        self.invocation_limits.append(limit)
        return self._next(self.invocation_snapshots)

    def subscribe_live_turns(self, group_id: str, session_key: str) -> list[FakeOperation]:
        return self._next(self.operation_snapshots)


def _patch_manager(monkeypatch: pytest.MonkeyPatch, manager: FakeManager) -> None:
    monkeypatch.setattr(
        "deeptutor.services.partner_groups.manager.get_partner_group_manager",
        lambda: manager,
    )


def _collector():
    events: list[Any] = []

    async def on_event(event) -> None:
        events.append(event)

    return events, on_event


def _message(
    event_id: str,
    role: str,
    content: str,
    *,
    author: str | None = None,
    kind: str = "message",
    error: bool = False,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "event_id": event_id,
        "role": role,
        "kind": kind,
        "error": error,
        "content": content,
    }
    if author is not None:
        row["author_name"] = author
    return row


def _invocation(invocation_id: str, status: str) -> dict[str, Any]:
    return {
        "invocation_id": invocation_id,
        "status": status,
        "requester_partner_name": "Ada",
        "target_partner_name": "Bob",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("partner_id", [None, "panel", "ghost"])
async def test_missing_group_fails_without_starting_any_session(
    monkeypatch: pytest.MonkeyPatch, partner_id
) -> None:
    manager = FakeManager(group=None)
    _patch_manager(monkeypatch, manager)
    events, on_event = _collector()

    result = await PartnerGroupBackend().consult("q", on_event=on_event, partner_id=partner_id)

    assert result.success is False
    assert result.error == "Partner Group is unavailable."
    assert result.final_text == ""
    assert result.session_id is None
    assert result.event_count == 0
    assert manager.group_query == (partner_id or "")
    assert manager.live_turn_args is None
    assert manager.begin_calls == []
    assert manager.end_calls == []
    assert events == []


@pytest.mark.asyncio
async def test_completion_seals_window_and_assembles_public_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finished = asyncio.create_task(asyncio.sleep(0))
    await finished
    window = FakeWindow([None, 7, 0])
    manager = FakeManager(
        window=window,
        message_snapshots=[
            [_message("e1", "user", "What is X?")],
            [
                _message("e1", "user", "What is X?"),
                _message("e2", "partner", "X is algebra.", author="Ada"),
            ],
            [
                _message("e1", "user", "What is X?"),
                _message("e2", "partner", "X is algebra.", author="Ada"),
                _message("e3", "partner", "boom", author="Bob", kind="summary", error=True),
            ],
        ],
        invocation_snapshots=[[_invocation("i1", "pending")], [_invocation("i1", "rejected")]],
        operation_snapshots=[[FakeOperation(task=None), FakeOperation(task=finished)], [], []],
    )
    _patch_manager(monkeypatch, manager)
    events, on_event = _collector()

    result = await PartnerGroupBackend().consult(
        "Discuss X", on_event=on_event, partner_id="panel", session_id="dt-fixed"
    )

    assert result.success is True
    assert result.error == ""
    assert result.session_id == "dt-fixed"
    assert "user (message):\nWhat is X?" in result.final_text
    assert "Ada (message):\nX is algebra." in result.final_text
    assert "Bob (summary, failed):\nboom" in result.final_text
    assert result.final_text.endswith("Follow-up decisions:\nAda → Bob: rejected")
    assert manager.live_turn_args == {
        "group_id": "panel",
        "content": "Discuss X",
        "session_key": "dt-fixed",
        "mentions": ["ada", "bob"],
    }
    assert manager.begin_calls == [("panel", "dt-fixed")]
    assert manager.history_limits == [10000, 10000, 10000]
    assert manager.invocation_limits == [10000, 10000, 10000]
    assert [call["busy"] for call in window.calls] == [True, False, False]
    assert window.calls[2]["revision"] == (
        ("e1", "e2", "e3"),
        (("i1", "rejected"),),
    )
    assert [event.kind for event in events] == ["log", "log", "log"]
    assert [event.text for event in events] == ["Panel", "Panel", "Panel"]
    assert [event.meta["partner_group_consultation_status"] for event in events] == [
        "discussing",
        "waiting",
        "completed",
    ]
    assert [event.meta["partner_group_idle_seconds"] for event in events] == [None, 7, 0]
    for event in events:
        assert event.meta["merge_id"] == "group-wait"
        assert event.meta["partner_group_id"] == "panel"
        assert event.meta["partner_group_session_key"] == "dt-fixed"
    assert result.event_count == 3
    assert len(manager.end_calls) == 2
    assert all(call[2] is window for call in manager.end_calls)
    assert {call[:2] for call in manager.end_calls} == {("panel", "dt-fixed")}


@pytest.mark.asyncio
async def test_first_consult_mints_session_key_and_degrades_without_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = FakeManager(window=FakeWindow([0]))
    _patch_manager(monkeypatch, manager)
    events, on_event = _collector()

    result = await PartnerGroupBackend().consult("Hi", on_event=on_event, partner_id="panel")

    session_key = manager.live_turn_args["session_key"]
    assert re.fullmatch(r"dt-[0-9a-f]{12}", session_key)
    assert result.session_id == session_key
    assert manager.begin_calls == [("panel", session_key)]
    assert result.success is False
    assert result.error == "The discussion produced no messages."
    assert result.final_text == ""
    assert result.event_count == 1
    assert events[0].meta["partner_group_consultation_status"] == "completed"


@pytest.mark.asyncio
async def test_transcript_without_successful_partner_answer_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = FakeManager(
        window=FakeWindow([0]),
        message_snapshots=[
            [
                _message("e1", "user", "Hello"),
                _message("e2", "partner", "crashed", author="Ada", error=True),
            ]
        ],
    )
    _patch_manager(monkeypatch, manager)
    events, on_event = _collector()

    result = await PartnerGroupBackend().consult(
        "Hi", on_event=on_event, partner_id="panel", session_id="dt-fail"
    )

    assert result.success is False
    assert result.error == ""
    assert result.final_text.startswith("user (message):\nHello")
    assert "Ada (message, failed):\ncrashed" in result.final_text


@pytest.mark.asyncio
async def test_repeated_status_is_suppressed_until_idle_or_fifteen_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    real_sleep = asyncio.sleep

    async def paced_sleep(_seconds: float) -> None:
        clock[0] += 8
        await real_sleep(0)

    monkeypatch.setattr(partner_group_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(partner_group_module, "asyncio", SimpleNamespace(sleep=paced_sleep))
    manager = FakeManager(window=FakeWindow([7, 7, 7, 0]))
    _patch_manager(monkeypatch, manager)
    events, on_event = _collector()

    result = await PartnerGroupBackend().consult(
        "Hi", on_event=on_event, partner_id="panel", session_id="dt-pace"
    )

    assert result.event_count == 3
    assert [event.meta["partner_group_consultation_status"] for event in events] == [
        "waiting",
        "waiting",
        "completed",
    ]
    assert [event.meta["partner_group_idle_seconds"] for event in events] == [7, 7, 0]


@pytest.mark.asyncio
async def test_cancellation_cancels_live_turns_and_still_ends_consultation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_task = asyncio.create_task(asyncio.sleep(30))
    window = FakeWindow([None])
    manager = FakeManager(
        window=window,
        operation_snapshots=[[FakeOperation(task=live_task)]],
    )
    _patch_manager(monkeypatch, manager)
    started = asyncio.Event()
    events: list[Any] = []

    async def on_event(event) -> None:
        events.append(event)
        started.set()

    task = asyncio.create_task(
        PartnerGroupBackend().consult(
            "q", on_event=on_event, partner_id="panel", session_id="dt-cancel"
        )
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
    except BaseException:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        live_task.cancel()
        raise
    assert window.calls[0]["busy"] is True
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with suppress(asyncio.CancelledError):
        await live_task
    assert live_task.cancelled()
    assert manager.end_calls and manager.end_calls[0][2] is window
    assert manager.live_turn_args["session_key"] == "dt-cancel"
    assert events[0].meta["partner_group_consultation_status"] == "discussing"
