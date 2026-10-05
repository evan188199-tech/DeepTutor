"""Mainline state transitions and primary error paths of ``TurnExecutor._run_turn``.

Focused, fully-mocked slice: no LLM, no services. The cancellation family
(``asyncio.CancelledError`` from an explicit learner cancel) is covered by
``test_turn_cancel.py`` (AGEN-605) and deliberately out of scope here; the one
cancellation-shaped path in scope is the terminal-transition fencing
rejection, which aborts the turn without any terminal event.

Covered families:
- normal completion: row persistence, DONE reconciliation metadata, DONE
  synthesis when the engine forgets it, round retraction, artifact
  attachments, regenerate chaining, engine-reported terminal errors;
- LLM/engine exceptions: generic and provider-coded failures, plus a
  post-DONE persistence failure (``stream_done_sent`` branch);
- persistence failures: user-row and assistant-row write failures, and the
  terminal transition losing the fencing race.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager, _TurnExecution


class FakeTurnEngine:
    """Stands in for the real turn engine; replays canned stream events."""

    def __init__(
        self,
        events: list[StreamEvent] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.events = events or []
        self.error = error
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


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "content": "what is 2+2?",
        "capability": "chat",
        "tools": [],
        "knowledge_bases": [],
        "attachments": [],
        "language": "en",
        "config": {},
    }
    payload.update(overrides)
    return payload


async def _begin_turn(store: SQLiteSessionStore, capability: str = "chat") -> tuple[str, str]:
    session = await store.ensure_session(None)
    turn_id = f"turn_test_{uuid4().hex[:12]}"
    store._begin_turn_sync(session["id"], capability=capability, turn_id=turn_id)
    return session["id"], turn_id


class RunTurnHarness:
    """Boots a real ``TurnRuntimeManager`` against a temp SQLite store and
    records every event ``_run_turn`` publishes."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        self.engine = FakeTurnEngine()
        monkeypatch.setattr(
            "deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace()
        )
        monkeypatch.setattr(
            "deeptutor.services.session.context_builder.ContextBuilder",
            FakeContextBuilder,
        )
        # Give the content workspace service a real, empty root so the
        # per-turn runtime context can create its outputs folder.
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
        self.title_calls: list[dict[str, Any]] = []

        original_publish = self.runtime._publish_live_event

        async def recording_publish(execution, event):
            payload = await original_publish(execution, event)
            self.published.append(payload)
            return payload

        async def recording_title(**kwargs):
            self.title_calls.append(kwargs)

        monkeypatch.setattr(self.runtime, "_publish_live_event", recording_publish)
        monkeypatch.setattr(self.runtime, "_maybe_generate_session_title", recording_title)

    async def new_execution(self, payload: dict[str, Any]) -> _TurnExecution:
        session_id, turn_id = await _begin_turn(self.store)
        return _TurnExecution(
            turn_id=turn_id,
            session_id=session_id,
            capability=str(payload.get("capability") or "chat"),
            payload=payload,
        )

    async def run(self, payload: dict[str, Any]) -> _TurnExecution:
        execution = await self.new_execution(payload)
        await self.runtime._run_turn(execution)
        return execution

    async def turn_row(self, execution: _TurnExecution) -> dict[str, Any]:
        row = await self.store.get_turn(execution.turn_id)
        assert row is not None
        return row

    async def messages(self, execution: _TurnExecution) -> list[dict[str, Any]]:
        return await self.store.get_messages(execution.session_id)

    def published_of(self, *types: str) -> list[dict[str, Any]]:
        return [p for p in self.published if p.get("type") in types]


