"""Unit tests for the thin ``tools.question.exam_mimic`` entrypoint.

The orchestration moved to ``deeptutor.agents.question.coordinator``; these
tests pin the parameter forwarding, the backward-compatible export surface,
and the result-dict contract with the coordinator (all with a mocked
coordinator, fully offline).
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest

import deeptutor.agents.question as agents_question
from deeptutor.services.llm.config import LLMConfig
from deeptutor.tools.question import exam_mimic

LEGACY_PARAM_ORDER = [
    "pdf_path",
    "paper_dir",
    "kb_name",
    "output_dir",
    "max_questions",
    "ws_callback",
]

_SUMMARY_SUCCESS = {
    "success": True,
    "template_count": 3,
    "results": [
        {"success": True, "qa_pair": {"question": "Q1", "answer": "A1"}},
        {"success": False, "qa_pair": {}, "error": "generation failed"},
        {"success": True, "qa_pair": {"question": "Q2", "answer": "A2"}},
    ],
}


class _FakeCoordinator:
    """Records constructor/forwarding calls; offline stand-in for the coordinator."""

    last_instance: "_FakeCoordinator | None" = None

    def __init__(self, **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        self.forwarded_callback = None
        self.forwarded_calls: list[tuple[str, dict[str, Any]]] = []
        self.generate_calls: list[dict[str, Any]] = []
        self.summary: dict[str, Any] = dict(_SUMMARY_SUCCESS)
        _FakeCoordinator.last_instance = self

    def set_ws_callback(self, callback: Any) -> None:
        self.forwarded_callback = callback

    async def generate_from_exam(self, **kwargs: Any) -> dict[str, Any]:
        self.generate_calls.append(kwargs)
        return dict(self.summary)

    async def invoke_forwarded(self, payload: dict[str, Any]) -> None:
        assert self.forwarded_callback is not None
        await self.forwarded_callback(payload)


@pytest.fixture()
def fake_coordinator(monkeypatch: pytest.MonkeyPatch) -> type[_FakeCoordinator]:
    monkeypatch.setattr(exam_mimic, "AgentCoordinator", _FakeCoordinator)
    monkeypatch.setattr(
        exam_mimic,
        "get_llm_config",
        lambda: LLMConfig(
            model="test-model",
            api_key="test-key",
            base_url="https://llm.example.invalid",
            api_version="2024-02-01",
        ),
    )
    _FakeCoordinator.last_instance = None
    return _FakeCoordinator


def test_rejects_missing_inputs_without_building_coordinator(
    fake_coordinator: type[_FakeCoordinator],
) -> None:
    result = asyncio.run(exam_mimic.mimic_exam_questions())

    assert result["success"] is False
    assert "Either pdf_path or paper_dir" in result["error"]
    assert _FakeCoordinator.last_instance is None


def test_rejects_conflicting_inputs_without_building_coordinator(
    fake_coordinator: type[_FakeCoordinator],
) -> None:
    result = asyncio.run(
        exam_mimic.mimic_exam_questions(pdf_path="a.pdf", paper_dir="parsed/")
    )

    assert result["success"] is False
    assert "cannot be used together" in result["error"]
    assert _FakeCoordinator.last_instance is None


def test_upload_mode_forwards_parameters_and_maps_result(
    fake_coordinator: type[_FakeCoordinator],
) -> None:
    result = asyncio.run(
        exam_mimic.mimic_exam_questions(
            pdf_path="paper.pdf",
            kb_name="kb1",
            output_dir="out",
            max_questions=5,
        )
    )

    coordinator = _FakeCoordinator.last_instance
    assert coordinator is not None
    assert coordinator.init_kwargs == {
        "api_key": "test-key",
        "base_url": "https://llm.example.invalid",
        "api_version": "2024-02-01",
        "kb_name": "kb1",
        "output_dir": "out",
    }
    assert coordinator.generate_calls == [
        {
            "exam_paper_path": "paper.pdf",
            "max_questions": 5,
            "paper_mode": "upload",
        }
    ]
    assert result["success"] is True
    assert result["summary"] == _SUMMARY_SUCCESS
    assert result["generated_questions"] == [
        {"question": "Q1", "answer": "A1"},
        {},
        {"question": "Q2", "answer": "A2"},
    ]
    assert result["failed_questions"] == [
        {"success": False, "qa_pair": {}, "error": "generation failed"}
    ]
    assert result["total_reference_questions"] == 3


def test_parsed_mode_routes_paper_dir(fake_coordinator: type[_FakeCoordinator]) -> None:
    asyncio.run(exam_mimic.mimic_exam_questions(paper_dir="parsed/"))

    coordinator = _FakeCoordinator.last_instance
    assert coordinator is not None
    assert coordinator.generate_calls == [
        {
            "exam_paper_path": "parsed/",
            "max_questions": 10,
            "paper_mode": "parsed",
        }
    ]


def test_default_max_questions_is_ten(fake_coordinator: type[_FakeCoordinator]) -> None:
    asyncio.run(exam_mimic.mimic_exam_questions(pdf_path="paper.pdf"))

    coordinator = _FakeCoordinator.last_instance
    assert coordinator is not None
    assert coordinator.generate_calls[0]["max_questions"] == 10


def test_no_ws_callback_leaves_coordinator_unset(
    fake_coordinator: type[_FakeCoordinator],
) -> None:
    asyncio.run(exam_mimic.mimic_exam_questions(pdf_path="paper.pdf"))

    coordinator = _FakeCoordinator.last_instance
    assert coordinator is not None
    assert coordinator.forwarded_callback is None


def test_ws_callback_forwards_event_type_and_payload(
    fake_coordinator: type[_FakeCoordinator],
) -> None:
    received: list[tuple[str, dict[str, Any]]] = []

    async def ws_callback(event_type: str, data: dict[str, Any]) -> None:
        received.append((event_type, data))

    asyncio.run(
        exam_mimic.mimic_exam_questions(pdf_path="paper.pdf", ws_callback=ws_callback)
    )

    coordinator = _FakeCoordinator.last_instance
    assert coordinator is not None
    asyncio.run(
        coordinator.invoke_forwarded({"type": "status", "stage": "parsing", "n": 1})
    )
    asyncio.run(coordinator.invoke_forwarded({"stage": "done"}))

    assert received == [
        ("status", {"type": "status", "stage": "parsing", "n": 1}),
        ("progress", {"stage": "done"}),
    ]


def test_failed_summary_propagates_as_failure(
    fake_coordinator: type[_FakeCoordinator],
) -> None:
    _FakeCoordinator.last_instance = None
    original_init = _FakeCoordinator.__init__

    def _failing_init(self: _FakeCoordinator, **kwargs: Any) -> None:
        original_init(self, **kwargs)
        self.summary = {"success": False, "error": "boom", "template_count": 0, "results": []}

    _FakeCoordinator.__init__ = _failing_init  # type: ignore[method-assign]
    try:
        result = asyncio.run(exam_mimic.mimic_exam_questions(pdf_path="paper.pdf"))
    finally:
        _FakeCoordinator.__init__ = original_init  # type: ignore[method-assign]

    assert result["success"] is False
    assert result["summary"]["error"] == "boom"
    assert result["generated_questions"] == []
    assert result["failed_questions"] == []
    assert result["total_reference_questions"] == 0


def test_entry_surface_stays_compatible_for_legacy_callers() -> None:
    signature = inspect.signature(exam_mimic.mimic_exam_questions)

    assert inspect.iscoroutinefunction(exam_mimic.mimic_exam_questions)
    assert list(signature.parameters) == LEGACY_PARAM_ORDER
    assert all(
        param.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        for param in signature.parameters.values()
    )

    assert exam_mimic.WsCallback is not None
    assert exam_mimic.AgentCoordinator is agents_question.AgentCoordinator

    generate = inspect.signature(agents_question.AgentCoordinator.generate_from_exam)
    assert set(generate.parameters) == {
        "self",
        "exam_paper_path",
        "max_questions",
        "paper_mode",
    }
    assert inspect.iscoroutinefunction(agents_question.AgentCoordinator.generate_from_exam)
    assert callable(agents_question.AgentCoordinator.set_ws_callback)
