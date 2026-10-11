"""Unit tests for the legacy ``AgentCoordinator`` facade.

``coordinator.py`` is a compatibility adapter that delegates all real work to
``QuestionPipeline``. These tests cover its orchestration decisions and
degradation branches with a fake pipeline and a fake paper parser — no
network, no LLM calls, and a stubbed path service.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from deeptutor.agents.question import coordinator
from deeptutor.core.stream import StreamEvent, StreamEventType

# ---------------------------------------------------------------------------
# Fake collaborators
# ---------------------------------------------------------------------------


class _FakePathService:
    """Minimal stand-in so tests never touch the real question directory."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def get_question_dir(self) -> Path:
        return self._root / "questions"


def _install_stubs(
    monkeypatch,
    tmp_path: Path,
    *,
    response_language: str = "zh",
) -> None:
    """Keep every external lookup local and deterministic."""
    monkeypatch.setattr(
        coordinator,
        "get_path_service",
        lambda: _FakePathService(tmp_path),
    )
    monkeypatch.setattr(
        coordinator,
        "get_response_language",
        lambda default="en": response_language,
    )


def _install_fake_pipeline(
    monkeypatch, *, result: dict[str, Any] | None = None, run_exc: Exception | None = None
):
    """Replace ``QuestionPipeline`` in the coordinator namespace.

    Returns the list of created fake pipelines; each records its ``__init__``
    arguments and its ``run`` keyword arguments.
    """
    created: list[_FakePipeline] = []

    class _FakePipeline:
        def __init__(
            self,
            *,
            language: str = "en",
            kb_name: str | None = None,
            enabled_tools: list[str] | None = None,
        ) -> None:
            self.language = language
            self.kb_name = kb_name
            self.enabled_tools = list(enabled_tools or [])
            self.run_calls: list[dict[str, Any]] = []
            self.events_to_emit: tuple[StreamEvent, ...] = ()
            created.append(self)

        async def run(self, **kwargs: Any) -> dict[str, Any]:
            self.run_calls.append(kwargs)
            if run_exc is not None:
                raise run_exc
            bus = kwargs["stream"]
            for event in self.events_to_emit:
                await bus.emit(event)
            return dict(result or {})

    monkeypatch.setattr(coordinator, "QuestionPipeline", _FakePipeline)
    return created


def _install_fake_parser(
    monkeypatch,
    *,
    templates: list[Any] | None = None,
    trace: dict[str, str] | None = None,
    exc: Exception | None = None,
) -> list[dict[str, Any]]:
    """Replace ``parse_exam_paper_to_templates`` in the coordinator namespace."""
    calls: list[dict[str, Any]] = []

    async def _fake_parse(
        paper_path: str | Path,
        *,
        max_questions: int,
        paper_mode: str,
        output_dir: str | Path,
    ) -> tuple[list[Any], dict[str, str]]:
        calls.append(
            {
                "paper_path": paper_path,
                "max_questions": max_questions,
                "paper_mode": paper_mode,
                "output_dir": output_dir,
            }
        )
        if exc is not None:
            raise exc
        return list(templates or []), dict(trace or {})

    monkeypatch.setattr(coordinator, "parse_exam_paper_to_templates", _fake_parse)
    return calls


