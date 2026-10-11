"""Fake-level tests for the ``DeepResearchCapability`` shim.

The capability is the orchestration entry users actually hit: request-config
validation, the outline-preview two-stage flow, and the single result
emission carrying ``research_config`` back to the frontend. The pipeline
itself is faked here — phase behaviour is covered in
``test_pipeline_orchestration.py`` and the host-level test modules.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

import deeptutor.agents.research.capability as capability_module
from deeptutor.agents.research.capability import DeepResearchCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.stream_bus import StreamBus

pytestmark = pytest.mark.asyncio


class _FakePipeline:
    """Records constructor kwargs and replays a canned run result."""

    instances: list["_FakePipeline"] = []
    canned_result: dict[str, Any] = {}

    def __init__(
        self,
        *,
        language: str,
        runtime_config: dict[str, Any],
        kb_name: str | None,
        enabled_tools: list[str],
    ) -> None:
        self.language = language
        self.runtime_config = runtime_config
        self.kb_name = kb_name
        self.enabled_tools = enabled_tools
        self.run_calls: list[dict[str, Any]] = []
        _FakePipeline.instances.append(self)

    async def run(
        self,
        *,
        context,
        topic,
        confirmed_outline,
        attachments,
        stream,
    ) -> dict[str, Any]:
        self.run_calls.append(
            {
                "topic": topic,
                "confirmed_outline": confirmed_outline,
                "attachments": attachments,
            }
        )
        return _FakePipeline.canned_result


def _install(monkeypatch: pytest.MonkeyPatch, result: dict[str, Any]) -> None:
    _FakePipeline.instances = []
    _FakePipeline.canned_result = result
    monkeypatch.setattr(capability_module, "ResearchPipeline", _FakePipeline)
    monkeypatch.setattr(capability_module, "load_config_with_main", lambda _name: {})


def _events_of_type(stream: StreamBus, type_value: str):
    return [event for event in stream._history if event.type.value == type_value]


def _capability() -> DeepResearchCapability:
    return DeepResearchCapability()


async def test_first_call_emits_outline_preview_with_research_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        {
            "outline_preview": True,
            "topic": "refined",
            "sub_topics": [{"title": "A", "overview": ""}],
            "response": "",
            "output_dir": "",
        },
    )
    capability = _capability()
    context = UnifiedContext(
        session_id="s1",
        user_message="original question",
        language="zh",
        enabled_tools=["web_search"],
        config_overrides={"mode": "report", "depth": "quick"},
    )
    stream = StreamBus()

    await capability.run(context, stream)

    assert len(_FakePipeline.instances) == 1
    fake = _FakePipeline.instances[0]
    assert fake.language == "zh"
    assert fake.kb_name is None
    assert fake.enabled_tools == ["web_search"]
    assert fake.run_calls[0]["topic"] == "original question"
    assert fake.run_calls[0]["confirmed_outline"] is None

    results = _events_of_type(stream, "result")
    assert len(results) == 1
    payload = results[0].metadata
    assert payload["outline_preview"] is True
    assert payload["research_config"] == {"mode": "report", "depth": "quick"}


async def test_confirmed_outline_is_converted_to_sub_topic_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        {
            "response": "final report body",
            "output_dir": "",
            "metadata": {"mode": "agentic_research"},
        },
    )
    capability = _capability()
    context = UnifiedContext(
        session_id="s1",
        user_message="topic",
        config_overrides={
            "mode": "notes",
            "depth": "manual",
            "manual_subtopics": 3,
            "manual_max_iterations": 2,
            "confirmed_outline": [
                {"title": "A"},
                {"title": "B", "overview": "b overview"},
            ],
        },
    )
    stream = StreamBus()

    await capability.run(context, stream)

    fake = _FakePipeline.instances[0]
    confirmed = fake.run_calls[0]["confirmed_outline"]
    assert [item.title for item in confirmed] == ["A", "B"]
    assert [item.overview for item in confirmed] == ["", "b overview"]

    results = _events_of_type(stream, "result")
    assert results == []


async def test_first_call_forwards_manual_knobs_in_research_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        {"outline_preview": True, "topic": "t", "sub_topics": [], "response": "", "output_dir": ""},
    )
    capability = _capability()
    context = UnifiedContext(
        session_id="s1",
        user_message="topic",
        config_overrides={
            "mode": "comparison",
            "depth": "manual",
            "manual_subtopics": 4,
            "manual_max_iterations": 5,
        },
    )
    stream = StreamBus()

    await capability.run(context, stream)

    results = _events_of_type(stream, "result")
    assert results[0].metadata["research_config"] == {
        "mode": "comparison",
        "depth": "manual",
        "manual_subtopics": 4,
        "manual_max_iterations": 5,
    }


async def test_kb_attached_is_forwarded_to_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, {"outline_preview": True, "topic": "t", "sub_topics": []})
    capability = _capability()
    context = UnifiedContext(
        session_id="s1",
        user_message="topic",
        knowledge_bases=["my-kb"],
        config_overrides={"mode": "report", "depth": "standard"},
    )
    stream = StreamBus()

    await capability.run(context, stream)

    assert _FakePipeline.instances[0].kb_name == "my-kb"


async def test_invalid_request_config_raises_before_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, {})
    capability = _capability()
    context = UnifiedContext(
        session_id="s1",
        user_message="topic",
        config_overrides={"mode": "not-a-mode", "depth": "quick"},
    )
    stream = StreamBus()

    with pytest.raises(ValueError, match="Invalid deep research config"):
        await capability.run(context, stream)

    assert _FakePipeline.instances == []
    assert _events_of_type(stream, "result") == []
