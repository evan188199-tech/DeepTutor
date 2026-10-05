"""Terminal chat-stream error events must not carry raw exception text.

``str(exc)`` of an LLM/provider failure can embed provider URLs, request ids
and provider response bodies. These tests lock the neutral mapping: the live
error event, the DONE metadata and the persisted turn error (replayed later
by reconnect and orphaned-failed-turn reconcile) all carry a neutral message
plus a machine-readable ``error_code``; the raw text stays in server logs.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType, neutral_turn_error_message
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager, _TurnExecution

UPSTREAM_MARKERS = (
    "internal.gateway.example",
    "req_7f3a2b",
    "sk-live-9f2",
    "insufficient_quota",
    "RuntimeError",
    "503",
)


class _ProviderTransportError(RuntimeError):
    """Stands in for an LLM provider error whose str() carries upstream details."""

    error_code = "provider_transport"
    retryable = True


class FakeTurnEngine:
    def __init__(self) -> None:
        self.events: list[StreamEvent] = []
        self.error: BaseException | None = None
        self.contexts: list[Any] = []

    async def execute(self, context):
        self.contexts.append(context)
        for event in self.events:
            yield event
        if self.error is not None:
            raise self.error


class FakeContextBuilder:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def build(self, **_kwargs):
        return SimpleNamespace(
            conversation_history=[],
            conversation_summary="",
            context_text="",
            token_count=0,
            budget=0,
        )


def _payload() -> dict[str, Any]:
    return {
        "content": "what is 2+2?",
        "capability": "chat",
        "tools": [],
        "knowledge_bases": [],
        "attachments": [],
        "language": "en",
        "config": {},
    }


class RunTurnHarness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        self.engine = FakeTurnEngine()
        monkeypatch.setattr(
            "deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace()
        )
        monkeypatch.setattr(
            "deeptutor.services.session.context_builder.ContextBuilder",
            FakeContextBuilder,
        )
        from deeptutor.services.path_service import PathService
        from deeptutor.services.workspace import service as workspace_service_module

        paths = PathService(workspace_root=tmp_path / "runtime")
        paths.ensure_all_directories()
        monkeypatch.setattr(workspace_service_module, "get_path_service", lambda: paths)
        monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ROOT", raising=False)
        monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS", raising=False)
        self.store = SQLiteSessionStore(tmp_path / "turns.db")
        self.runtime = TurnRuntimeManager(self.store, turn_engine=self.engine)
        self.published: list[dict[str, Any]] = []

        original_publish = self.runtime._publish_live_event

        async def recording_publish(execution, event):
            payload = await original_publish(execution, event)
            self.published.append(payload)
            return payload

        monkeypatch.setattr(self.runtime, "_publish_live_event", recording_publish)
        monkeypatch.setattr(self.runtime, "_maybe_generate_session_title", self._no_title)

    @staticmethod
    async def _no_title(**_kwargs) -> None:
        return None

    async def run(self, payload: dict[str, Any] | None = None) -> _TurnExecution:
        session = await self.store.ensure_session(None)
        turn_id = f"turn_test_{uuid4().hex[:12]}"
        self.store._begin_turn_sync(session["id"], capability="chat", turn_id=turn_id)
        execution = _TurnExecution(
            turn_id=turn_id,
            session_id=session["id"],
            capability="chat",
            payload=payload or _payload(),
        )
        await self.runtime._run_turn(execution)
        return execution

    def published_of(self, *types: str) -> list[dict[str, Any]]:
        return [p for p in self.published if p.get("type") in types]

    async def turn_row(self, execution: _TurnExecution) -> dict[str, Any]:
        row = await self.store.get_turn(execution.turn_id)
        assert row is not None
        return row


class TestNeutralTurnErrorMessage:
    def test_known_codes_map_to_specific_messages(self) -> None:
        assert neutral_turn_error_message("provider_transport") == (
            "The AI service is temporarily unavailable. Please try again. "
            "(error code: provider_transport)"
        )
        assert neutral_turn_error_message("reasoning_budget_exhausted") == (
            "The model stopped before finishing its answer. Please try again. "
            "(error code: reasoning_budget_exhausted)"
        )

    def test_unknown_and_empty_codes_default_to_internal_error(self) -> None:
        expected = "The assistant response failed. Please try again. (error code: internal_error)"
        assert neutral_turn_error_message("") == expected
        assert neutral_turn_error_message("never_heard_of_it") == (
            "The assistant response failed. Please try again. (error code: never_heard_of_it)"
        )


@pytest.mark.asyncio
async def test_engine_exception_error_event_is_neutral_with_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    harness = RunTurnHarness(monkeypatch, tmp_path)
    harness.engine.error = _ProviderTransportError(
        "POST https://internal.gateway.example/v1/chat returned 503 "
        '(request id: req_7f3a2b) body: {"error": {"code": "insufficient_quota", '
        '"key_hint": "sk-live-9f2***"}}'
    )

    execution = await harness.run()

    error_events = harness.published_of("error")
    assert len(error_events) == 1
    error = error_events[0]
    assert error["content"] == (
        "The AI service is temporarily unavailable. Please try again. "
        "(error code: provider_transport)"
    )
    for marker in UPSTREAM_MARKERS:
        assert marker not in error["content"]
    assert error["metadata"] == {
        "turn_terminal": True,
        "status": "failed",
        "error_code": "provider_transport",
        "retryable": True,
    }

    done_events = harness.published_of("done")
    assert len(done_events) == 1
    assert done_events[0]["metadata"]["status"] == "failed"
    assert done_events[0]["metadata"]["error_code"] == "provider_transport"
    assert done_events[0]["metadata"]["retryable"] is True

    row = await harness.turn_row(execution)
    assert row["status"] == "failed"
    assert row["error"] == error["content"]
    assert row["failure_code"] == "provider_transport"
    assert row["retryable"] is True

    persisted = await harness.store.get_turn_events(execution.turn_id)
    persisted_errors = [e for e in persisted if e.get("type") == StreamEventType.ERROR.value]
    assert len(persisted_errors) == 1
    assert persisted_errors[0]["content"] == error["content"]
    for marker in UPSTREAM_MARKERS:
        assert marker not in str(persisted_errors[0])


@pytest.mark.asyncio
async def test_engine_exception_without_code_defaults_to_internal_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    harness = RunTurnHarness(monkeypatch, tmp_path)
    harness.engine.error = RuntimeError(
        "connection to https://internal.gateway.example reset (request id: req_7f3a2b)"
    )

    execution = await harness.run()

    error_events = harness.published_of("error")
    assert len(error_events) == 1
    assert error_events[0]["content"] == (
        "The assistant response failed. Please try again. (error code: internal_error)"
    )
    for marker in UPSTREAM_MARKERS:
        assert marker not in error_events[0]["content"]
    assert error_events[0]["metadata"]["error_code"] == "internal_error"
    assert error_events[0]["metadata"]["retryable"] is True

    row = await harness.turn_row(execution)
    assert row["status"] == "failed"
    assert row["error"] == error_events[0]["content"]
    assert row["failure_code"] == "internal_error"


@pytest.mark.asyncio
async def test_post_done_failure_never_surfaces_raw_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    harness = RunTurnHarness(monkeypatch, tmp_path)
    harness.engine.events = [
        StreamEvent(
            type=StreamEventType.CONTENT,
            source="chat",
            content="partial answer",
            metadata={"call_id": "c1", "call_kind": "llm_final_response"},
        ),
        StreamEvent(
            type=StreamEventType.DONE,
            source="chat",
            metadata={"status": "completed"},
        ),
    ]
    # A durable-log failure after the terminal DONE became visible must not
    # publish any new terminal event carrying the raw exception text; the
    # row was already settled, so nothing user-visible may leak either.
    state = {"done_visible": False}
    original_publish = harness.runtime._publish_live_event
    real_flush = harness.runtime._flush_buffered_events

    async def armed_publish(execution, event):
        payload = await original_publish(execution, event)
        if payload.get("type") == "done":
            state["done_visible"] = True
        return payload

    async def armed_flush(execution):
        if state["done_visible"]:
            raise RuntimeError(
                "flush failed: sqlite locked at /srv/data/turns.db (request id: req_deadbeef)"
            )
        return await real_flush(execution)

    monkeypatch.setattr(harness.runtime, "_publish_live_event", armed_publish)
    monkeypatch.setattr(harness.runtime, "_flush_buffered_events", armed_flush)

    execution = await harness.run()

    assert harness.published_of("error") == []
    assert [p["type"] for p in harness.published].count("done") == 1

    row = await harness.turn_row(execution)
    assert row["status"] == "completed"
    assert row["error"] == ""
    for marker in ("/srv/data/turns.db", "req_deadbeef", "sqlite locked"):
        assert marker not in row["error"]
        assert all(marker not in str(p.get("content") or "") for p in harness.published)
