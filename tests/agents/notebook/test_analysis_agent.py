"""Behavioral tests for NotebookAnalysisAgent (three-stage notebook analysis)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType


def _make_cfg(**overrides):
    cfg = SimpleNamespace(
        model="gpt-4o-mini",
        api_key="test-key",
        base_url="https://api.example.com/v1",
        api_version=None,
        binding="openai",
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _make_agent(monkeypatch, *, language="en", cfg=None):
    monkeypatch.setattr(
        "deeptutor.agents.notebook.analysis_agent.get_llm_config",
        lambda: cfg if cfg is not None else _make_cfg(),
    )
    from deeptutor.agents.notebook.analysis_agent import NotebookAnalysisAgent

    return NotebookAnalysisAgent(language=language)


def _make_agent_with_prompts(monkeypatch, sections, *, language="en"):
    class _StubPromptManager:
        def __init__(self, loaded):
            self._loaded = loaded

        def load_prompts(self, module_name, agent_name, lang="zh", subdirectory=None):
            return self._loaded

    monkeypatch.setattr(
        "deeptutor.agents.notebook.analysis_agent.get_prompt_manager",
        lambda: _StubPromptManager(sections),
    )
    return _make_agent(monkeypatch, language=language)


class _EventCollector:
    def __init__(self) -> None:
        self.events: list[StreamEvent] = []

    async def __call__(self, event: StreamEvent) -> None:
        self.events.append(event)

    def of_type(self, event_type) -> list[StreamEvent]:
        return [e for e in self.events if e.type == event_type]


def _records(*ids):
    return [
        {
            "id": rid,
            "notebook_name": f"nb-{rid}",
            "type": "chat",
            "title": f"Title {rid}",
            "summary": f"Summary {rid}",
            "output": f"Full output for {rid}",
        }
        for rid in ids
    ]


def _stub_llm_stream(monkeypatch, per_call):
    """Stub llm_stream with one entry per expected call (chunks or an exception)."""
    calls: list[dict] = []

    async def _stream(**kwargs):
        calls.append(kwargs)
        index = len(calls) - 1
        if index >= len(per_call):
            raise AssertionError(f"unexpected extra llm_stream call #{index + 1}")
        outcome = per_call[index]
        if isinstance(outcome, Exception):
            raise outcome
        for chunk in outcome:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    monkeypatch.setattr("deeptutor.agents.notebook.analysis_agent.llm_stream", _stream)
    return calls


@pytest.mark.parametrize(
    ("raw_language", "expected"),
    [
        ("zh", "zh"),
        ("ZH-TW", "zh"),
        ("en", "en"),
        ("EN-US", "en"),
        (None, "en"),
        ("fr", "en"),
    ],
)
def test_init_normalizes_language(monkeypatch, raw_language, expected) -> None:
    agent = _make_agent(monkeypatch, language=raw_language)
    assert agent.language == expected


def test_init_reads_llm_config_fields(monkeypatch) -> None:
    agent = _make_agent(monkeypatch, cfg=_make_cfg(binding="anthropic"))
    assert agent.model == "gpt-4o-mini"
    assert agent.api_key == "test-key"
    assert agent.base_url == "https://api.example.com/v1"
    assert agent.api_version is None
    assert agent.binding == "anthropic"


def test_init_defaults_binding_to_openai(monkeypatch) -> None:
    agent = _make_agent(monkeypatch, cfg=_make_cfg(binding=None))
    assert agent.binding == "openai"


def test_init_loads_bilingual_prompts(monkeypatch) -> None:
    for language in ("en", "zh"):
        agent = _make_agent(monkeypatch, language=language)
        for stage in ("thinking", "acting", "observing"):
            section = agent._prompts.get(stage)
            assert isinstance(section, dict), (language, stage)
            assert str(section.get("system", "")).strip()
            assert str(section.get("user_template", "")).strip()


def test_thinking_prompt_embeds_question_and_catalog(monkeypatch) -> None:
    agent = _make_agent(monkeypatch)
    records = _records("r1", "r2")

    prompt = agent._thinking_prompt("  why does this fail?  ", records)
    assert "why does this fail?" in prompt
    assert "id=r1" in prompt
    assert "id=r2" in prompt

    empty_prompt = agent._thinking_prompt("   ", records)
    assert "(empty)" in empty_prompt


def test_summary_catalog_clips_fields_and_falls_back(monkeypatch) -> None:
    agent = _make_agent(monkeypatch)

    long_title = "T" * 120
    catalog = agent._summary_catalog(
        [{"id": "r1", "notebook_name": "nb", "type": "chat", "title": long_title}]
    )
    assert f"title={'T' * 80}\n...[truncated]" in catalog
    # summary falls back to the unclipped title and stays under its own limit
    assert f"summary={long_title}" in catalog

    fallback = agent._summary_catalog(
        [{"id": "r2", "notebook_name": "nb", "type": "chat", "title": "Only title"}]
    )
    assert "summary=Only title" in fallback

    assert agent._summary_catalog([]) == "(none)"


def test_acting_prompt_embeds_thinking_text(monkeypatch) -> None:
    agent = _make_agent(monkeypatch)

    prompt = agent._acting_prompt("question?", "prior reasoning", _records("r1"))
    assert "prior reasoning" in prompt
    assert "id=r1" in prompt

    blank = agent._acting_prompt("question?", "", _records("r1"))
    assert "(empty)" in blank


def test_observing_prompt_renders_record_blocks_and_clips(monkeypatch) -> None:
    agent = _make_agent(monkeypatch)

    long_output = "O" * 2600
    prompt = agent._observing_prompt(
        "question?",
        "reasoning",
        [
            {
                "id": "r1",
                "notebook_name": "nb-1",
                "title": "T1",
                "summary": "S1",
                "output": long_output,
            }
        ],
    )
    assert "Record ID: r1" in prompt
    assert "Notebook: nb-1" in prompt
    assert "Title: T1" in prompt
    assert "Summary: S1" in prompt
    assert "O" * 2500 in prompt
    assert long_output not in prompt

    empty = agent._observing_prompt("question?", "reasoning", [])
    assert "(none)" in empty


def test_token_kwargs_empty_without_model(monkeypatch) -> None:
    agent = _make_agent(monkeypatch, cfg=_make_cfg(model=None))
    assert agent._token_kwargs(900) == {}


@pytest.mark.asyncio
async def test_analyze_happy_path_event_sequence_and_result(monkeypatch) -> None:
    agent = _make_agent(monkeypatch)
    records = _records("r1", "r2", "r3")
    calls = _stub_llm_stream(
        monkeypatch,
        [
            ["Thinking ", "about r2"],
            ['{"selected_record_ids": ["r2", "r1"]}'],
            ["Answer ", "text"],
        ],
    )
    collector = _EventCollector()

    result = await agent.analyze(
        user_question="What happened?",
        records=records,
        emit=collector,
    )

    assert result == "Answer text"

    assert [e.type for e in collector.events] == [
        StreamEventType.STAGE_START,
        StreamEventType.THINKING,
        StreamEventType.THINKING,
        StreamEventType.STAGE_END,
        StreamEventType.STAGE_START,
        StreamEventType.TOOL_CALL,
        StreamEventType.TOOL_RESULT,
        StreamEventType.STAGE_END,
        StreamEventType.STAGE_START,
        StreamEventType.OBSERVATION,
        StreamEventType.OBSERVATION,
        StreamEventType.STAGE_END,
        StreamEventType.RESULT,
    ]
    assert {e.source for e in collector.events} == {"notebook_analysis"}

    stages = [e.stage for e in collector.events if e.type == StreamEventType.STAGE_START]
    assert stages == ["notebook_thinking", "notebook_acting", "notebook_observing"]

    result_event = collector.of_type(StreamEventType.RESULT)[0]
    assert result_event.metadata["observation"] == "Answer text"
    assert result_event.metadata["selected_record_ids"] == ["r2", "r1"]

    tool_call = collector.of_type(StreamEventType.TOOL_CALL)[0]
    assert tool_call.content == "notebook_lookup"
    assert tool_call.metadata["args"]["selected_record_ids"] == ["r2", "r1"]

    tool_result = collector.of_type(StreamEventType.TOOL_RESULT)[0]
    assert "r2 | nb-r2 | Title r2" in tool_result.content
    assert "Full output for r2" in tool_result.content

    assert len(calls) == 3
    assert calls[0]["temperature"] == 0.2
    assert calls[1]["temperature"] == 0.1
    assert calls[2]["temperature"] == 0.2
    assert calls[0]["binding"] == "openai"
    assert calls[0]["model"] == "gpt-4o-mini"
    assert "What happened?" in calls[0]["prompt"]
    assert "about r2" in calls[1]["prompt"]
    assert calls[2]["system_prompt"] != calls[0]["system_prompt"]


@pytest.mark.asyncio
async def test_analyze_skips_empty_stream_chunks(monkeypatch) -> None:
    agent = _make_agent(monkeypatch)
    _stub_llm_stream(
        monkeypatch,
        [
            ["", "visible", ""],
            ['{"selected_record_ids": ["r1"]}'],
            ["", "final", ""],
        ],
    )
    collector = _EventCollector()

    result = await agent.analyze(user_question="q", records=_records("r1"), emit=collector)

    assert result == "final"
    thinking = [e.content for e in collector.of_type(StreamEventType.THINKING)]
    assert thinking == ["visible"]
    observation = [e.content for e in collector.of_type(StreamEventType.OBSERVATION)]
    assert observation == ["final"]


@pytest.mark.asyncio
async def test_analyze_strips_think_tags_from_thinking(monkeypatch) -> None:
    agent = _make_agent(monkeypatch)
    calls = _stub_llm_stream(
        monkeypatch,
        [
            ["<think>scratchpad</think>", "reasoned body"],
            ['{"selected_record_ids": ["r1"]}'],
            ["done"],
        ],
    )

    await agent.analyze(user_question="q", records=_records("r1"))

    acting_prompt = calls[1]["prompt"]
    assert "reasoned body" in acting_prompt
    assert "scratchpad" not in acting_prompt


@pytest.mark.asyncio
async def test_analyze_selection_dedup_unknown_and_cap_at_five(monkeypatch) -> None:
    agent = _make_agent(monkeypatch)
    records = _records(*[f"r{i}" for i in range(1, 9)])
    _stub_llm_stream(
        monkeypatch,
        [
            ["think"],
            ['{"selected_record_ids": ["r3", "r3", "", "ghost", "r1", "r4", "r5", "r6", "r7"]}'],
            ["obs"],
        ],
    )
    collector = _EventCollector()

    await agent.analyze(user_question="q", records=records, emit=collector)

    result_event = collector.of_type(StreamEventType.RESULT)[0]
    assert result_event.metadata["selected_record_ids"] == ["r3", "r1", "r4", "r5", "r6"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "acting_chunks",
    [
        ["not valid json at all"],
        ['{"selected_record_ids": "r1"}'],
        ["[1, 2, 3]"],
    ],
    ids=["garbage", "non-list-ids", "non-dict-payload"],
)
async def test_analyze_falls_back_to_first_records_on_bad_selection(
    monkeypatch, acting_chunks
) -> None:
    agent = _make_agent(monkeypatch)
    records = _records(*[f"r{i}" for i in range(1, 8)])
    _stub_llm_stream(monkeypatch, [["think"], acting_chunks, ["obs"]])
    collector = _EventCollector()

    await agent.analyze(user_question="q", records=records, emit=collector)

    result_event = collector.of_type(StreamEventType.RESULT)[0]
    assert result_event.metadata["selected_record_ids"] == ["r1", "r2", "r3", "r4", "r5"]


@pytest.mark.asyncio
async def test_analyze_empty_records_produce_empty_selection(monkeypatch) -> None:
    agent = _make_agent(monkeypatch)
    calls = _stub_llm_stream(monkeypatch, [["think"], ['{"selected_record_ids": ["r1"]}'], ["obs"]])
    collector = _EventCollector()

    await agent.analyze(user_question="q", records=[], emit=collector)

    result_event = collector.of_type(StreamEventType.RESULT)[0]
    assert result_event.metadata["selected_record_ids"] == []
    tool_result = collector.of_type(StreamEventType.TOOL_RESULT)[0]
    assert tool_result.content == "(none)"
    assert "id=" not in calls[0]["prompt"]
    assert "(none)" in calls[0]["prompt"]


@pytest.mark.asyncio
async def test_empty_thinking_stream_uses_empty_placeholder(monkeypatch) -> None:
    agent = _make_agent(monkeypatch)
    calls = _stub_llm_stream(
        monkeypatch,
        [[], ['{"selected_record_ids": ["r1"]}'], ["final"]],
    )

    result = await agent.analyze(user_question="q", records=_records("r1"))

    assert result == "final"
    assert "(empty)" in calls[1]["prompt"]


@pytest.mark.asyncio
async def test_llm_timeout_in_thinking_propagates_without_stage_end(
    monkeypatch,
) -> None:
    agent = _make_agent(monkeypatch)
    _stub_llm_stream(monkeypatch, [TimeoutError("llm timed out")])
    collector = _EventCollector()

    with pytest.raises(TimeoutError):
        await agent.analyze(user_question="q", records=_records("r1"), emit=collector)

    starts = collector.of_type(StreamEventType.STAGE_START)
    assert [e.stage for e in starts] == ["notebook_thinking"]
    assert collector.of_type(StreamEventType.STAGE_END) == []
    assert collector.of_type(StreamEventType.RESULT) == []


@pytest.mark.asyncio
async def test_llm_failure_mid_observing_propagates_without_result(
    monkeypatch,
) -> None:
    agent = _make_agent(monkeypatch)
    _stub_llm_stream(
        monkeypatch,
        [
            ["thought"],
            ['{"selected_record_ids": ["r1"]}'],
            ["partial ", RuntimeError("upstream connection reset")],
        ],
    )
    collector = _EventCollector()

    with pytest.raises(RuntimeError, match="upstream connection reset"):
        await agent.analyze(user_question="q", records=_records("r1"), emit=collector)

    observation = [e.content for e in collector.of_type(StreamEventType.OBSERVATION)]
    assert observation == ["partial "]
    assert collector.of_type(StreamEventType.RESULT) == []
    ends = [e.stage for e in collector.of_type(StreamEventType.STAGE_END)]
    assert ends == ["notebook_thinking", "notebook_acting"]


@pytest.mark.asyncio
async def test_analyze_without_emit_returns_observation(monkeypatch) -> None:
    agent = _make_agent(monkeypatch)
    _stub_llm_stream(
        monkeypatch,
        [["think"], ['{"selected_record_ids": ["r1", "missing"]}'], ["note body"]],
    )

    result = await agent.analyze(user_question="q", records=_records("r1"), emit=None)

    assert result == "note body"


def test_stage_text_returns_empty_for_malformed_section(monkeypatch) -> None:
    agent = _make_agent_with_prompts(
        monkeypatch, {"thinking": "not-a-dict", "acting": None, "observing": {}}
    )

    assert agent._thinking_system_prompt() == ""
    assert agent._acting_system_prompt() == ""
    assert agent._observing_system_prompt() == ""
