"""Contract tests for the learning-domain turn adapter.

``LearningTurnAdapter`` is the mixin ``TurnRuntimeManager`` uses to bridge
the session turn runtime with mastery-path learning state: lease takeover,
card answer commit/grade/skip, and session-topic validation. These tests pin
that contract against stub collaborators, covering the success paths, the
missing-field guards, and the best-effort exception swallowing — without
touching a real learning store or LLM.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from deeptutor.capabilities.mastery import tools as mastery_tools
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.tool_protocol import ToolResult
from deeptutor.learning import service as learning_service_module
from deeptutor.learning import storage as learning_storage_module
from deeptutor.learning.models import MasteryPathLease
from deeptutor.learning.storage import PathLeaseConflictError
from deeptutor.services.session._turn_runtime_shared import _TurnExecution
from deeptutor.services.session.turns.learning_adapter import LearningTurnAdapter

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Host scaffolding: the adapter is a mixin over the turn runtime, so the
# tests provide the minimal host surface it expects (store, lock, executions,
# live-event publisher, cancel).
# ---------------------------------------------------------------------------


class _AdapterHost(LearningTurnAdapter):
    def __init__(self, store=None) -> None:
        self.store = store
        self._lock = asyncio.Lock()
        self._executions: dict[str, _TurnExecution] = {}
        self.published: list[StreamEvent] = []
        self.cancelled: list[str] = []

    def add_execution(self, execution: _TurnExecution) -> None:
        self._executions[execution.turn_id] = execution

    async def _publish_live_event(self, execution: _TurnExecution, event: StreamEvent) -> dict:
        self.published.append(event)
        return {}

    async def cancel_turn(self, turn_id: str) -> bool:
        self.cancelled.append(turn_id)
        return True


def _execution(turn_id: str = "turn-1", *, awaiting: bool = False) -> _TurnExecution:
    return _TurnExecution(
        turn_id=turn_id,
        session_id="session-1",
        capability="chat",
        payload={},
        awaiting_user_reply=awaiting,
    )


def _lease(
    path_id: str = "path-1",
    session_id: str = "session-old",
    turn_id: str = "turn-old",
) -> MasteryPathLease:
    return MasteryPathLease(path_id=path_id, session_id=session_id, turn_id=turn_id)


class _FakeSessionStore:
    """Minimal SessionStoreProtocol surface: only ``get_turn``."""

    def __init__(self, turns: dict[str, dict] | None = None) -> None:
        self.turns = dict(turns or {})

    async def get_turn(self, turn_id: str):
        return self.turns.get(turn_id)


class _FakeLearningStore:
    """Records LearningStore calls the adapter makes; no database."""

    def __init__(
        self,
        *,
        leases: dict[str, MasteryPathLease] | None = None,
        session_paths: dict[str, str] | None = None,
        acquire_error: Exception | None = None,
    ) -> None:
        self.leases = dict(leases or {})
        self.session_paths = dict(session_paths or {})
        self.acquire_error = acquire_error
        self.calls: list[tuple] = []

    def bind_session(self, path_id, session_id, *, owns_path=False):
        self.calls.append(("bind_session", path_id, session_id, owns_path))
        self.session_paths[session_id] = path_id

    def get_path_lease(self, path_id):
        self.calls.append(("get_path_lease", path_id))
        return self.leases.get(path_id)

    def acquire_path_lease(self, path_id, session_id, turn_id, *, bind_session=True):
        self.calls.append(("acquire_path_lease", path_id, session_id, turn_id))
        if self.acquire_error is not None:
            raise self.acquire_error
        lease = self.leases.get(path_id)
        if lease is not None and lease.turn_id != turn_id:
            raise PathLeaseConflictError(lease)
        self.leases[path_id] = MasteryPathLease(
            path_id=path_id, session_id=session_id, turn_id=turn_id
        )

    def release_path_lease(self, path_id, *, turn_id=None):
        self.calls.append(("release_path_lease", path_id, turn_id))
        self.leases.pop(path_id, None)

    def path_id_for_session(self, session_id):
        return self.session_paths.get(session_id, "")


class _FakeLearningService:
    def __init__(self, *, store=None, record_error: Exception | None = None) -> None:
        self._store = store
        self.record_error = record_error
        self.recorded: list[dict] = []

    @property
    def store(self):
        return self._store

    def record_question_answer(
        self, path_id, answer, *, interaction_id="", session_id="", turn_id=""
    ):
        if self.record_error is not None:
            raise self.record_error
        self.recorded.append(
            {
                "path_id": path_id,
                "answer": answer,
                "interaction_id": interaction_id,
                "session_id": session_id,
                "turn_id": turn_id,
            }
        )
        return None


class _FakeServiceStore:
    def __init__(self, active=None) -> None:
        self.active = active
        self.queries: list[str] = []

    def get_active_interaction(self, path_id):
        self.queries.append(path_id)
        return self.active


def _patch_learning_store(monkeypatch, store: _FakeLearningStore) -> _FakeLearningStore:
    monkeypatch.setattr(learning_storage_module, "LearningStore", lambda: store)
    return store


# ---------------------------------------------------------------------------
# _release_superseded_lease
# ---------------------------------------------------------------------------


async def test_release_superseded_lease_releases_finished_turn(monkeypatch):
    store = _patch_learning_store(monkeypatch, _FakeLearningStore())
    host = _AdapterHost(store=_FakeSessionStore({"turn-old": {"status": "finished"}}))
    lease = _lease()

    await host._release_superseded_lease("path-1", lease)

    assert store.calls == [("release_path_lease", "path-1", "turn-old")]
    assert host.cancelled == []


async def test_release_superseded_lease_cancels_parked_turn(monkeypatch):
    store = _patch_learning_store(monkeypatch, _FakeLearningStore())
    host = _AdapterHost(store=_FakeSessionStore({"turn-old": {"status": "running"}}))
    host.add_execution(_execution("turn-old", awaiting=True))
    lease = _lease()

    await host._release_superseded_lease("path-1", lease)

    assert host.cancelled == ["turn-old"]
    assert store.calls == [("release_path_lease", "path-1", "turn-old")]


async def test_release_superseded_lease_keeps_lease_while_turn_generates(monkeypatch):
    store = _patch_learning_store(monkeypatch, _FakeLearningStore())
    host = _AdapterHost(store=_FakeSessionStore({"turn-old": {"status": "running"}}))
    host.add_execution(_execution("turn-old", awaiting=False))
    lease = _lease()

    await host._release_superseded_lease("path-1", lease)

    assert host.cancelled == []
    assert store.calls == []


# ---------------------------------------------------------------------------
# _commit_mastery_card_answer
# ---------------------------------------------------------------------------


async def test_commit_card_answer_records_learner_words(monkeypatch):
    service = _FakeLearningService()
    monkeypatch.setattr(learning_service_module, "LearningService", lambda: service)

    await host_commit(
        monkeypatch,
        path_id="path-1",
        session_id="s-1",
        turn_id="t-1",
        question_id="q-1",
        answer="Paris",
    )

    assert service.recorded == [
        {
            "path_id": "path-1",
            "answer": "Paris",
            "interaction_id": "q-1",
            "session_id": "s-1",
            "turn_id": "t-1",
        }
    ]


async def test_commit_card_answer_swallows_storage_failure(monkeypatch, caplog):
    service = _FakeLearningService(record_error=RuntimeError("disk full"))
    monkeypatch.setattr(learning_service_module, "LearningService", lambda: service)

    # Best-effort by design: a storage hiccup must not sink the turn.
    await host_commit(
        monkeypatch,
        path_id="path-1",
        session_id="s-1",
        turn_id="t-1",
        question_id="q-1",
        answer="Paris",
    )

    assert service.recorded == []


async def host_commit(monkeypatch, *, path_id, session_id, turn_id, question_id, answer):
    host = _AdapterHost()
    await host._commit_mastery_card_answer(
        path_id=path_id,
        session_id=session_id,
        turn_id=turn_id,
        question_id=question_id,
        answer=answer,
    )
    return host


# ---------------------------------------------------------------------------
# _grade_submitted_card_answer
# ---------------------------------------------------------------------------


def _install_grade_tool(monkeypatch, result: ToolResult | None, error: Exception | None = None):
    calls: list[dict] = []

    class _FakeGradeTool:
        def __init__(self) -> None: ...

        async def execute(self, **kwargs):
            calls.append(kwargs)
            if error is not None:
                raise error
            return result

    monkeypatch.setattr(mastery_tools, "MasteryGradeTool", _FakeGradeTool)
    return calls


async def test_grade_missing_fields_skip_tool_and_events(monkeypatch):
    calls = _install_grade_tool(monkeypatch, ToolResult(content="unused"))
    host = _AdapterHost()
    execution = _execution()

    for path_id, answer in [
        ("", {"question_id": "q-1", "text": "C"}),
        ("path-1", {"question_id": "", "text": "C"}),
        ("path-1", {"question_id": "q-1", "text": ""}),
        ("path-1", {}),
        ("path-1", None),
    ]:
        assert (
            await host._grade_submitted_card_answer(execution, path_id=path_id, answer=answer)
            is None
        )

    assert calls == []
    assert host.published == []


async def test_grade_success_publishes_verdict_before_tutor(monkeypatch):
    payload = {"question_id": "q-1", "correct": True, "expected": "Paris"}
    calls = _install_grade_tool(
        monkeypatch,
        ToolResult(content="graded", metadata={"mastery_grade": payload}, success=True),
    )
    host = _AdapterHost()
    execution = _execution()

    returned = await host._grade_submitted_card_answer(
        execution, path_id="path-1", answer={"question_id": "q-1", "text": "Paris"}
    )

    assert returned == payload
    assert calls == [
        {
            "_mastery_path_id": "path-1",
            "_session_id": "session-1",
            "_turn_id": "turn-1",
            "question_id": "q-1",
            "answer": "Paris",
        }
    ]
    assert [event.type for event in host.published] == [
        StreamEventType.TOOL_RESULT,
        StreamEventType.PROGRESS,
    ]
    result_event, status_event = host.published
    assert result_event.source == "mastery"
    assert result_event.content == "graded"
    assert result_event.metadata["trace_kind"] == "tool_result"
    assert result_event.metadata["tool_metadata"] == {"mastery_grade": payload}
    assert result_event.metadata["call_id"] == "mastery-grade-turn-1-q-1"
    assert status_event.metadata["trace_kind"] == "call_status"
    assert status_event.metadata["call_state"] == "complete"
    assert status_event.metadata["call_id"] == result_event.metadata["call_id"]


async def test_grade_tool_failure_is_best_effort(monkeypatch):
    calls = _install_grade_tool(monkeypatch, None, error=RuntimeError("stale card"))
    host = _AdapterHost()

    returned = await host._grade_submitted_card_answer(
        _execution(), path_id="path-1", answer={"question_id": "q-1", "text": "C"}
    )

    assert returned is None
    assert len(calls) == 1
    assert host.published == []


async def test_grade_unsuccessful_result_yields_no_verdict(monkeypatch):
    _install_grade_tool(
        monkeypatch,
        ToolResult(content="no pending question", metadata={}, success=False),
    )
    host = _AdapterHost()

    returned = await host._grade_submitted_card_answer(
        _execution(), path_id="path-1", answer={"question_id": "q-1", "text": "C"}
    )

    assert returned is None
    assert host.published == []


async def test_grade_metadata_without_payload_yields_no_verdict(monkeypatch):
    _install_grade_tool(monkeypatch, ToolResult(content="graded", success=True))
    host = _AdapterHost()

    returned = await host._grade_submitted_card_answer(
        _execution(), path_id="path-1", answer={"question_id": "q-1", "text": "C"}
    )

    assert returned is None
    assert host.published == []


# ---------------------------------------------------------------------------
# _skip_card_question
# ---------------------------------------------------------------------------


def _install_skip_tool(monkeypatch, result: ToolResult | None, error: Exception | None = None):
    calls: list[dict] = []

    class _FakeSkipTool:
        def __init__(self) -> None: ...

        async def execute(self, **kwargs):
            calls.append(kwargs)
            if error is not None:
                raise error
            return result

    monkeypatch.setattr(mastery_tools, "MasterySkipQuestionTool", _FakeSkipTool)
    return calls


async def test_skip_missing_fields_never_touch_service(monkeypatch):
    calls = _install_skip_tool(monkeypatch, ToolResult(content="unused"))
    service = _FakeLearningService(store=_FakeServiceStore())
    monkeypatch.setattr(learning_service_module, "LearningService", lambda: service)
    host = _AdapterHost()

    for path_id, skip in [("", {"question_id": "q-1"}), ("path-1", {}), ("path-1", None)]:
        assert await host._skip_card_question(_execution(), path_id=path_id, skip=skip) is None

    assert service._store.queries == []
    assert calls == []
    assert host.published == []


async def test_skip_superseded_question_is_noop(monkeypatch):
    calls = _install_skip_tool(monkeypatch, ToolResult(content="unused"))
    service = _FakeLearningService(
        store=_FakeServiceStore(active=SimpleNamespace(interaction_id="q-other"))
    )
    monkeypatch.setattr(learning_service_module, "LearningService", lambda: service)
    host = _AdapterHost()

    returned = await host._skip_card_question(
        _execution(), path_id="path-1", skip={"question_id": "q-1"}
    )

    assert returned is None
    assert service._store.queries == ["path-1"]
    assert calls == []
    assert host.published == []


async def test_skip_active_question_publishes_scoped_payload(monkeypatch):
    payload = {"released": True}
    calls = _install_skip_tool(
        monkeypatch,
        ToolResult(content="skipped", metadata={"mastery_skip_question": payload}, success=True),
    )
    service = _FakeLearningService(
        store=_FakeServiceStore(active=SimpleNamespace(interaction_id="q-1"))
    )
    monkeypatch.setattr(learning_service_module, "LearningService", lambda: service)
    host = _AdapterHost()
    execution = _execution()

    returned = await host._skip_card_question(
        execution, path_id="path-1", skip={"question_id": "q-1"}
    )

    assert returned == {**payload, "question_id": "q-1"}
    assert calls == [
        {
            "_mastery_path_id": "path-1",
            "_session_id": "session-1",
            "_turn_id": "turn-1",
        }
    ]
    assert [event.type for event in host.published] == [
        StreamEventType.TOOL_RESULT,
        StreamEventType.PROGRESS,
    ]
    result_event, status_event = host.published
    assert result_event.metadata["tool_metadata"] == {
        "mastery_skip_question": {**payload, "question_id": "q-1"}
    }
    assert result_event.metadata["call_id"] == "mastery-skip-turn-1-q-1"
    assert status_event.metadata["call_state"] == "complete"


async def test_skip_service_failure_is_best_effort(monkeypatch):
    calls = _install_skip_tool(monkeypatch, ToolResult(content="unused"))

    class _BrokenService:
        def __init__(self) -> None:
            self._store = _FakeServiceStore(active=SimpleNamespace(interaction_id="q-1"))

        @property
        def store(self):
            raise RuntimeError("store gone")

    monkeypatch.setattr(learning_service_module, "LearningService", _BrokenService)
    host = _AdapterHost()

    returned = await host._skip_card_question(
        _execution(), path_id="path-1", skip={"question_id": "q-1"}
    )

    assert returned is None
    assert calls == []
    assert host.published == []


# ---------------------------------------------------------------------------
# _acquire_mastery_path_lease
# ---------------------------------------------------------------------------


async def test_acquire_lease_binds_and_acquires(monkeypatch):
    store = _patch_learning_store(monkeypatch, _FakeLearningStore())
    host = _AdapterHost(store=_FakeSessionStore())

    await host._acquire_mastery_path_lease(
        path_id="path-1", session_id="s-1", turn_id="t-1", owns_path=False
    )

    assert store.calls == [
        ("bind_session", "path-1", "s-1", False),
        ("get_path_lease", "path-1"),
        ("acquire_path_lease", "path-1", "s-1", "t-1"),
    ]


async def test_acquire_lease_takes_over_from_parked_turn(monkeypatch):
    old_lease = _lease()
    store = _patch_learning_store(monkeypatch, _FakeLearningStore(leases={"path-1": old_lease}))
    host = _AdapterHost(store=_FakeSessionStore({"turn-old": {"status": "running"}}))
    host.add_execution(_execution("turn-old", awaiting=True))

    await host._acquire_mastery_path_lease(
        path_id="path-1", session_id="s-1", turn_id="t-1", owns_path=False
    )

    assert host.cancelled == ["turn-old"]
    assert store.calls == [
        ("bind_session", "path-1", "s-1", False),
        ("get_path_lease", "path-1"),
        ("release_path_lease", "path-1", "turn-old"),
        ("acquire_path_lease", "path-1", "s-1", "t-1"),
    ]


async def test_acquire_lease_leaves_path_api_lease_alone(monkeypatch):
    api_lease = _lease(session_id="__path_api__", turn_id="turn-api")
    store = _patch_learning_store(monkeypatch, _FakeLearningStore(leases={"path-1": api_lease}))
    host = _AdapterHost(store=_FakeSessionStore())

    # A path-API lease is not a turn's lease: no takeover, no cancel — and the
    # store's conflict for a foreign turn still surfaces as mastery_path_busy.
    with pytest.raises(RuntimeError, match="mastery_path_busy"):
        await host._acquire_mastery_path_lease(
            path_id="path-1", session_id="s-1", turn_id="t-1", owns_path=False
        )

    assert host.cancelled == []
    assert ("release_path_lease", "path-1", "turn-api") not in store.calls


async def test_acquire_lease_conflict_raises_busy_runtime_error(monkeypatch):
    conflict = PathLeaseConflictError(_lease())
    store = _patch_learning_store(monkeypatch, _FakeLearningStore(acquire_error=conflict))
    host = _AdapterHost(store=_FakeSessionStore())

    with pytest.raises(RuntimeError, match="mastery_path_busy") as excinfo:
        await host._acquire_mastery_path_lease(
            path_id="path-1", session_id="s-1", turn_id="t-1", owns_path=False
        )

    assert "path-1" in str(excinfo.value)
    assert excinfo.value.__cause__ is conflict


# ---------------------------------------------------------------------------
# _validate_mastery_session_topic
# ---------------------------------------------------------------------------


async def test_validate_topic_rejects_foreign_topic_url(monkeypatch):
    _patch_learning_store(monkeypatch, _FakeLearningStore(session_paths={"s-1": "path-A"}))

    with pytest.raises(RuntimeError, match="mastery_session_topic_mismatch"):
        await LearningTurnAdapter._validate_mastery_session_topic(
            session_id="s-1", requested_path_id="path-B", remembered_path_id=""
        )


async def test_validate_topic_accepts_current_membership(monkeypatch):
    _patch_learning_store(monkeypatch, _FakeLearningStore(session_paths={"s-1": "path-A"}))

    await LearningTurnAdapter._validate_mastery_session_topic(
        session_id="s-1", requested_path_id="path-A", remembered_path_id="path-old"
    )


async def test_validate_topic_falls_back_to_remembered_path(monkeypatch):
    _patch_learning_store(monkeypatch, _FakeLearningStore())

    await LearningTurnAdapter._validate_mastery_session_topic(
        session_id="s-1", requested_path_id="path-old", remembered_path_id="path-old"
    )
    with pytest.raises(RuntimeError, match="mastery_session_topic_mismatch"):
        await LearningTurnAdapter._validate_mastery_session_topic(
            session_id="s-1", requested_path_id="path-B", remembered_path_id="path-old"
        )


async def test_validate_topic_new_session_may_start_anywhere(monkeypatch):
    _patch_learning_store(monkeypatch, _FakeLearningStore())

    await LearningTurnAdapter._validate_mastery_session_topic(
        session_id="s-new", requested_path_id="path-fresh", remembered_path_id=""
    )


# ---------------------------------------------------------------------------
# _is_awaiting_user_reply
# ---------------------------------------------------------------------------


async def test_awaiting_user_reply_reflects_execution_state():
    host = _AdapterHost()
    assert await host._is_awaiting_user_reply("turn-1") is False

    host.add_execution(_execution("turn-1", awaiting=True))
    assert await host._is_awaiting_user_reply("turn-1") is True

    host.add_execution(_execution("turn-1", awaiting=False))
    assert await host._is_awaiting_user_reply("turn-1") is False
