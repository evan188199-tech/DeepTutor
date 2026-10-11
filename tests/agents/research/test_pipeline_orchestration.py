"""Fake-level orchestration tests for the research agent pipeline.

Existing coverage reaches ``ResearchPipeline`` through the services and
registry layers, plus host-level unit tests for the rephrase/block/report
callbacks. This module drives the orchestration surface itself — the
``run`` entry point, phase advancement, the outline-preview two-stage
flow, and the failure / degradation branches — with fake LLM clients and
fake phases, never touching the network.
"""

from __future__ import annotations

import asyncio
import types
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deeptutor.agents.research.data_structures import DynamicTopicQueue, TopicStatus
from deeptutor.agents.research.pipeline import (
    IncompleteReportError,
    ResearchedBlock,
    ResearchPipeline,
    SubTopicItem,
    _outline_payload_is_usable,
    _report_outline_payload_is_usable,
    _topic_index_from_block_id,
)
from deeptutor.agents.research.utils.citation_manager import CitationManager
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.stream_bus import StreamBus

pytestmark = pytest.mark.asyncio


class _FakeLLM:
    binding = "openai"
    model = "gpt-x"
    api_key = "k"
    base_url = "u"
    api_version = None
    extra_headers: dict = {}
    reasoning_effort = None


class _FakeRegistry:
    def build_openai_schemas(self, _names):
        return []

    def build_prompt_text(self, _names, **_kwargs):
        return "- none"

    def get(self, _name):
        return None

    def get_enabled(self, _names):
        return []


def _make_pipeline(runtime_config: dict | None = None) -> ResearchPipeline:
    with (
        patch("deeptutor.agents.research.pipeline.get_llm_config", lambda: _FakeLLM()),
        patch("deeptutor.agents.research.pipeline.get_tool_registry", lambda: _FakeRegistry()),
    ):
        return ResearchPipeline(language="en", runtime_config=runtime_config or {})


def _stage_names(stream: StreamBus) -> list[str]:
    return [event.stage for event in stream._history if event.type.value == "stage_start"]


def _events_of_type(stream: StreamBus, type_value: str):
    return [event for event in stream._history if event.type.value == type_value]


# ---------------------------------------------------------------------------
# run() entry point: preparation, delegation, and visible failure
# ---------------------------------------------------------------------------


async def test_run_prepares_tools_and_delegates_to_inner() -> None:
    pipeline = _make_pipeline()
    inner_calls: list[dict] = []
    prepared: list[str] = []
    client_marker = object()

    async def fake_pageindex() -> None:
        prepared.append("pageindex")

    async def fake_providers(context) -> None:
        prepared.append("providers")

    async def fake_inner(self, **kwargs):
        inner_calls.append(kwargs)
        return {"response": "ok"}

    pipeline._prepare_pageindex_tools = fake_pageindex
    pipeline._prepare_research_providers = fake_providers
    pipeline._run_inner = types.MethodType(fake_inner, pipeline)
    with patch.object(pipeline, "_build_client", lambda: client_marker):
        result = await pipeline.run(
            context=UnifiedContext(session_id="s1", user_message="topic"),
            topic="topic",
            stream=StreamBus(),
        )

    assert result == {"response": "ok"}
    assert prepared == ["pageindex", "providers"]
    assert inner_calls[0]["client"] is client_marker
    assert inner_calls[0]["confirmed_outline"] is None


async def test_run_failure_emits_visible_error_and_reraises() -> None:
    pipeline = _make_pipeline()
    stream = StreamBus()

    async def fake_pageindex() -> None:
        return None

    async def fake_providers(context) -> None:
        raise RuntimeError("provider exploded")

    pipeline._prepare_pageindex_tools = fake_pageindex
    pipeline._prepare_research_providers = fake_providers

    with patch.object(pipeline, "_build_client", lambda: None):
        with pytest.raises(RuntimeError, match="provider exploded"):
            await pipeline.run(
                context=UnifiedContext(session_id="s1", user_message="topic"),
                topic="topic",
                stream=stream,
            )

    errors = _events_of_type(stream, "error")
    contents = _events_of_type(stream, "content")
    assert errors, "failure must surface a labelled error trace card"
    assert "RuntimeError: provider exploded" in errors[0].content
    assert contents, "failure must also warn in the chat bubble"
    assert contents[-1].content.startswith("⚠")
    assert contents[-1].content.endswith("provider exploded")


