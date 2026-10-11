"""Unit tests for the PageIndex reasoning loop.

Verifies the calling contract `read_pageindex_with_agent` has with the shared
agentic loop, the result-parsing boundaries, and a full FINISH round against a
scripted fake LLM transport — no network, no real PageIndex tools.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEventType
from deeptutor.core.tool_protocol import ToolDefinition, ToolResult
from deeptutor.runtime.stream_bus import StreamBus
from deeptutor.services.rag.pipelines.pageindex import reasoning as reasoning_mod
from deeptutor.services.rag.pipelines.pageindex.reasoning import (
    PageIndexReadingResult,
    read_pageindex_with_agent,
)


class _FakeTool:
    def __init__(self, name: str = "pageindex_oss_get_page_content") -> None:
        self.name = name

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description="Read pages",
            raw_parameters={"type": "object", "properties": {"doc_name": {"type": "string"}}},
        )

    async def execute(self, **_kwargs: Any) -> ToolResult:  # pragma: no cover - dispatch stubbed
        return ToolResult(content="")


def _tool_context(documents: dict[str, str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        provider="pageindex-oss",
        registry=object(),
        tools=(_FakeTool(),),
        instructions="Inspect structure, then read pages.",
        documents={"manual.pdf": "pi-1"} if documents is None else documents,
    )


def _llm(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "binding": "openai",
        "model": "gpt-test",
        "api_key": "k",
        "base_url": "u",
        "api_version": None,
        "extra_headers": None,
        "reasoning_effort": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _patch_llm(monkeypatch: pytest.MonkeyPatch, llm: SimpleNamespace) -> None:
    monkeypatch.setattr(reasoning_mod, "get_llm_config", lambda: llm)
    monkeypatch.setattr(reasoning_mod, "can_use_native_tool_calling", lambda **_kw: True)


def _patch_tool_context(
    monkeypatch: pytest.MonkeyPatch, context: SimpleNamespace | None
) -> None:
    monkeypatch.setattr(reasoning_mod, "get_tool_registry", lambda: object())

    async def _build(kb_name: str, *, base_registry: Any):
        return context

    monkeypatch.setattr(reasoning_mod, "build_pageindex_tool_context", _build)


def _run(**kwargs: Any):
    defaults: dict[str, Any] = {
        "kb_name": "kb",
        "system_prompt": "Answer from the KB.",
        "user_prompt": "What does page 3 say?",
        "source": "test",
        "stage": "answer",
    }
    defaults.update(kwargs)
    return read_pageindex_with_agent(**defaults)


def _content_chunk(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=None))]
    )


async def _async_stream(chunks: list[SimpleNamespace]):
    for chunk in chunks:
        yield chunk


class _ScriptedClient:
    """Fake OpenAI transport replaying canned streaming rounds."""

    def __init__(self, scripts: list[list[SimpleNamespace]]) -> None:
        self._scripts = list(scripts)

        class _Completions:
            async def create(self, **_kwargs: Any):
                if not self._parent._scripts:
                    raise RuntimeError("scripted client exhausted")
                return _async_stream(self._parent._scripts.pop(0))

        class _Chat:
            def __init__(self, parent: "_ScriptedClient") -> None:
                self.completions = _Completions()
                self.completions._parent = parent  # type: ignore[attr-defined]

        self.chat = _Chat(self)


def test_requires_native_tool_calling(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_llm(monkeypatch, _llm())
    monkeypatch.setattr(reasoning_mod, "can_use_native_tool_calling", lambda **_kw: False)

    with pytest.raises(RuntimeError, match="tool calling"):
        asyncio.run(_run())


def test_rejects_non_pageindex_kb(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_llm(monkeypatch, _llm())
    _patch_tool_context(monkeypatch, None)

    with pytest.raises(ValueError, match="not a PageIndex"):
        asyncio.run(_run())


def test_loop_contract_and_result_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_llm(monkeypatch, _llm())
    context = _tool_context()
    _patch_tool_context(monkeypatch, context)
    captured: dict[str, Any] = {}

    async def _loop(**kwargs: Any):
        captured.update(kwargs)
        return SimpleNamespace(
            final_text="  grounded answer \n", sources=[{"type": "pageindex"}]
        )

    monkeypatch.setattr(reasoning_mod, "run_agentic_loop", _loop)
    client = object()
    monkeypatch.setattr(reasoning_mod, "build_openai_client", lambda _config: client)
    stream = StreamBus()

    result = asyncio.run(_run(stream=stream))

    # Calling contract towards the shared agentic loop.
    assert captured["client"] is client
    assert captured["model"] == "gpt-test"
    assert captured["binding"] == "openai"
    assert captured["max_iterations"] == 8
    assert captured["source"] == "test"
    assert captured["stage"] == "answer"
    assert captured["stream"] is stream
    assert list(captured["protocol"].allowed) == ["THINK", "TOOL", "FINISH"]
    assert captured["tool_schemas"] == [context.tools[0].get_definition().to_openai_schema()]
    system, user = captured["initial_messages"]
    assert user == {"role": "user", "content": "What does page 3 say?"}
    assert "manual.pdf (doc_id: pi-1)" in system["content"]
    assert "pageindex_oss_get_page_content" in system["content"]
    assert "Inspect structure, then read pages." in system["content"]
    assert "Answer from the KB." in system["content"]

    # Result parsing boundaries.
    assert isinstance(result, PageIndexReadingResult)
    assert result.text == "grounded answer"
    assert result.sources == [{"type": "pageindex"}]
    assert result.tool_context is context
    source_events = [e for e in stream._history if e.type is StreamEventType.SOURCES]
    assert source_events
    assert source_events[0].metadata["sources"] == [{"type": "pageindex"}]


def test_empty_kb_lists_placeholder_and_returns_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_llm(monkeypatch, _llm())
    _patch_tool_context(monkeypatch, _tool_context(documents={}))
    captured: dict[str, Any] = {}

    async def _loop(**kwargs: Any):
        captured.update(kwargs)
        return SimpleNamespace(final_text=None, sources=[])

    monkeypatch.setattr(reasoning_mod, "run_agentic_loop", _loop)
    monkeypatch.setattr(reasoning_mod, "build_openai_client", lambda _config: object())

    result = asyncio.run(_run())

    assert "(no indexed documents)" in captured["initial_messages"][0]["content"]
    assert result.text == ""
    assert result.sources == []


def test_finishing_round_flows_through_the_real_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_llm(monkeypatch, _llm())
    _patch_tool_context(monkeypatch, _tool_context())
    scripted = _ScriptedClient(
        [[_content_chunk("``FINISH``\nGrounded: page 3 says hello.")]]
    )
    monkeypatch.setattr(reasoning_mod, "build_openai_client", lambda _config: scripted)
    stream = StreamBus()

    result = asyncio.run(_run(stream=stream))

    assert result.text == "Grounded: page 3 says hello."
    assert result.sources == []
    assert result.tool_context.documents == {"manual.pdf": "pi-1"}


def test_force_finalize_appends_budget_message(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_llm(monkeypatch, _llm())
    host = reasoning_mod._ReadingHost(
        tool_context=_tool_context(),
        context=UnifiedContext(user_message="q", knowledge_bases=["kb"]),
        stream=StreamBus(),
        client=object(),
        model="gpt-test",
        binding="openai",
        reasoning_effort=None,
        source="test",
        stage="answer",
    )
    captured: dict[str, Any] = {}

    async def _step(**kwargs: Any):
        captured.update(kwargs)
        return SimpleNamespace(text="best effort", label="FINISH")

    monkeypatch.setattr(reasoning_mod, "run_labeled_step", _step)
    messages: list[dict[str, Any]] = [{"role": "system", "content": "s"}]

    text, finished, extra = asyncio.run(
        host.force_finalize(messages=messages, start_iteration=5)
    )

    assert (text, finished, extra) == ("best effort", True, 1)
    assert messages[-1]["role"] == "user"
    assert "Tool budget exhausted" in messages[-1]["content"]
    assert captured["allowed_labels"] == ("FINISH",)
    assert captured["tool_schemas"] is None

    assert "THINK" in host.protocol_repair_message("bad label")
    assert "retrying" in host.protocol_retry_notice()