@pytest.mark.asyncio
async def test_completed_turn_persists_rows_and_reconciles_done_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    harness = RunTurnHarness(monkeypatch, tmp_path)
    harness.engine.events = [
        StreamEvent(
            type=StreamEventType.CONTENT,
            source="chat",
            stage="responding",
            content="4",
            metadata={"call_id": "c1", "call_kind": "llm_final_response"},
        ),
        StreamEvent(
            type=StreamEventType.DONE,
            source="chat",
            metadata={
                "status": "completed",
                "usage_summary": {"total_tokens": 10, "total_calls": 1},
            },
        ),
    ]

    execution = await harness.run(_payload())
    assert len(harness.engine.contexts) == 1

    messages = await harness.messages(execution)
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "what is 2+2?"
    assert messages[1]["content"] == "4"

    row = await harness.turn_row(execution)
    assert row["status"] == "completed"
    assert row["error"] == ""
    assert row["failure_code"] == ""

    done_events = harness.published_of("done")
    assert len(done_events) == 1
    done = done_events[0]
    assert done["metadata"]["status"] == "completed"
    assert done["metadata"]["usage_summary"] == {"total_tokens": 10, "total_calls": 1}
    assert done["metadata"]["user_message_id"] == messages[0]["id"]
    assert done["metadata"]["assistant_message_id"] == messages[1]["id"]

    # Post-turn title generation runs exactly once for a non-regenerate
    # completed turn, after the assistant row is durable.
    assert len(harness.title_calls) == 1
    assert harness.title_calls[0]["session_id"] == execution.session_id

    # The per-turn reply queue and execution bookkeeping are cleaned up.
    assert execution.turn_id not in harness.runtime._reply_queues