async def test_emit_visible_failure_maps_incomplete_report_to_reporting_stage() -> None:
    pipeline = _make_pipeline()
    stream = StreamBus()
    exc = IncompleteReportError("The report stopped before these parts: Conclusion")
    exc.__cause__ = RuntimeError("outline writer died")

    await pipeline._emit_visible_failure(stream, exc)

    errors = _events_of_type(stream, "error")
    contents = _events_of_type(stream, "content")
    assert errors[0].stage == "reporting"
    assert errors[0].content == "RuntimeError: outline writer died"
    assert "report stopped" in contents[-1].content


async def test_emit_visible_failure_generic_error_stays_on_researching_stage() -> None:
    pipeline = _make_pipeline()
    stream = StreamBus()

    await pipeline._emit_visible_failure(stream, ValueError("bad request"))

    errors = _events_of_type(stream, "error")
    assert errors[0].stage == "researching"
    assert errors[0].content == "ValueError: bad request"


# ---------------------------------------------------------------------------
# Phase advancement: outline-preview flow (Phase 1 + 2) and skip path
# ---------------------------------------------------------------------------


async def test_unconfirmed_outline_runs_rephrase_then_decompose_and_previews() -> None:
    pipeline = _make_pipeline()
    stream = StreamBus()
    seen_topics: list[tuple[str, str]] = []

    async def fake_rephrase(self, *, topic, **_kwargs):
        seen_topics.append(("rephrase", topic))
        return "refined topic"

    async def fake_decompose(self, *, topic, **_kwargs):
        seen_topics.append(("decompose", topic))
        return [SubTopicItem(title="Sub A", overview="a"), SubTopicItem(title="Sub B")]

    pipeline._rephrase = types.MethodType(fake_rephrase, pipeline)
    pipeline._decompose = types.MethodType(fake_decompose, pipeline)

    result = await pipeline._run_inner(
        context=UnifiedContext(session_id="s1", user_message="original"),
        topic="  original  ",
        image_attachments=[],
        confirmed_outline=None,
        stream=stream,
        client=None,
    )

    assert seen_topics == [("rephrase", "  original  "), ("decompose", "refined topic")]
    assert result["outline_preview"] is True
    assert result["topic"] == "refined topic"
    assert result["response"] == ""
    assert result["sub_topics"] == [
        {"title": "Sub A", "overview": "a"},
        {"title": "Sub B", "overview": ""},
    ]
    assert _stage_names(stream) == ["rephrasing", "decomposing"]
    assert not _events_of_type(stream, "result")


async def test_rephrase_disabled_skips_phase_one() -> None:
    pipeline = _make_pipeline(runtime_config={"planning": {"rephrase": {"enabled": False}}})
    stream = StreamBus()
    calls: list[str] = []

    async def fake_rephrase(self, **_kwargs):
        calls.append("rephrase")
        return "should not be used"

    async def fake_decompose(self, *, topic, **_kwargs):
        calls.append(f"decompose:{topic}")
        return [SubTopicItem(title=topic)]

    pipeline._rephrase = types.MethodType(fake_rephrase, pipeline)
    pipeline._decompose = types.MethodType(fake_decompose, pipeline)

    result = await pipeline._run_inner(
        context=UnifiedContext(session_id="s1"),
        topic="  raw topic  ",
        image_attachments=[],
        confirmed_outline=None,
        stream=stream,
        client=None,
    )

    assert calls == ["decompose:raw topic"]
    assert result["topic"] == "raw topic"
    assert _stage_names(stream) == ["rephrasing", "decomposing"]


# ---------------------------------------------------------------------------
# Rephrase degradation branches
# ---------------------------------------------------------------------------


