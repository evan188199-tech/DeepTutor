"""EditAgent behavior contract: instruction → edit-operation parsing and failure branches.

Scope note: the co-writer *router* contract (CRUD, 4xx payloads, export
failures, history limits) is locked by ``tests/api/test_co_writer.py``; the
DOCX converter has its own suite. This file covers the ``EditAgent`` itself —
how an instruction/action pair is assembled into the edit operation, how RAG /
web / PageIndex context sources are chosen and degraded, and the automark
post-processing rule — with the LLM seam stubbed. No network, no external
service.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any, AsyncIterator

import pytest

from deeptutor.co_writer import edit_agent
from deeptutor.co_writer.edit_agent import EditAgent

_OPERATION_ID_RE = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{6}$")


class _StubPathService:
    """Route co-writer state under a per-test directory."""

    def __init__(self, root: Path):
        self.root = root

    def get_co_writer_dir(self) -> Path:
        return self.root

    def get_co_writer_history_file(self) -> Path:
        return self.root / "history.json"

    def get_co_writer_tool_calls_dir(self) -> Path:
        return self.root / "tool_calls"


@pytest.fixture
def agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> EditAgent:
    """A real EditAgent whose on-disk state is redirected to tmp."""
    stub = _StubPathService(tmp_path)
    monkeypatch.setattr(edit_agent, "get_path_service", lambda: stub)
    return EditAgent(language="en")


def _stub_stream(agent: EditAgent, chunks: list[str]) -> dict[str, Any]:
    """Replace the LLM seam on the instance; capture the call kwargs."""
    captured: dict[str, Any] = {}

    async def _stream(**kwargs: Any) -> AsyncIterator[str]:
        captured.update(kwargs)
        for chunk in chunks:
            yield chunk

    agent.stream_llm = _stream  # type: ignore[method-assign]
    return captured


def _stub_stream_never(agent: EditAgent) -> None:
    async def _stream(**_kwargs: Any) -> AsyncIterator[str]:
        raise AssertionError("this path must not call the plain LLM stream")
        yield ""  # pragma: no cover — makes this an async generator

    agent.stream_llm = _stream  # type: ignore[method-assign]


def _load_history(agent: EditAgent) -> list[dict[str, Any]]:
    return edit_agent.load_history()


def _tool_call_files() -> list[Path]:
    """Files under the (possibly not-yet-created) tool-calls dir."""
    tool_dir = edit_agent.tool_calls_dir()
    if not tool_dir.exists():
        return []
    return sorted(tool_dir.iterdir())


# ── process(): instruction → edit operation ──────────────────────────────


@pytest.mark.asyncio
async def test_plain_edit_returns_edited_text_and_operation_id(agent: EditAgent) -> None:
    _stub_stream(agent, ["Edited: ", "formal text"])

    result = await agent.process("draft body", "make it formal")

    assert set(result) == {"edited_text", "operation_id"}
    assert result["edited_text"] == "Edited: formal text"
    assert _OPERATION_ID_RE.match(result["operation_id"])

    history = _load_history(agent)
    assert len(history) == 1
    record = history[0]
    assert record["id"] == result["operation_id"]
    assert record["action"] == "rewrite"
    assert record["source"] is None
    assert record["kb_name"] is None
    assert record["input"] == {"original_text": "draft body", "instruction": "make it formal"}
    assert record["output"] == {"edited_text": "Edited: formal text"}
    assert record["tool_call_file"] is None
    assert record["model"] == agent.get_model()


@pytest.mark.asyncio
async def test_user_prompt_carries_instruction_action_and_target_text(
    agent: EditAgent,
) -> None:
    captured = _stub_stream(agent, ["out"])

    await agent.process("the target text", "shorten the intro", action="shorten")

    assert captured["stage"] == "edit_shorten"
    assert "expert editor" in captured["system_prompt"]
    assert "Shorten the following text" in captured["user_prompt"]
    assert "shorten the intro" in captured["user_prompt"]
    assert "the target text" in captured["user_prompt"]
    assert "Output only the edited text" in captured["user_prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "verb"),
    [("rewrite", "Rewrite"), ("shorten", "Shorten"), ("expand", "Expand")],
)
async def test_action_verb_mapping(agent: EditAgent, action: str, verb: str) -> None:
    captured = _stub_stream(agent, ["out"])

    await agent.process("text", "instruction", action=action)  # type: ignore[arg-type]

    assert captured["user_prompt"].startswith(f"{verb} the following text")
    assert captured["stage"] == f"edit_{action}"


@pytest.mark.asyncio
async def test_unknown_action_falls_back_to_rewrite_verb(agent: EditAgent) -> None:
    captured = _stub_stream(agent, ["out"])

    await agent.process("text", "polish this", action="polish")  # type: ignore[arg-type]

    assert captured["user_prompt"].startswith("Rewrite the following text")


@pytest.mark.asyncio
async def test_thinking_tags_stripped_from_streamed_output(agent: EditAgent) -> None:
    _stub_stream(agent, ["<think>hidden scratchpad</think>", "visible edit"])

    result = await agent.process("text", "instruction")

    assert result["edited_text"] == "visible edit"


# ── process(): context sources (rag / web / pageindex) ───────────────────


@pytest.mark.asyncio
async def test_rag_context_embedded_in_prompt_and_tool_call_saved(
    agent: EditAgent, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(edit_agent, "is_pageindex_kb", lambda _kb: False)
    calls: list[dict[str, Any]] = []

    async def _rag_search(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"answer": "KB SAYS X"}

    monkeypatch.setattr(edit_agent, "rag_search", _rag_search)
    _stub_stream(agent, ["out"])

    await agent.process("text", "cite the source", source="rag", kb_name="my-kb")

    assert calls == [{"query": "cite the source", "kb_name": "my-kb", "only_need_context": True}]
    history = _load_history(agent)
    record = history[0]
    assert record["source"] == "rag"
    assert record["kb_name"] == "my-kb"
    assert record["tool_call_file"] is not None
    assert Path(record["tool_call_file"]).exists()
    saved = json.loads(Path(record["tool_call_file"]).read_text(encoding="utf-8"))
    assert saved["type"] == "rag"
    assert saved["context"] == "KB SAYS X"


@pytest.mark.asyncio
async def test_rag_context_text_reaches_the_llm_prompt(
    agent: EditAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(edit_agent, "is_pageindex_kb", lambda _kb: False)

    async def _rag_search(**_kwargs: Any) -> dict[str, Any]:
        return {"answer": "KB SAYS X"}

    monkeypatch.setattr(edit_agent, "rag_search", _rag_search)
    captured = _stub_stream(agent, ["out"])

    await agent.process("text", "instruction", source="rag", kb_name="my-kb")

    assert "Reference Context (knowledge base)" in captured["user_prompt"]
    assert "KB SAYS X" in captured["user_prompt"]


@pytest.mark.asyncio
async def test_rag_empty_context_degrades_to_plain_edit(
    agent: EditAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(edit_agent, "is_pageindex_kb", lambda _kb: False)

    async def _rag_search(**_kwargs: Any) -> dict[str, Any]:
        return {"answer": ""}

    monkeypatch.setattr(edit_agent, "rag_search", _rag_search)
    captured = _stub_stream(agent, ["out"])

    result = await agent.process("text", "instruction", source="rag", kb_name="my-kb")

    assert result["edited_text"] == "out"
    assert "Reference Context" not in captured["user_prompt"]
    # Empty context degrades the *source*, but the prefetch attempt is still
    # auditable: the rag tool-call file is saved and referenced.
    record = _load_history(agent)[0]
    assert record["source"] is None
    assert record["tool_call_file"] is not None
    saved = json.loads(Path(record["tool_call_file"]).read_text(encoding="utf-8"))
    assert saved["context"] == ""
    assert len(_tool_call_files()) == 1


@pytest.mark.asyncio
async def test_rag_failure_degrades_to_plain_edit(
    agent: EditAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(edit_agent, "is_pageindex_kb", lambda _kb: False)

    async def _boom(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("rag provider down")

    monkeypatch.setattr(edit_agent, "rag_search", _boom)
    _stub_stream(agent, ["plain edit"])

    result = await agent.process("text", "instruction", source="rag", kb_name="my-kb")

    assert result["edited_text"] == "plain edit"
    record = _load_history(agent)[0]
    assert record["source"] is None
    assert record["tool_call_file"] is None


@pytest.mark.asyncio
async def test_pageindex_kb_routes_through_reasoning_loop(
    agent: EditAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(edit_agent, "is_pageindex_kb", lambda kb: kb == "pi-kb")
    reading_calls: list[dict[str, Any]] = []

    async def _read(**kwargs: Any) -> SimpleNamespace:
        reading_calls.append(kwargs)
        return SimpleNamespace(text="<think>scratch</think>pageindex edit", sources=[{"n": 1}])

    import deeptutor.services.rag.pipelines.pageindex.reasoning as reasoning

    monkeypatch.setattr(reasoning, "read_pageindex_with_agent", _read)
    _stub_stream_never(agent)

    result = await agent.process("text", "instruction", source="rag", kb_name="pi-kb")

    assert result["edited_text"] == "pageindex edit"
    assert reading_calls[0]["kb_name"] == "pi-kb"
    assert reading_calls[0]["source"] == "co_writer"
    assert reading_calls[0]["stage"] == "edit_rewrite"
    assert "instruction" in reading_calls[0]["user_prompt"]

    record = _load_history(agent)[0]
    assert record["tool_call_file"] is not None
    saved = json.loads(Path(record["tool_call_file"]).read_text(encoding="utf-8"))
    assert saved["type"] == "pageindex"
    assert saved["sources"] == [{"n": 1}]


# ── gather_context(): failure branches degrade to a plain edit ───────────


@pytest.mark.asyncio
async def test_gather_context_rag_tool_disabled_returns_empty(
    agent: EditAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent.enabled_tools = ["web_search"]
    failed = False

    async def _rag_search(**_kwargs: Any) -> dict[str, Any]:
        nonlocal failed
        failed = True
        return {}

    monkeypatch.setattr(edit_agent, "rag_search", _rag_search)

    assert await agent.gather_context(source="rag", query="q", kb_name="kb") == ("", None)
    assert not failed


@pytest.mark.asyncio
async def test_gather_context_rag_without_kb_name_returns_empty(
    agent: EditAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = False

    async def _rag_search(**_kwargs: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(edit_agent, "rag_search", _rag_search)

    assert await agent.gather_context(source="rag", query="q", kb_name=None) == ("", None)
    assert not called


@pytest.mark.asyncio
async def test_gather_context_rag_failure_returns_empty(
    agent: EditAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("down")

    monkeypatch.setattr(edit_agent, "rag_search", _boom)

    assert await agent.gather_context(source="rag", query="q", kb_name="kb") == ("", None)
    assert _tool_call_files() == []


@pytest.mark.asyncio
async def test_gather_context_web_tool_disabled_returns_empty(agent: EditAgent) -> None:
    agent.enabled_tools = ["rag"]

    assert await agent.gather_context(source="web", query="q") == ("", None)


@pytest.mark.asyncio
async def test_gather_context_web_failure_returns_empty(
    agent: EditAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_query: str) -> dict[str, Any]:
        raise RuntimeError("web down")

    monkeypatch.setattr(edit_agent, "web_search", _boom)

    assert await agent.gather_context(source="web", query="q") == ("", None)
    assert _tool_call_files() == []


@pytest.mark.asyncio
async def test_gather_context_web_success_saves_tool_call_with_citations(
    agent: EditAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    queries: list[str] = []

    def _web_search(query: str) -> dict[str, Any]:
        queries.append(query)
        return {"answer": "WEB ANSWER", "citations": ["c1"], "usage": {"n": 1}}

    monkeypatch.setattr(edit_agent, "web_search", _web_search)

    context, tool_call_file = await agent.gather_context(source="web", query="q1")

    assert context == "WEB ANSWER"
    assert queries == ["q1"]
    assert tool_call_file is not None
    saved = json.loads(Path(tool_call_file).read_text(encoding="utf-8"))
    assert saved["type"] == "web_search"
    assert saved["citations"] == ["c1"]


# ── auto_mark(): annotation post-processing ──────────────────────────────


@pytest.mark.asyncio
async def test_auto_mark_streams_with_stage_and_records_history(
    agent: EditAgent,
) -> None:
    captured = _stub_stream(agent, ["【marked】 text"])

    result = await agent.auto_mark("plain text")

    assert result["marked_text"] == "【marked】 text"
    assert _OPERATION_ID_RE.match(result["operation_id"])
    assert captured["stage"] == "auto_mark"
    assert "plain text" in captured["user_prompt"]

    record = _load_history(agent)[0]
    assert record["action"] == "automark"
    assert record["id"] == result["operation_id"]
    assert record["input"] == {"original_text": "plain text", "instruction": "AI Auto Mark"}
    assert record["output"] == {"edited_text": "【marked】 text"}
    assert record["tool_call_file"] is None


@pytest.mark.asyncio
async def test_auto_mark_rough_notation_markup_falls_back_to_original(
    agent: EditAgent,
) -> None:
    original = "Deep learning uses neural networks."
    _stub_stream(agent, ['<span data-rough-notation="circle">Deep learning</span>'])

    result = await agent.auto_mark(original)

    assert result["marked_text"] == original
    # The fallback (not the unsupported markup) is what history records.
    assert _load_history(agent)[0]["output"] == {"edited_text": original}


# ── prompt-building helpers ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("en", "(no external reference tools enabled)"),
        ("zh", "（当前未启用外部参考工具）"),
    ],
)
def test_available_tools_text_fallback_when_no_known_tool_enabled(language: str, expected: str):
    # enabled_tools=[] resets to the default ["rag", "web_search"]; only a
    # list with no known names reaches the localized "no tools" fallback.
    agent = EditAgent(language=language, enabled_tools=["unknown_tool"])

    assert agent._build_available_tools_text() == expected


def test_available_tools_text_filters_unknown_tool_names(agent: EditAgent):
    agent.enabled_tools = ["rag", "banana", "web_search"]

    class _RecordingRegistry:
        def __init__(self) -> None:
            self.names: list[str] | None = None

        def build_prompt_text(
            self, names: list[str], format: str = "list", language: str = "en", **_opts: Any
        ) -> str:
            self.names = list(names)
            return "TOOL HINTS"

    registry = _RecordingRegistry()
    agent._tool_registry = registry  # type: ignore[assignment]

    assert agent._build_available_tools_text() == "TOOL HINTS"
    assert registry.names == ["rag", "web_search"]


@pytest.mark.parametrize(
    ("language", "source", "expected"),
    [
        ("en", "rag", "knowledge base"),
        ("en", "web", "web search"),
        ("en", None, "reference"),
        ("zh", "rag", "知识库"),
        ("zh", "web", "网页搜索"),
        ("zh", None, "参考资料"),
    ],
)
def test_source_label_localization(language: str, source: str | None, expected: str):
    agent = EditAgent(language=language)

    assert agent._get_source_label(source) == expected  # type: ignore[arg-type]