@pytest.mark.asyncio
async def test_engine_finishing_without_done_synthesizes_completed_done(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    harness = RunTurnHarness(monkeypatch, tmp_path)
    harness.engine.events = [
        StreamEvent(
            type=StreamEventType.CONTENT,
            source="chat",
            content="short answer",
            metadata={"call_id": "c1", "call_kind": "llm_final_response"},
        ),
    ]

    execution = await harness.run(_payload())

    row = await harness.turn_row(execution)
    assert row["status"] == "completed"

    done_events = harness.published_of("done")
    assert len(done_events) == 1
    assert done_events[0]["metadata"]["status"] == "completed"
    assert "usage_summary" not in done_events[0]["metadata"]


@pytest.mark.asyncio
async def test_retracted_round_is_dropped_from_persisted_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    harness = RunTurnHarness(monkeypatch, tmp_path)
    harness.engine.events = [
        StreamEvent(
            type=StreamEventType.CONTENT,
            source="chat",
            content="let me check one thing.",
            metadata={"call_id": "r1", "call_kind": "llm_final_response"},
        ),
        StreamEvent(
            type=StreamEventType.PROGRESS,
            source="chat",
            metadata={
                "trace_kind": "call_status",
                "call_state": "complete",
                "call_id": "r1",
                "call_role": "narration",
                "answer_visible": False,
            },
        ),
        StreamEvent(
            type=StreamEventType.CONTENT,
            source="chat",
            content="the answer is 42",
            metadata={"call_id": "r2", "call_kind": "llm_final_response"},
        ),
        StreamEvent(
            type=StreamEventType.DONE,
            source="chat",
            metadata={"status": "completed"},
        ),
    ]

    execution = await harness.run(_payload())

    messages = await harness.messages(execution)
    assert messages[1]["content"] == "the answer is 42"
    row = await harness.turn_row(execution)
    assert row["status"] == "completed"


@pytest.mark.asyncio
async def test_generated_artifacts_are_deduped_onto_assistant_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    harness = RunTurnHarness(monkeypatch, tmp_path)
    artifact_a = {
        "type": "artifact",
        "url": "/files/outputs/a.csv",
        "filename": "a.csv",
        "mime_type": "text/csv",
        "size_bytes": 3,
    }
    harness.engine.events = [
        StreamEvent(
            type=StreamEventType.SOURCES,
            source="chat",
            metadata={
                "sources": [
                    artifact_a,
                    dict(artifact_a),
                    {
                        "type": "artifact",
                        "url": "/files/outputs/b.png",
                        "filename": "b.png",
                        "mime_type": "image/png",
                    },
                ]
            },
        ),
        StreamEvent(
            type=StreamEventType.SOURCES,
            source="chat",
            metadata={"sources": [dict(artifact_a)]},
        ),
        StreamEvent(
            type=StreamEventType.DONE,
            source="chat",
            metadata={"status": "completed"},
        ),
    ]

    execution = await harness.run(_payload())

    messages = await harness.messages(execution)
    attachments = messages[1]["attachments"]
    assert [a["url"] for a in attachments] == [
        "/files/outputs/a.csv",
        "/files/outputs/b.png",
    ]
    assert all(a["generated"] for a in attachments)
    row = await harness.turn_row(execution)
    assert row["status"] == "completed"


@pytest.mark.asyncio
async def test_regenerate_chains_assistant_to_regenerated_message_without_new_user_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    harness = RunTurnHarness(monkeypatch, tmp_path)
    execution = await harness.new_execution(
        _payload(
            persist_user_message=False,
            regenerate=True,
            regenerated_from_message_id=0,
        )
    )
    original_user_id = await harness.store.add_message(
        session_id=execution.session_id,
        role="user",
        content="original question",
        capability="chat",
    )
    execution.payload["regenerated_from_message_id"] = original_user_id

    harness.engine.events = [
        StreamEvent(
            type=StreamEventType.CONTENT,
            source="chat",
            content="second attempt",
            metadata={"call_id": "c1", "call_kind": "llm_final_response"},
        ),
        StreamEvent(
            type=StreamEventType.DONE,
            source="chat",
            metadata={"status": "completed"},
        ),
    ]
    await harness.runtime._run_turn(execution)

    messages = await harness.messages(execution)
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["id"] == original_user_id
    assert messages[1]["content"] == "second attempt"
    assert messages[1]["parent_message_id"] == original_user_id

    done_events = harness.published_of("done")
    assert done_events[0]["metadata"]["assistant_message_id"] == messages[1]["id"]
    assert "user_message_id" not in done_events[0]["metadata"]
    # Regenerate must not re-run title generation.
    assert harness.title_calls == []


@pytest.mark.asyncio
async def test_engine_terminal_error_event_marks_turn_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    harness = RunTurnHarness(monkeypatch, tmp_path)
    harness.engine.events = [
        StreamEvent(
            type=StreamEventType.CONTENT,
            source="chat",
            content="partial",
            metadata={"call_id": "c1", "call_kind": "llm_final_response"},
        ),
        StreamEvent(
            type=StreamEventType.ERROR,
            source="chat",
            content="The model exhausted its output budget.",
            metadata={
                "turn_terminal": True,
                "status": "failed",
                "error_code": "reasoning_budget_exhausted",
                "retryable": True,
            },
        ),
        # The engine still closes its stream with a completed DONE; the
        # executor must let the terminal error event win the outcome.
        StreamEvent(
            type=StreamEventType.DONE,
            source="chat",
            metadata={"status": "completed"},
        ),
    ]

    execution = await harness.run(_payload())

    row = await harness.turn_row(execution)
    assert row["status"] == "failed"
    assert row["error"] == "The model exhausted its output budget."
    assert row["failure_code"] == "reasoning_budget_exhausted"
    assert row["retryable"] is True

    done_events = harness.published_of("done")
    assert len(done_events) == 1
    done = done_events[0]
    assert done["metadata"]["status"] == "failed"
    assert done["metadata"]["error_code"] == "reasoning_budget_exhausted"
    assert done["metadata"]["retryable"] is True
    assert done["metadata"]["assistant_message_id"]

    # A failed turn never generates a session title.
    assert harness.title_calls == []


class ProviderError(RuntimeError):
    def __init__(self, message: str, error_code: str, retryable: bool) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_code", "retryable"),
    [("rate_limited", True), ("content_policy_violation", False)],
)
async def test_engine_exception_preserves_provider_error_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path, error_code: str, retryable: bool
) -> None:
    harness = RunTurnHarness(monkeypatch, tmp_path)
    harness.engine.error = ProviderError(
        "provider rejected the request", error_code=error_code, retryable=retryable
    )

    execution = await harness.run(_payload())

    error_events = harness.published_of("error")
    done_events = harness.published_of("done")
    assert len(error_events) == 1
    assert len(done_events) == 1
    assert error_events[0]["metadata"]["turn_terminal"] is True
    assert error_events[0]["metadata"]["status"] == "failed"
    assert done_events[0]["metadata"]["status"] == "failed"
    assert done_events[0]["metadata"]["error_code"] == error_code
    assert done_events[0]["metadata"]["retryable"] is retryable

    row = await harness.turn_row(execution)
    assert row["status"] == "failed"
    assert row["error"] == "provider rejected the request"
    assert row["failure_code"] == error_code
    assert row["retryable"] is retryable

    # The user row is durable but no assistant row is written for a turn
    # that failed before any answer could be persisted.
    messages = await harness.messages(execution)
    assert [m["role"] for m in messages] == ["user"]