class _Recorder:
    """ws_callback double: accepts sync or async use, records every payload."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def as_sync(self):
        def _cb(payload: dict[str, Any]) -> None:
            self.payloads.append(payload)

        return _cb

    def as_async(self):
        async def _cb(payload: dict[str, Any]) -> None:
            self.payloads.append(payload)

        return _cb


# ---------------------------------------------------------------------------
# Construction and configuration
# ---------------------------------------------------------------------------


def test_init_defaults_strip_empty_kb_and_default_idea_rag(tmp_path, monkeypatch) -> None:
    _install_stubs(monkeypatch, tmp_path)
    coord = coordinator.AgentCoordinator(kb_name="   ", enable_idea_rag=None)

    assert coord.kb_name is None
    assert coord.enable_idea_rag is True
    assert coord.language == "zh"
    assert coord.enabled_tools == []
    assert coord._ws_callback is None


def test_init_keeps_explicit_settings(tmp_path, monkeypatch) -> None:
    _install_stubs(monkeypatch, tmp_path)
    tools = ["rag"]
    coord = coordinator.AgentCoordinator(
        kb_name=" course-kb ",
        language="fr",
        enabled_tools=tools,
        enable_idea_rag=0,
        api_key="k",
        base_url="http://localhost",
    )

    assert coord.kb_name == "course-kb"
    assert coord.language == "fr"
    assert coord.enable_idea_rag is False
    assert coord.enabled_tools == ["rag"]
    # The caller's list is copied, later mutation must not leak in.
    tools.append("web_fetch")
    assert coord.enabled_tools == ["rag"]


def test_active_kb_name_gated_by_idea_rag(tmp_path, monkeypatch) -> None:
    _install_stubs(monkeypatch, tmp_path)
    coord = coordinator.AgentCoordinator(kb_name="kb", enable_idea_rag=False)
    assert coord._active_kb_name() is None

    coord_on = coordinator.AgentCoordinator(kb_name="kb")
    assert coord_on._active_kb_name() == "kb"


def test_output_dir_and_session_id_fall_back_to_path_service(tmp_path, monkeypatch) -> None:
    _install_stubs(monkeypatch, tmp_path)
    coord = coordinator.AgentCoordinator()
    assert coord._session_id() == "legacy-question"
    assert coord._resolve_output_dir() == tmp_path / "questions" / "mimic_papers"

    named = coordinator.AgentCoordinator(output_dir=str(tmp_path / "paper-run"))
    assert named._session_id() == "paper-run"
    assert named._resolve_output_dir() == tmp_path / "paper-run"


def test_set_ws_callback_round_trip(tmp_path, monkeypatch) -> None:
    _install_stubs(monkeypatch, tmp_path)
    coord = coordinator.AgentCoordinator()
    recorder = _Recorder()

    coord.set_ws_callback(recorder.as_sync())
    assert coord._ws_callback is not None

    coord.set_ws_callback(None)
    assert coord._ws_callback is None


# ---------------------------------------------------------------------------
# ``_legacy_summary`` result merging
# ---------------------------------------------------------------------------


def test_legacy_summary_empty_result_marks_failure() -> None:
    summary = coordinator.AgentCoordinator._legacy_summary({})

    assert summary["success"] is False
    assert summary["results"] == []
    assert summary["requested"] == 0
    assert summary["completed"] == 0
    assert summary["failed"] == 0
    assert summary["mode"] == "custom"
    assert summary["response"] == ""


def test_legacy_summary_preserves_pipeline_fields() -> None:
    result = {
        "summary": {"completed": 2, "failed": 1, "success": True, "results": [{"id": 1}]},
        "response": "final text",
        "mode": "mimic",
        "metadata": {"turn": "t1"},
    }
    summary = coordinator.AgentCoordinator._legacy_summary(result)

    assert summary["completed"] == 2
    assert summary["failed"] == 1
    assert summary["success"] is True
    assert summary["requested"] == 0  # setdefault: kept at 0 when absent
    assert summary["response"] == "final text"
    assert summary["mode"] == "mimic"
    assert summary["metadata"] == {"turn": "t1"}
    # Items without a ``success`` key get it inferred from ``metadata.error``.
    assert summary["results"] == [{"id": 1, "success": True}]


def test_legacy_summary_infers_item_success_from_metadata_error() -> None:
    summary = coordinator.AgentCoordinator._legacy_summary(
        {
            "summary": {
                "completed": 2,
                "results": [
                    {"question": "ok", "metadata": {}},
                    {"question": "broken", "metadata": {"error": "boom"}},
                    {"question": "preset", "success": True, "metadata": {"error": "ignored"}},
                    "not-a-dict",
                ],
            }
        }
    )

    results = summary["results"]
    assert results[0]["success"] is True
    assert results[1]["success"] is False
    # Pre-set ``success`` is never overwritten.
    assert results[2]["success"] is True
    assert "success" not in results[3]


# ---------------------------------------------------------------------------
# Event forwarding
# ---------------------------------------------------------------------------


def test_event_payload_result_event_gains_content_from_metadata() -> None:
    result_event = StreamEvent(
        type=StreamEventType.RESULT,
        content="",
        metadata={"response": "final answer"},
    )
    payload = coordinator.AgentCoordinator._event_payload(result_event)
    # ``to_dict`` always carries the event's own ``content``, so the
    # ``setdefault`` fallback never replaces it — the event content wins.
    assert payload["content"] == ""

    plain = StreamEvent(type=StreamEventType.CONTENT, content="chunk")
    payload = coordinator.AgentCoordinator._event_payload(plain)
    assert payload["content"] == "chunk"


def test_generate_from_topic_wires_pipeline_with_config(tmp_path, monkeypatch) -> None:
    _install_stubs(monkeypatch, tmp_path)
    pipelines = _install_fake_pipeline(
        monkeypatch,
        result={
            "summary": {"completed": 1, "results": [{"question": "q1"}]},
            "response": "done",
        },
    )

    coord = coordinator.AgentCoordinator(kb_name="kb", enabled_tools=["rag"])
    summary = asyncio.run(coord.generate_from_topic(user_topic="photosynthesis"))

    assert len(pipelines) == 1
    pipeline = pipelines[0]
    assert pipeline.language == "zh"  # stubbed settings default
    assert pipeline.kb_name == "kb"
    assert pipeline.enabled_tools == ["rag"]
    assert len(pipeline.run_calls) == 1
    call = pipeline.run_calls[0]
    assert call["user_message"] == "photosynthesis"
    assert call["num_questions"] == 1
    assert call["difficulty"] == ""
    assert call["question_types"] == []
    assert call["per_type_counts"] == {}
    assert call["stream"] is not None

    assert summary["completed"] == 1
    assert summary["response"] == "done"


def test_generate_from_topic_emits_pipeline_events_to_callback(tmp_path, monkeypatch) -> None:
    _install_stubs(monkeypatch, tmp_path)
    recorder = _Recorder()
    created: list[Any] = []

    events = (
        StreamEvent(type=StreamEventType.STAGE_START, stage="planning", content="plan"),
        StreamEvent(
            type=StreamEventType.RESULT,
            content="",
            metadata={"response": "the answer"},
        ),
    )

    class _FakePipeline:
        def __init__(self, **kwargs: Any) -> None:
            created.append(self)

        async def run(self, **kwargs: Any) -> dict[str, Any]:
            bus = kwargs["stream"]
            for event in events:
                await bus.emit(event)
            return {"summary": {"completed": 1}, "response": "the answer"}

    monkeypatch.setattr(coordinator, "QuestionPipeline", _FakePipeline)

    coord = coordinator.AgentCoordinator()
    coord.set_ws_callback(recorder.as_async())
    summary = asyncio.run(coord.generate_from_topic(user_topic="topic"))

    assert summary["completed"] == 1
    types = [payload["type"] for payload in recorder.payloads]
    assert "stage_start" in types
    assert "result" in types
    result_payload = next(p for p in recorder.payloads if p["type"] == "result")
    assert result_payload["content"] == ""  # event's own content is preserved
    assert result_payload["metadata"]["response"] == "the answer"


def test_generate_from_topic_supports_sync_callback(tmp_path, monkeypatch) -> None:
    _install_stubs(monkeypatch, tmp_path)
    recorder = _Recorder()

    class _FakePipeline:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def run(self, **kwargs: Any) -> dict[str, Any]:
            await kwargs["stream"].emit(StreamEvent(type=StreamEventType.CONTENT, content="hello"))
            return {"summary": {"completed": 1}}

    monkeypatch.setattr(coordinator, "QuestionPipeline", _FakePipeline)

    coord = coordinator.AgentCoordinator()
    coord.set_ws_callback(recorder.as_sync())
    summary = asyncio.run(coord.generate_from_topic(user_topic="topic"))

    assert summary["completed"] == 1
    assert [p["content"] for p in recorder.payloads] == ["hello"]


def test_generate_from_topic_without_callback_still_returns_summary(tmp_path, monkeypatch) -> None:
    _install_stubs(monkeypatch, tmp_path)

    class _FakePipeline:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def run(self, **kwargs: Any) -> dict[str, Any]:
            return {"summary": {"completed": 1}, "response": "ok"}

    monkeypatch.setattr(coordinator, "QuestionPipeline", _FakePipeline)

    coord = coordinator.AgentCoordinator()
    summary = asyncio.run(coord.generate_from_topic(user_topic="topic"))
    assert summary["response"] == "ok"


def test_generate_from_topic_normalizes_num_questions(tmp_path, monkeypatch) -> None:
    _install_stubs(monkeypatch, tmp_path)
    pipelines = _install_fake_pipeline(monkeypatch, result={})

    coord = coordinator.AgentCoordinator()
    asyncio.run(coord.generate_from_topic(user_topic="t", num_questions=0))
    asyncio.run(coord.generate_from_topic(user_topic="t", num_questions=None))
    asyncio.run(coord.generate_from_topic(user_topic="t", num_questions=5))

    assert [c.run_calls[0]["num_questions"] for c in pipelines] == [1, 1, 5]


def test_forwarder_failure_does_not_break_the_run(tmp_path, monkeypatch) -> None:
    _install_stubs(monkeypatch, tmp_path)

    class _FakePipeline:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def run(self, **kwargs: Any) -> dict[str, Any]:
            await kwargs["stream"].emit(
                StreamEvent(type=StreamEventType.CONTENT, content="boom-path")
            )
            return {"summary": {"completed": 1}}

    monkeypatch.setattr(coordinator, "QuestionPipeline", _FakePipeline)

    def _failing_callback(payload: dict[str, Any]) -> None:
        raise RuntimeError("callback socket closed")

    coord = coordinator.AgentCoordinator()
    coord.set_ws_callback(_failing_callback)
    summary = asyncio.run(coord.generate_from_topic(user_topic="topic"))
    assert summary["completed"] == 1


# ---------------------------------------------------------------------------
# ``generate_from_exam``
# ---------------------------------------------------------------------------


def test_generate_from_exam_requires_paper_path(tmp_path, monkeypatch) -> None:
    _install_stubs(monkeypatch, tmp_path)
    parser_calls = _install_fake_parser(monkeypatch)
    pipelines = _install_fake_pipeline(monkeypatch)

    coord = coordinator.AgentCoordinator()
    for bad_path in ("", "   "):
        result = asyncio.run(coord.generate_from_exam(exam_paper_path=bad_path))
        assert result == {"success": False, "error": "exam_paper_path is required."}

    assert parser_calls == []
    assert pipelines == []


def test_generate_from_exam_no_templates_degrades_without_pipeline(tmp_path, monkeypatch) -> None:
    _install_stubs(monkeypatch, tmp_path)
    parser_calls = _install_fake_parser(monkeypatch, templates=[], trace={"source": "upload"})
    pipelines = _install_fake_pipeline(monkeypatch)
    recorder = _Recorder()

    coord = coordinator.AgentCoordinator(output_dir=str(tmp_path / "run1"))
    coord.set_ws_callback(recorder.as_sync())
    result = asyncio.run(coord.generate_from_exam(exam_paper_path="paper.pdf", max_questions=3))

    assert result["success"] is False
    assert result["template_count"] == 0
    assert result["results"] == []
    assert result["trace"] == {"source": "upload"}
    assert parser_calls == [
        {
            "paper_path": "paper.pdf",
            "max_questions": 3,
            "paper_mode": "upload",
            "output_dir": tmp_path / "run1",
        }
    ]
    assert pipelines == []
    # The parsing status event was still pushed to the UI callback.
    assert recorder.payloads == [
        {
            "type": "status",
            "stage": "parsing",
            "content": "Extracting question templates from exam paper...",
        }
    ]


def test_generate_from_exam_runs_pipeline_with_templates(tmp_path, monkeypatch) -> None:
    _install_stubs(monkeypatch, tmp_path)
    templates = [object(), object()]
    _install_fake_parser(monkeypatch, templates=templates, trace={"mode": "dir"})
    pipelines = _install_fake_pipeline(
        monkeypatch,
        result={"summary": {"completed": 2, "results": [{}, {}]}, "response": "quiz"},
    )

    coord = coordinator.AgentCoordinator(kb_name="kb")
    result = asyncio.run(
        coord.generate_from_exam(exam_paper_path="paper.pdf", max_questions=2, paper_mode="dir")
    )

    pipeline = pipelines[0]
    call = pipeline.run_calls[0]
    assert call["num_questions"] == 2
    assert call["templates_override"] == templates
    assert call["user_message"] == "Mimic this exam paper"

    assert result["completed"] == 2
    assert result["response"] == "quiz"
    assert result["trace"] == {"mode": "dir"}


def test_generate_from_exam_parser_error_returns_failure(tmp_path, monkeypatch) -> None:
    _install_stubs(monkeypatch, tmp_path)
    _install_fake_parser(monkeypatch, exc=ValueError("unreadable pdf"))
    pipelines = _install_fake_pipeline(monkeypatch)

    coord = coordinator.AgentCoordinator()
    result = asyncio.run(coord.generate_from_exam(exam_paper_path="paper.pdf"))

    assert result["success"] is False
    assert result["error"] == "unreadable pdf"
    assert result["results"] == []
    assert pipelines == []


def test_generate_from_exam_pipeline_error_returns_failure(tmp_path, monkeypatch) -> None:
    _install_stubs(monkeypatch, tmp_path)
    _install_fake_parser(monkeypatch, templates=[object()])
    _install_fake_pipeline(monkeypatch, run_exc=RuntimeError("pipeline exploded"))

    coord = coordinator.AgentCoordinator()
    result = asyncio.run(coord.generate_from_exam(exam_paper_path="paper.pdf"))

    assert result["success"] is False
    assert result["error"] == "pipeline exploded"
    assert result["results"] == []