async def test_rephrase_returns_raw_topic_when_ask_user_missing() -> None:
    pipeline = _make_pipeline()

    async def explode(**_kwargs):
        raise AssertionError("loop must not run without ask_user")

    with patch("deeptutor.agents.research.pipeline.run_agentic_loop", explode):
        refined = await pipeline._rephrase(
            topic="  raw  ",
            context=UnifiedContext(session_id="s1"),
            stream=StreamBus(),
            client=None,
        )

    assert refined == "raw"


async def test_rephrase_loop_failure_falls_back_to_raw_topic() -> None:
    pipeline = _make_pipeline()

    async def fake_registry_get(name):
        return object() if name == "ask_user" else None

    pipeline.registry.get = fake_registry_get

    async def explode(**_kwargs):
        raise RuntimeError("llm down")

    with patch("deeptutor.agents.research.pipeline.run_agentic_loop", explode):
        refined = await pipeline._rephrase(
            topic="raw topic",
            context=UnifiedContext(session_id="s1"),
            stream=StreamBus(),
            client=None,
        )

    assert refined == "raw topic"


async def test_rephrase_empty_finish_text_falls_back_to_raw_topic() -> None:
    pipeline = _make_pipeline()

    async def fake_registry_get(name):
        return object() if name == "ask_user" else None

    pipeline.registry.get = fake_registry_get

    async def fake_loop(**_kwargs):
        return SimpleNamespace(final_text="   ", completed=True, iterations=1)

    with patch("deeptutor.agents.research.pipeline.run_agentic_loop", fake_loop):
        refined = await pipeline._rephrase(
            topic="raw topic",
            context=UnifiedContext(session_id="s1"),
            stream=StreamBus(),
            client=None,
        )

    assert refined == "raw topic"


# ---------------------------------------------------------------------------
# Decompose / outline degradation branches
# ---------------------------------------------------------------------------


async def _decompose_with_payload(pipeline: ResearchPipeline, data) -> list[SubTopicItem]:
    async def fake_retry(run, *, is_usable, logger_instance=None):
        return data

    with patch("deeptutor.agents.research.pipeline.payload_with_reasoning_retry", fake_retry):
        return await pipeline._decompose(
            topic="topic",
            context=UnifiedContext(session_id="s1"),
            stream=StreamBus(),
            client=None,
        )


async def test_decompose_unusable_payload_degrades_to_single_topic() -> None:
    pipeline = _make_pipeline()
    outline = await _decompose_with_payload(pipeline, None)
    assert outline == [SubTopicItem(title="topic", overview="")]


async def test_parse_outline_accepts_arrays_dicts_and_strings_with_cap() -> None:
    pipeline = _make_pipeline(runtime_config={"planning": {"decompose": {"initial_subtopics": 2}}})
    outline = pipeline._parse_outline(
        "topic",
        [
            {"title": "A", "overview": "a"},
            {"topic": "B", "description": "b"},
            "C",
            {"overview": "no title, dropped"},
            {"title": "D"},
        ],
    )
    assert [(item.title, item.overview) for item in outline] == [
        ("A", "a"),
        ("B", "b"),
    ]


def test_outline_payload_usability_helpers() -> None:
    assert _outline_payload_is_usable([{"title": "A"}]) is True
    assert _outline_payload_is_usable({"sub_topics": [{"title": "A"}]}) is True
    assert _outline_payload_is_usable({"subtopics": [{"title": "A"}]}) is True
    assert _outline_payload_is_usable([]) is False
    assert _outline_payload_is_usable({}) is False
    assert _outline_payload_is_usable("nope") is False

    assert _report_outline_payload_is_usable({"sections": [{"title": "S"}]}) is True
    assert _report_outline_payload_is_usable([{"title": "S"}]) is True
    assert _report_outline_payload_is_usable({}) is False
    assert _report_outline_payload_is_usable(None) is False


# ---------------------------------------------------------------------------
# Queue scheduler: series vs parallel, APPEND pickup, gather failure backfill
# ---------------------------------------------------------------------------


