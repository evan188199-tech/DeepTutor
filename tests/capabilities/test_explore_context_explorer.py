"""Focused unit tests for the explore-context ``ContextExplorer``.

Complements ``test_explore_context_capability.py`` (capability wiring) by
pinning the explorer's own paths: input trimming, retrieval aggregation over
a fake ``read_source`` backend, and the empty-result / over-budget
degradation routes. No real LLM or external service is contacted — the
retrieval backend is the in-memory ``source_index`` map read by the real
``read_source`` tool.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from deeptutor.capabilities.explore_context import explorer as explorer_mod
from deeptutor.capabilities.explore_context.capability import _load_prompts
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.stream_bus import StreamBus

# The production prompt set: the loop and single-pass paths bail out early on
# empty prompts, so the real YAML files must back every test that reaches an
# LLM call.
_REAL_PROMPTS = _load_prompts("en")


def _recording_stream(chunks: list[str]):
    """llm_stream double that records its kwargs and yields *chunks*."""
    calls: list[dict[str, Any]] = []

    async def _gen(*_args: Any, **_kwargs: Any):
        for chunk in chunks:
            yield chunk

    def _stream(**kwargs: Any):
        calls.append(kwargs)
        return _gen()

    return _stream, calls


def _ctx(**metadata: Any) -> UnifiedContext:
    return UnifiedContext(
        session_id="s1",
        user_message="what did this chat do?",
        source_manifest="[Attached Sources]\n- id=hs-x type=history",
        metadata=metadata,
    )


class _UsageRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, int]] = []

    def add_estimated(self, *, input_chars: int, output_chars: int) -> None:
        self.calls.append({"input_chars": input_chars, "output_chars": output_chars})


class _ExplodingUsage:
    def add_estimated(self, **_kwargs: int) -> None:
        raise RuntimeError("usage backend down")


def _fake_stream(chunks: list[str]):
    async def _stream(*_args: Any, **_kwargs: Any):
        for chunk in chunks:
            yield chunk

    return _stream


# ---------------------------------------------------------------------------
# Fakes for the native tool-calling loop (same shapes as the capability test).
# ---------------------------------------------------------------------------


class _FakeFunc:
    def __init__(self, name: str | None = None, arguments: str | None = None) -> None:
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, index: int, call_id: str, name: str, arguments: str) -> None:
        self.index = index
        self.id = call_id
        self.function = _FakeFunc(name=name, arguments=arguments)


class _FakeDelta:
    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[_FakeToolCall] | None = None,
        reasoning_content: str | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls
        self.reasoning_content = reasoning_content
        self.reasoning = None


class _FakeChoice:
    def __init__(self, delta: _FakeDelta, provider_specific_fields: dict | None = None) -> None:
        self.delta = delta
        self.finish_reason = None
        self.provider_specific_fields = provider_specific_fields


class _FakeChunk:
    def __init__(
        self,
        delta: _FakeDelta | None = None,
        provider_specific_fields: dict | None = None,
        choices: list[_FakeChoice] | None = None,
    ) -> None:
        self.choices = (
            choices if choices is not None else [_FakeChoice(delta, provider_specific_fields)]
        )
        self.usage = None


class _EmptyChoicesChunk:
    choices: list = []


class _FakeResponseStream:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk

    async def close(self) -> None:
        self.closed = True


class _FakeCompletions:
    """Returns one queued response per ``create`` call (one per loop round).

    Recorded kwargs are deep-copied: the loop reuses (and mutates) one
    ``messages`` list across rounds, and each call must be assertion-checked
    against the state production would have sent at that point.
    """

    def __init__(self, rounds: list[list[Any]]) -> None:
        self._rounds = list(rounds)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _FakeResponseStream:
        self.calls.append(copy.deepcopy(kwargs))
        chunks = self._rounds.pop(0) if self._rounds else []
        stream = _FakeResponseStream(chunks)
        self.last_stream = stream
        return stream


class _FakeClient:
    def __init__(self, rounds: list[list[Any]]) -> None:
        self.chat = type("Chat", (), {"completions": _FakeCompletions(rounds)})()


_SINGLE_PASS_MARKER = "single-pass-fallback-must-not-appear"


@pytest.fixture
def _guard_single_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Loop tests: if the loop unexpectedly degrades, the marker betrays it and
    no real LLM call can happen."""
    monkeypatch.setattr(explorer_mod, "llm_stream", _fake_stream([_SINGLE_PASS_MARKER]))


