"""Focused tests for NotebookSummarizeAgent prompting, parsing and degradation.

Covers the bilingual prompt assembly (YAML packs, field clipping, record
hints), output parsing (chunk joining and thinking-tag cleanup), and the
failure/timeout behaviour of the streaming path — all against a fake LLM
stream, with no real network access.
"""

from __future__ import annotations

import asyncio

import pytest

from deeptutor.services.llm.config import LLMConfig

MODULE = "deeptutor.agents.notebook.summarize_agent"


def _make_cfg(**overrides) -> LLMConfig:
    defaults = dict(
        model="gpt-4o-mini",
        api_key="test-key",
        base_url="https://api.example.com/v1",
        binding="openai",
        provider_name="openai",
        provider_mode="standard",
    )
    defaults.update(overrides)
    return LLMConfig(**defaults)


def _make_agent(monkeypatch, *, language: str = "en", **cfg_overrides):
    cfg = _make_cfg(**cfg_overrides)
    monkeypatch.setattr(f"{MODULE}.get_llm_config", lambda: cfg)

    from deeptutor.agents.notebook.summarize_agent import NotebookSummarizeAgent

    return NotebookSummarizeAgent(language=language)


def _install_fake_stream(monkeypatch, *, chunks=None, error=None) -> dict:
    """Replace the module-level llm_stream with a fake offline generator."""
    captured: dict = {}

    async def _fake_llm_stream(**kwargs):
        captured.update(kwargs)
        for chunk in chunks or []:
            yield chunk
        if error is not None:
            raise error

    monkeypatch.setattr(f"{MODULE}.llm_stream", _fake_llm_stream)
    return captured


async def _collect(agen) -> list[str]:
    out: list[str] = []
    async for chunk in agen:
        out.append(chunk)
    return out


# ---------------------------------------------------------------------------
# Language normalization and prompt pack loading
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw_language", "expected"),
    [("zh-CN", "zh"), ("ZH", "zh"), ("EN", "en"), ("fr", "en"), (None, "en")],
)
def test_language_normalized_to_supported_locale(monkeypatch, raw_language, expected):
    agent = _make_agent(monkeypatch, language=raw_language)
    assert agent.language == expected


def test_prompts_loaded_from_bilingual_yaml_packs(monkeypatch):
    en = _make_agent(monkeypatch, language="en")
    assert en._system_prompt().startswith("You are DeepTutor's notebook summary agent")
    assert "Record type: {record_type}" in en._prompts["user_template"]
    assert "chat" in en._prompts["record_hints"]

    zh = _make_agent(monkeypatch, language="zh-CN")
    assert "notebook summary agent" in zh._system_prompt()
    assert "记录类型" in zh._prompts["user_template"]


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def test_user_prompt_assembles_fields_and_known_type_hint(monkeypatch):
    agent = _make_agent(monkeypatch)
    prompt = agent._build_user_prompt(
        title="Physics notes",
        record_type="chat",
        user_query="Explain entropy",
        output="Entropy measures disorder.",
        metadata={"source": "lecture-3"},
    )
    hint = agent._prompts["record_hints"]["chat"]
    assert "Record type: chat" in prompt
    assert f"Type hint: {hint}" in prompt
    assert "Title: Physics notes" in prompt
    assert "Explain entropy" in prompt
    assert "Entropy measures disorder." in prompt
    assert "Metadata: {'source': 'lecture-3'}" in prompt


def test_user_prompt_unknown_record_type_uses_default_hint(monkeypatch):
    agent = _make_agent(monkeypatch)
    prompt = agent._build_user_prompt(
        title="T",
        record_type="mystery",
        user_query="q",
        output="o",
        metadata={},
    )
    assert agent._prompts["record_hints"]["default"] in prompt


def test_user_prompt_clips_oversized_fields(monkeypatch):
    agent = _make_agent(monkeypatch)
    long_query = "q" * 1195 + "QUERY_SENTINEL"
    long_output = "o" * 5990 + "OUTPUT_SENTINEL"
    long_metadata = {"blob": "m" * 990 + "META_SENTINEL"}
    prompt = agent._build_user_prompt(
        title="T",
        record_type="chat",
        user_query=long_query,
        output=long_output,
        metadata=long_metadata,
    )
    assert prompt.count("...[truncated]") == 3
    assert "QUERY_SENTINEL" not in prompt
    assert "OUTPUT_SENTINEL" not in prompt
    assert "META_SENTINEL" not in prompt
    assert "qqqqq" in prompt
    assert "ooooo" in prompt