def _fake_block_phase(pipeline: ResearchPipeline, recorder: list, *, hook=None) -> None:
    async def fake_research_block(self, *, block, queue, citations, topic, context, stream, client):
        queue.mark_researching(block.block_id)
        recorder.append(("start", block.block_id))
        if hook is not None:
            await hook(block=block, queue=queue)
        queue.mark_completed(block.block_id)
        recorder.append(("end", block.block_id))
        return ResearchedBlock(block=block, knowledge=f"knowledge {block.block_id}")

    pipeline._research_block = types.MethodType(fake_research_block, pipeline)


async def _drive(
    pipeline: ResearchPipeline,
    titles: list[str],
    tmp_path,
) -> list[ResearchedBlock]:
    queue = DynamicTopicQueue("orch-q", max_length=8)
    for title in titles:
        queue.add_block(title, "")
    return await pipeline._drive_queue(
        queue=queue,
        citations=CitationManager("orch-q", cache_dir=tmp_path),
        topic="topic",
        context=UnifiedContext(session_id="s1"),
        image_attachments=[],
        stream=StreamBus(),
        client=None,
    )


async def test_queue_runs_series_blocks_one_at_a_time(tmp_path) -> None:
    pipeline = _make_pipeline(runtime_config={"researching": {"execution_mode": "series"}})
    recorder: list[tuple[str, str]] = []
    _fake_block_phase(pipeline, recorder)

    researched = await _drive(pipeline, ["A", "B"], tmp_path)

    assert recorder == [
        ("start", "block_1"),
        ("end", "block_1"),
        ("start", "block_2"),
        ("end", "block_2"),
    ]
    assert [rb.knowledge for rb in researched] == ["knowledge block_1", "knowledge block_2"]


async def test_queue_parallel_batch_runs_blocks_concurrently(tmp_path) -> None:
    pipeline = _make_pipeline(
        runtime_config={"researching": {"execution_mode": "parallel", "max_parallel_topics": 3}}
    )
    in_flight = {"count": 0, "max": 0}

    async def hook(block, queue):
        in_flight["count"] += 1
        in_flight["max"] = max(in_flight["max"], in_flight["count"])
        await asyncio.sleep(0)
        in_flight["count"] -= 1

    recorder: list[tuple[str, str]] = []
    _fake_block_phase(pipeline, recorder, hook=hook)

    await _drive(pipeline, ["A", "B"], tmp_path)

    assert in_flight["max"] == 2


async def test_queue_picks_up_appended_child_after_parent(tmp_path) -> None:
    pipeline = _make_pipeline(runtime_config={"researching": {"execution_mode": "series"}})
    recorder: list[tuple[str, str]] = []

    async def append_child_once(block, queue):
        if block.block_id == "block_1" and not any(b.sub_topic == "Child" for b in queue.blocks):
            queue.append_child(parent=block, sub_topic="Child", overview="")

    _fake_block_phase(pipeline, recorder, hook=append_child_once)

    researched = await _drive(pipeline, ["Parent"], tmp_path)

    starts = [bid for phase, bid in recorder if phase == "start"]
    assert starts == ["block_1", "block_2"]
    assert researched[-1].block.sub_topic == "Child"
    assert researched[-1].knowledge == "knowledge block_2"


async def test_queue_backfills_empty_knowledge_when_block_raises(tmp_path) -> None:
    pipeline = _make_pipeline(runtime_config={"researching": {"execution_mode": "series"}})
    queue = DynamicTopicQueue("orch-q2", max_length=8)
    queue.add_block("Bad", "")
    queue.add_block("Good", "")
    calls = {"n": 0}

    async def one_shot(self, *, block, queue, citations, topic, context, stream, client):
        calls["n"] += 1
        queue.mark_researching(block.block_id)
        if calls["n"] == 1:
            raise RuntimeError("gather-level failure")
        queue.mark_completed(block.block_id)
        return ResearchedBlock(block=block, knowledge="fine")

    pipeline._research_block = types.MethodType(one_shot, pipeline)
    researched = await pipeline._drive_queue(
        queue=queue,
        citations=CitationManager("orch-q2", cache_dir=tmp_path),
        topic="topic",
        context=UnifiedContext(session_id="s1"),
        image_attachments=[],
        stream=StreamBus(),
        client=None,
    )

    assert researched[0].block.sub_topic == "Bad"
    assert researched[0].knowledge == ""
    assert queue.blocks[0].status == TopicStatus.FAILED
    assert researched[1].block.sub_topic == "Good"
    assert researched[1].knowledge == "fine"