def _read_call(source_id: str, call_id: str = "call_1") -> _FakeChunk:
    return _FakeChunk(
        _FakeDelta(
            tool_calls=[_FakeToolCall(0, call_id, "read_source", f'{{"source_id": "{source_id}"}}')]
        )
    )


# ---------------------------------------------------------------------------
# Empty-result degradation (investigate entry point)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_investigate_without_sources_is_noop() -> None:
    """No readable sources → empty string before any LLM or stream activity."""
    explorer = explorer_mod.ContextExplorer(language="en", prompts={})
    bus = StreamBus()

    assert await explorer.investigate(context=_ctx(history_references=["x"]), stream=bus) == ""
    assert bus._history == []


@pytest.mark.asyncio
async def test_blank_sources_yield_no_briefing_without_llm_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whitespace-only source bodies render to nothing: the single pass skips
    its LLM call entirely and the investigation stays empty."""

    def _must_not_stream(*_args: Any, **_kwargs: Any):
        raise AssertionError("llm_stream must not be called for blank sources")

    monkeypatch.setattr(explorer_mod, "can_use_native_tool_calling", lambda **_k: False)
    monkeypatch.setattr(explorer_mod, "llm_stream", _must_not_stream)
    explorer = explorer_mod.ContextExplorer(language="en", prompts=_REAL_PROMPTS)
    ctx = _ctx(source_index={"hs-x": "   \n\t  ", "nb-y": ""})

    assert await explorer.investigate(context=ctx, stream=StreamBus()) == ""


@pytest.mark.asyncio
async def test_loop_prompts_missing_degrades_to_single_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A native-capable provider without ``loop.*`` prompts abandons the loop
    and falls back to the single-pass briefing with the remaining prompts."""
    monkeypatch.setattr(explorer_mod, "can_use_native_tool_calling", lambda **_k: True)
    stream, calls = _recording_stream(["The transcript shows a nav rewrite by another agent."])
    monkeypatch.setattr(explorer_mod, "llm_stream", stream)
    prompts = {
        "system": "SINGLE PASS SYSTEM",
        "user_template": "Q:{question}|M:{mode}|MAN:{manifest}|SRC:{sources}",
    }
    explorer = explorer_mod.ContextExplorer(language="en", prompts=prompts)
    ctx = _ctx(source_index={"hs-x": "## Claude Code\nI rewrote the nav."})

    result = await explorer.investigate(context=ctx, stream=StreamBus())

    assert result.startswith("[Context Investigation]")
    assert "The transcript shows a nav rewrite by another agent." in result
    # The rendered source blocks reached the single-pass prompt.
    assert calls and "### [hs-x]" in calls[0]["prompt"]
    assert calls[0]["system_prompt"] == "SINGLE PASS SYSTEM"