@pytest.mark.asyncio
async def test_engine_exception_defaults_to_internal_error_retryable(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    harness = RunTurnHarness(monkeypatch, tmp_path)
    harness.engine.events = [
        StreamEvent(
            type=StreamEventType.CONTENT,
            source="chat",
            content="half an answer",
            metadata={"call_id": "c1", "call_kind": "llm_final_response"},
        ),
    ]
    harness.engine.error = RuntimeError("boom")

    execution = await harness.run(_payload())

    error_events = harness.published_of("error")
    done_events = harness.published_of("done")
    assert [e["type"] for e in harness.published] == ["content", "error", "done"]
    assert error_events[0]["content"] == "boom"
    assert error_events[0]["metadata"]["error_code"] == "internal_error"
    assert error_events[0]["metadata"]["retryable"] is True
    assert done_events[0]["metadata"]["status"] == "failed"
    assert done_events[0]["metadata"]["error_code"] == "internal_error"

    row = await harness.turn_row(execution)
    assert row["status"] == "failed"
    assert row["error"] == "boom"
    assert row["failure_code"] == "internal_error"
    assert row["retryable"] is True

    messages = await harness.messages(execution)
    assert [m["role"] for m in messages] == ["user"]


@pytest.mark.asyncio
async def test_failure_after_done_visible_marks_turn_failed_without_new_terminal_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    harness = RunTurnHarness(monkeypatch, tmp_path)
    harness.engine.events = [
        StreamEvent(
            type=StreamEventType.CONTENT,
            source="chat",
            content="4",
            metadata={"call_id": "c1", "call_kind": "llm_final_response"},
        ),
        StreamEvent(
            type=StreamEventType.DONE,
            source="chat",
            metadata={"status": "completed"},
        ),
    ]

    # Once DONE became visible to the client, a durable-log write failure in
    # the remaining post-stream flush must downgrade the turn to failed
    # WITHOUT publishing a second terminal event pair.
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
            raise OSError("durable log write failed after DONE")
        return await real_flush(execution)

    monkeypatch.setattr(harness.runtime, "_publish_live_event", armed_publish)
    monkeypatch.setattr(harness.runtime, "_flush_buffered_events", armed_flush)

    execution = await harness.run(_payload())

    # Exactly one terminal event pair reached the client: the original DONE.
    # No ERROR may follow it, and no second DONE may be published.
    assert [p["type"] for p in harness.published].count("done") == 1
    assert not harness.published_of("error")

    # The terminal transition already settled the row as completed before
    # DONE went out; a post-DONE persistence failure cannot unsettle a
    # settled row (the CAS only accepts a running/waiting_input turn).
    row = await harness.turn_row(execution)
    assert row["status"] == "completed"
    assert row["error"] == ""

    # The assistant row itself was persisted before the flush failure.
    messages = await harness.messages(execution)
    assert [m["role"] for m in messages] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_user_message_persistence_failure_fails_turn_before_engine_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    harness = RunTurnHarness(monkeypatch, tmp_path)
    execution = await harness.new_execution(_payload())

    real_add = harness.store.add_message

    async def flaky_add(session_id, role, content, **kwargs):
        if role == "user":
            raise RuntimeError("disk full")
        return await real_add(session_id, role, content, **kwargs)

    monkeypatch.setattr(harness.store, "add_message", flaky_add)

    await harness.runtime._run_turn(execution)

    assert harness.engine.contexts == []
    assert [p["type"] for p in harness.published] == ["error", "done"]
    assert harness.published_of("done")[0]["metadata"]["status"] == "failed"

    row = await harness.turn_row(execution)
    assert row["status"] == "failed"
    assert row["error"] == "disk full"
    assert row["failure_code"] == "internal_error"
    assert row["retryable"] is True

    messages = await harness.messages(execution)
    assert messages == []
    assert execution.turn_id not in harness.runtime._reply_queues


@pytest.mark.asyncio
async def test_assistant_message_persistence_failure_fails_turn_after_stream(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    harness = RunTurnHarness(monkeypatch, tmp_path)
    harness.engine.events = [
        StreamEvent(
            type=StreamEventType.CONTENT,
            source="chat",
            content="4",
            metadata={"call_id": "c1", "call_kind": "llm_final_response"},
        ),
        StreamEvent(
            type=StreamEventType.DONE,
            source="chat",
            metadata={"status": "completed"},
        ),
    ]
    execution = await harness.new_execution(_payload())

    real_add = harness.store.add_message

    async def flaky_add(session_id, role, content, **kwargs):
        if role == "assistant":
            raise RuntimeError("assistant row write failed")
        return await real_add(session_id, role, content, **kwargs)

    monkeypatch.setattr(harness.store, "add_message", flaky_add)

    await harness.runtime._run_turn(execution)

    assert len(harness.engine.contexts) == 1
    assert [p["type"] for p in harness.published] == ["content", "error", "done"]
    done = harness.published_of("done")[0]
    assert done["metadata"]["status"] == "failed"
    assert done["metadata"]["error_code"] == "internal_error"

    row = await harness.turn_row(execution)
    assert row["status"] == "failed"
    assert row["error"] == "assistant row write failed"

    messages = await harness.messages(execution)
    assert [m["role"] for m in messages] == ["user"]


@pytest.mark.asyncio
async def test_terminal_transition_rejection_aborts_turn_without_terminal_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Losing the fencing race at the terminal transition aborts the turn.

    The lease holder can no longer prove ownership, so nothing terminal is
    published or written: the CancelledError propagates unwrapped and leader
    recovery owns the shared stream from here.
    """
    harness = RunTurnHarness(monkeypatch, tmp_path)
    harness.engine.events = [
        StreamEvent(
            type=StreamEventType.CONTENT,
            source="chat",
            content="4",
            metadata={"call_id": "c1", "call_kind": "llm_final_response"},
        ),
        StreamEvent(
            type=StreamEventType.DONE,
            source="chat",
            metadata={"status": "completed"},
        ),
    ]
    execution = await harness.new_execution(_payload())

    async def rejected_transition(_execution, _status, _error="", **_kwargs) -> bool:
        return False

    monkeypatch.setattr(harness.runtime, "_transition_execution", rejected_transition)

    with pytest.raises(asyncio.CancelledError):
        await harness.runtime._run_turn(execution)

    assert execution.lease_lost is True
    assert harness.published_of("error") == []
    assert harness.published_of("done") == []
    # The answer streamed to the client stays durable, but the turn row is
    # left for the lease owner / recovery path to settle.
    messages = await harness.messages(execution)
    assert [m["role"] for m in messages] == ["user", "assistant"]
    row = await harness.turn_row(execution)
    assert row["status"] == "running"
    assert execution.turn_id not in harness.runtime._reply_queues