def test_user_prompt_empty_fields_use_placeholders(monkeypatch):
    agent = _make_agent(monkeypatch)
    prompt = agent._build_user_prompt(
        title="",
        record_type="chat",
        user_query="",
        output="",
        metadata={},
    )
    assert "Title: (untitled)" in prompt
    assert "(empty)" in prompt
    assert "Metadata: {}" in prompt


def test_record_hint_tolerates_malformed_prompt_pack(monkeypatch):
    agent = _make_agent(monkeypatch)
    agent._prompts = {"system": "s", "user_template": "t", "record_hints": "not-a-dict"}
    assert agent._record_hint("chat") == ""
    agent._prompts = {}
    assert agent._record_hint("chat") == ""


# ---------------------------------------------------------------------------
# Streaming: forwarded arguments and chunk filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_summary_forwards_prompt_and_temperature(monkeypatch):
    agent = _make_agent(monkeypatch)
    captured = _install_fake_stream(monkeypatch, chunks=["A", "", "B"])

    collected = await _collect(
        agent.stream_summary(
            title="T",
            record_type="chat",
            user_query="q",
            output="o",
            metadata={"k": "v"},
        )
    )

    assert collected == ["A", "B"]
    assert captured["temperature"] == 0.2
    assert captured["system_prompt"] == agent._system_prompt()
    assert "Title: T" in captured["prompt"]
    assert captured["model"] == "gpt-4o-mini"
    assert captured["api_key"] == "test-key"
    assert captured["binding"] == "openai"


@pytest.mark.parametrize(
    ("model", "limit_kwargs"),
    [
        ("gpt-3.5-turbo", {"max_tokens": 300}),
        ("o3-mini", {"max_completion_tokens": 300}),
    ],
)
@pytest.mark.asyncio
async def test_stream_summary_applies_model_specific_token_limit(monkeypatch, model, limit_kwargs):
    agent = _make_agent(monkeypatch, model=model)
    captured = _install_fake_stream(monkeypatch, chunks=["x"])

    async for _ in agent.stream_summary(title="T", record_type="chat", user_query="q", output="o"):
        pass

    for key, value in limit_kwargs.items():
        assert captured[key] == value
    other_key = "max_completion_tokens" if "max_tokens" in limit_kwargs else "max_tokens"
    assert other_key not in captured


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarize_joins_chunks_and_strips_closed_thinking_tags(monkeypatch):
    agent = _make_agent(monkeypatch)
    _install_fake_stream(
        monkeypatch,
        chunks=["<think>hidden ", "reasoning</think>", "Final ", "summary."],
    )

    summary = await agent.summarize(title="T", record_type="chat", user_query="q", output="o")

    assert summary == "Final summary."


@pytest.mark.asyncio
async def test_summarize_drops_unclosed_thinking_block(monkeypatch):
    agent = _make_agent(monkeypatch)
    _install_fake_stream(monkeypatch, chunks=["Partial answer ", "<think>interrupted scratch"])

    summary = await agent.summarize(title="T", record_type="chat", user_query="q", output="o")

    assert summary == "Partial answer"


@pytest.mark.asyncio
async def test_summarize_returns_empty_string_when_stream_yields_nothing(monkeypatch):
    agent = _make_agent(monkeypatch)
    _install_fake_stream(monkeypatch, chunks=[])

    summary = await agent.summarize(title="T", record_type="chat", user_query="q", output="o")

    assert summary == ""


# ---------------------------------------------------------------------------
# Failure / timeout degradation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_summary_propagates_llm_timeout(monkeypatch):
    agent = _make_agent(monkeypatch)
    _install_fake_stream(
        monkeypatch, chunks=["partial"], error=asyncio.TimeoutError("llm timed out")
    )

    with pytest.raises(asyncio.TimeoutError):
        await _collect(
            agent.stream_summary(title="T", record_type="chat", user_query="q", output="o")
        )


@pytest.mark.asyncio
async def test_stream_summary_propagates_provider_failure(monkeypatch):
    agent = _make_agent(monkeypatch)
    _install_fake_stream(monkeypatch, error=RuntimeError("connection reset"))

    with pytest.raises(RuntimeError, match="connection reset"):
        await _collect(
            agent.stream_summary(title="T", record_type="chat", user_query="q", output="o")
        )


@pytest.mark.asyncio
async def test_summarize_does_not_return_partial_output_on_midstream_failure(
    monkeypatch,
):
    agent = _make_agent(monkeypatch)
    _install_fake_stream(monkeypatch, chunks=["half answer"], error=RuntimeError("stream broken"))

    with pytest.raises(RuntimeError, match="stream broken"):
        await agent.summarize(title="T", record_type="chat", user_query="q", output="o")