@pytest.mark.asyncio
async def test_single_pass_llm_failure_returns_empty_without_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed single pass degrades to an empty investigation and never
    charges usage for output it did not produce."""
    monkeypatch.setattr(explorer_mod, "can_use_native_tool_calling", lambda **_k: False)

    def _boom(*_args: Any, **_kwargs: Any):
        raise RuntimeError("provider down")

    monkeypatch.setattr(explorer_mod, "llm_stream", _boom)
    explorer = explorer_mod.ContextExplorer(language="en", prompts=_REAL_PROMPTS)
    usage = _UsageRecorder()
    ctx = _ctx(source_index={"hs-x": "transcript body"})

    result = await explorer.investigate(context=ctx, stream=StreamBus(), usage=usage)

    assert result == ""
    assert usage.calls == []


# ---------------------------------------------------------------------------
# Input trimming
# ---------------------------------------------------------------------------


def test_clip_truncation_semantics_en_and_zh() -> None:
    en = explorer_mod.ContextExplorer(language="en", prompts={})
    zh = explorer_mod.ContextExplorer(language="zh", prompts={})

    assert en._clip("anything", 0) == ""
    assert en._clip("anything", -3) == ""
    assert en._clip("short", 10) == "short"
    assert en._clip("x" * 10, 10) == "x" * 10  # exact fit: no note
    clipped = en._clip("y" * 30, 10)
    assert clipped.startswith("y" * 10)
    assert clipped.endswith("…(truncated)")

    clipped_zh = zh._clip("z" * 30, 10)
    assert clipped_zh.startswith("z" * 10)
    assert clipped_zh.endswith("…（已截断）")


def test_render_blocks_skip_blank_and_clip_per_source() -> None:
    explorer = explorer_mod.ContextExplorer(language="en", prompts={})
    blocks = explorer._render_source_blocks(
        {
            "at-blank": "   ",
            "at-a": "a" * (explorer_mod.CHARS_PER_SOURCE + 500),
            "at-b": "b" * 10,
        }
    )

    assert "at-blank" not in blocks
    assert "a" * explorer_mod.CHARS_PER_SOURCE in blocks
    assert "a" * (explorer_mod.CHARS_PER_SOURCE + 1) not in blocks
    assert "### [at-a] (Document)" in blocks
    assert "### [at-b] (Document)" in blocks


def test_render_blocks_stop_at_total_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(explorer_mod, "TOTAL_CHARS", 200)
    explorer = explorer_mod.ContextExplorer(language="en", prompts={})
    blocks = explorer._render_source_blocks({"at-1": "1" * 1000, "at-2": "2" * 1000})

    assert "### [at-1]" in blocks
    assert "at-2" not in blocks  # budget exhausted → remaining source dropped
    assert "(truncated)" in blocks


def test_source_index_normalizes_and_rejects_non_dict() -> None:
    assert explorer_mod.ContextExplorer._source_index(_ctx()) == {}
    assert explorer_mod.ContextExplorer._source_index(_ctx(source_index="nope")) == {}
    normalized = explorer_mod.ContextExplorer._source_index(
        _ctx(source_index={"hs-x": 123, 5: "text", "nb-y": None})
    )
    assert normalized == {"hs-x": "123", "5": "text", "nb-y": "None"}


# ---------------------------------------------------------------------------
# Retrieval aggregation (fake retrieval backend = source_index + real read_source)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_aggregates_parallel_reads(
    monkeypatch: pytest.MonkeyPatch, _guard_single_pass: None
) -> None:
    """One round of parallel reads across sources; the investigation the model
    writes next round is grounded in both retrieved bodies."""
    monkeypatch.setattr(explorer_mod, "can_use_native_tool_calling", lambda **_k: True)
    rounds = [
        [
            _FakeChunk(
                _FakeDelta(
                    tool_calls=[
                        _FakeToolCall(0, "call_1", "read_source", '{"source_id": "hs-x"}'),
                        _FakeToolCall(1, "call_2", "read_source", '{"source_id": "nb-y"}'),
                    ]
                )
            )
        ],
        [_FakeChunk(_FakeDelta(content="Both sources describe the nav rewrite."))],
    ]
    fake_client = _FakeClient(rounds)
    monkeypatch.setattr(explorer_mod, "build_openai_client", lambda _cfg: fake_client)

    explorer = explorer_mod.ContextExplorer(language="en", prompts=_REAL_PROMPTS)
    ctx = _ctx(
        source_index={"hs-x": "transcript: nav rewritten", "nb-y": "notebook: nav task logged"}
    )

    result = await explorer.investigate(context=ctx, stream=StreamBus())

    completions = fake_client.chat.completions
    assert len(completions.calls) == 2
    tool_messages = [m for m in completions.calls[1]["messages"] if m.get("role") == "tool"]
    assert len(tool_messages) == 2
    joined = " ".join(str(m.get("content", "")) for m in tool_messages)
    assert "transcript: nav rewritten" in joined
    assert "notebook: nav task logged" in joined
    assert _SINGLE_PASS_MARKER not in result
    assert "Both sources describe the nav rewrite." in result


@pytest.mark.asyncio
async def test_loop_unknown_source_error_still_briefs(
    monkeypatch: pytest.MonkeyPatch, _guard_single_pass: None
) -> None:
    """A retrieval miss (unknown source id) is fed back as a tool error, does
    not crash the loop, and the investigation is still produced."""
    monkeypatch.setattr(explorer_mod, "can_use_native_tool_calling", lambda **_k: True)
    fake_client = _FakeClient(
        [
            [_read_call("hs-ghost")],
            [_FakeChunk(_FakeDelta(content="The requested transcript was not readable."))],
        ]
    )
    monkeypatch.setattr(explorer_mod, "build_openai_client", lambda _cfg: fake_client)

    explorer = explorer_mod.ContextExplorer(language="en", prompts=_REAL_PROMPTS)
    ctx = _ctx(source_index={"hs-x": "transcript body"})

    result = await explorer.investigate(context=ctx, stream=StreamBus())

    assert "The requested transcript was not readable." in result
    assert _SINGLE_PASS_MARKER not in result
    completions = fake_client.chat.completions
    assert len(completions.calls) == 2
    tool_messages = [m for m in completions.calls[1]["messages"] if m.get("role") == "tool"]
    assert len(tool_messages) == 1


@pytest.mark.asyncio
async def test_loop_forced_finish_on_budget_exhaustion(
    monkeypatch: pytest.MonkeyPatch, _guard_single_pass: None
) -> None:
    """Rounds that keep calling tools are cut off at MAX_LOOP_ROUNDS: the last
    round runs tool-less with a forced-finish instruction and its text wins."""
    monkeypatch.setattr(explorer_mod, "can_use_native_tool_calling", lambda **_k: True)
    tool_round: list[Any] = [_read_call("hs-x")]
    rounds = [list(tool_round) for _ in range(explorer_mod.MAX_LOOP_ROUNDS - 1)]
    rounds.append([_FakeChunk(_FakeDelta(content="Investigation written under budget pressure."))])
    fake_client = _FakeClient(rounds)
    monkeypatch.setattr(explorer_mod, "build_openai_client", lambda _cfg: fake_client)

    explorer = explorer_mod.ContextExplorer(language="en", prompts=_REAL_PROMPTS)
    ctx = _ctx(source_index={"hs-x": "transcript body"})

    result = await explorer.investigate(context=ctx, stream=StreamBus())

    completions = fake_client.chat.completions
    assert len(completions.calls) == explorer_mod.MAX_LOOP_ROUNDS
    assert "Investigation written under budget pressure." in result
    assert _SINGLE_PASS_MARKER not in result
    # Every round before the last offered tools; the last round is tool-less.
    assert "tools" in completions.calls[0]
    assert "tools" not in completions.calls[-1]
    forced = completions.calls[-1]["messages"][-1]
    assert forced["role"] == "user"
    assert "Investigation budget reached" in str(forced["content"])
    for call in completions.calls[:-1]:
        assert "Investigation budget reached" not in str(call["messages"][-1].get("content", ""))


def test_read_source_schemas_pin_enum_and_lockdown() -> None:
    explorer = explorer_mod.ContextExplorer(language="en", prompts={})
    schemas = explorer._read_source_schemas({"hs-b": "2", "at-1": "3", "hs-a": "1"})

    read_schema = next(
        s
        for s in schemas
        if isinstance(s, dict) and s.get("function", {}).get("name") == "read_source"
    )
    properties = read_schema["function"]["parameters"]["properties"]
    assert properties["source_id"]["enum"] == ["at-1", "hs-a", "hs-b"]
    assert read_schema["function"]["parameters"]["additionalProperties"] is False


def test_augmenter_injects_backend_only_for_read_source() -> None:
    augment = explorer_mod.ContextExplorer._augmenter({"hs-x": "text"})
    ctx = _ctx()

    assert augment("read_source", {"source_id": "hs-x"}, ctx)["source_index"] == {"hs-x": "text"}
    other = augment("rag_search", {"query": "nav"}, ctx)
    assert other == {"query": "nav"}
    assert "source_index" not in other


# ---------------------------------------------------------------------------
# Usage accounting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_account_usage_records_estimated_chars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(explorer_mod, "can_use_native_tool_calling", lambda **_k: False)
    monkeypatch.setattr(explorer_mod, "llm_stream", _fake_stream(["briefing text"]))
    explorer = explorer_mod.ContextExplorer(language="en", prompts=_REAL_PROMPTS)
    usage = _UsageRecorder()
    ctx = _ctx(source_index={"hs-x": "transcript body"})

    await explorer.investigate(context=ctx, stream=StreamBus(), usage=usage)

    assert len(usage.calls) == 1
    assert usage.calls[0]["output_chars"] == len("briefing text")
    assert usage.calls[0]["input_chars"] > 0


@pytest.mark.asyncio
async def test_account_usage_skipped_for_blank_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(explorer_mod, "can_use_native_tool_calling", lambda **_k: False)
    monkeypatch.setattr(explorer_mod, "llm_stream", _fake_stream([""]))
    explorer = explorer_mod.ContextExplorer(language="en", prompts=_REAL_PROMPTS)
    usage = _UsageRecorder()
    ctx = _ctx(source_index={"hs-x": "transcript body"})

    assert await explorer.investigate(context=ctx, stream=StreamBus(), usage=usage) == ""
    assert usage.calls == []


@pytest.mark.asyncio
async def test_account_usage_survives_recorder_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(explorer_mod, "can_use_native_tool_calling", lambda **_k: False)
    monkeypatch.setattr(explorer_mod, "llm_stream", _fake_stream(["good briefing"]))
    explorer = explorer_mod.ContextExplorer(language="en", prompts=_REAL_PROMPTS)
    ctx = _ctx(source_index={"hs-x": "transcript body"})

    result = await explorer.investigate(context=ctx, stream=StreamBus(), usage=_ExplodingUsage())

    assert "good briefing" in result


# ---------------------------------------------------------------------------
# Stream parsing and small helpers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_llm_stream_parsing_and_kwargs() -> None:
    native_items = [{"type": "reasoning", "id": "rs_1"}]
    thinking_blocks = [{"type": "thinking", "thinking": "partial"}]
    fake_client = _FakeClient(
        [
            [
                _EmptyChoicesChunk(),  # no choices → skipped
                _FakeChunk(),  # delta None → skipped
                _FakeChunk(_FakeDelta(reasoning_content="planning")),
                _FakeChunk(_FakeDelta(content="Found ")),
                _FakeChunk(_FakeDelta(content="the answer.")),
                _FakeChunk(
                    _FakeDelta(),
                    provider_specific_fields={
                        "native_output_items": native_items + ["not-a-dict"],
                        "thinking_blocks": thinking_blocks + ["not-a-dict"],
                    },
                ),
            ]
        ]
    )
    explorer = explorer_mod.ContextExplorer(language="en", prompts={})
    bus = StreamBus()

    result = await explorer._call_llm(
        fake_client,
        [{"role": "user", "content": "hi"}],
        None,
        {"trace_kind": "llm_chunk"},
        bus,
        "s1",
    )

    assert result.text == "Found the answer."
    assert result.reasoning_content == "planning"
    assert result.response_output_items == native_items
    assert result.thinking_blocks == thinking_blocks
    assert result.output_chars == len("planning") + len("Found ") + len("the answer.")
    # Plain openai binding: no session threading, no tools when schemas are absent.
    kwargs = fake_client.chat.completions.calls[0]
    assert kwargs["model"] == explorer.model
    assert kwargs["stream"] is True
    assert "tools" not in kwargs
    assert "deeptutor_session_id" not in kwargs
    assert fake_client.chat.completions.last_stream.closed is True


def test_content_chars_language_and_translation_helpers() -> None:
    assert explorer_mod._content_chars({"content": "abc"}) == 3
    assert (
        explorer_mod._content_chars({"content": [{"text": "ab"}, {"text": "cd"}, {"nope": 1}]}) == 4
    )
    assert explorer_mod._content_chars({"content": None}) == 0
    assert explorer_mod._content_chars({}) == 0
    assert explorer_mod._content_chars({"content": 123}) == 0

    assert explorer_mod.ContextExplorer(language="zh-CN", prompts={}).language == "zh"
    assert explorer_mod.ContextExplorer(language=None, prompts={}).language == "en"
    assert explorer_mod.ContextExplorer(language="zh", prompts={})._kind_label("hs-1") == "对话记录"
    assert explorer_mod.ContextExplorer(language="zh", prompts={})._kind_label("other") == "来源"

    explorer = explorer_mod.ContextExplorer(
        language="en", prompts={"a": {"b": "  padded  "}, "c": {"d": {"nested": True}}}
    )
    assert explorer._t("a.b") == "padded"
    assert explorer._t("a.b.c", default="fallback") == "fallback"  # leaf is a dict
    assert explorer._t("missing.key", default="fallback") == "fallback"