# ---------------------------------------------------------------------------
# Report planning degradation
# ---------------------------------------------------------------------------


def _blocks_from_queue(tmp_path, titles: list[str]):
    queue = DynamicTopicQueue("orch-report", max_length=8)
    blocks = [queue.add_block(title, "") for title in titles]
    return [ResearchedBlock(block=block, knowledge=f"k-{block.block_id}") for block in blocks]


def test_parse_report_outline_falls_back_to_one_section_per_block(tmp_path) -> None:
    pipeline = _make_pipeline()
    blocks = _blocks_from_queue(tmp_path, ["First", "Second"])

    outline = pipeline._parse_report_outline("the topic", None, blocks)

    assert outline.title == "the topic"
    assert [(s.id, s.title) for s in outline.sections] == [
        (blocks[0].block.block_id, "First"),
        (blocks[1].block.block_id, "Second"),
    ]
    assert outline.sections[0].block_ids == (blocks[0].block.block_id,)


def test_parse_report_outline_resolves_section_blocks_by_title(tmp_path) -> None:
    pipeline = _make_pipeline()
    blocks = _blocks_from_queue(tmp_path, ["Alpha topic", "Beta topic"])
    first_id = blocks[0].block.block_id
    second_id = blocks[1].block.block_id

    outline = pipeline._parse_report_outline(
        "topic",
        {
            "title": "Report",
            "sections": [
                {"id": "S1", "title": "About Alpha", "block_ids": ["Alpha Topic"]},
                {"id": "S2", "title": "About Beta", "blocks": [second_id]},
            ],
        },
        blocks,
    )

    assert outline.sections[0].block_ids == (first_id,)
    assert outline.sections[1].block_ids == (second_id,)


# ---------------------------------------------------------------------------
# Note summariser degradation
# ---------------------------------------------------------------------------


def _client_returning(content: object):
    async def create(**_kwargs):
        return SimpleNamespace(choices=content)

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def _client_raising():
    async def create(**_kwargs):
        raise RuntimeError("provider down")

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


async def test_summarise_tool_result_empty_answer_short_circuits() -> None:
    pipeline = _make_pipeline()
    client = _client_returning([SimpleNamespace(message=SimpleNamespace(content="boom"))])

    result = await pipeline._summarise_tool_result(
        tool_name="rag", query="q", raw_answer="   ", client=client
    )
    assert result == ""


async def test_summarise_tool_result_falls_back_to_raw_slice_on_error() -> None:
    pipeline = _make_pipeline()
    raw = "x" * 800

    result = await pipeline._summarise_tool_result(
        tool_name="web_search", query="q", raw_answer=raw, client=_client_raising()
    )
    assert result == raw[:600]


async def test_summarise_tool_result_strips_finish_label() -> None:
    pipeline = _make_pipeline()
    client = _client_returning(
        [SimpleNamespace(message=SimpleNamespace(content="``FINISH``\nClean summary."))]
    )

    result = await pipeline._summarise_tool_result(
        tool_name="rag", query="q", raw_answer="raw text", client=client
    )
    assert result == "Clean summary."


async def test_summarise_tool_result_empty_content_uses_raw_slice() -> None:
    pipeline = _make_pipeline()
    client = _client_returning([])

    result = await pipeline._summarise_tool_result(
        tool_name="rag", query="q", raw_answer="raw answer body", client=client
    )
    assert result == "raw answer body"


def test_topic_index_helper_extracts_block_number() -> None:
    assert _topic_index_from_block_id("block_12") == 12
    assert _topic_index_from_block_id("ad-hoc") is None
