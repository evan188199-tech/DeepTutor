"""Focused coverage for the reasoning tool wrappers.

Covers ``deeptutor.tools.reason``, ``deeptutor.tools.brainstorm`` and the
``deeptutor.tools.solve_tool`` compatibility re-exports. Every LLM call is
driven by a fake stream, so no real service, config file, or network is used.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Callable

import pytest

import deeptutor.capabilities.solve.tools as solve_tools
from deeptutor.core.tool_protocol import BaseTool
import deeptutor.tools.brainstorm as brainstorm_mod
import deeptutor.tools.reason as reason_mod
import deeptutor.tools.solve_tool as solve_tool_mod


class FakeLLMStream:
    """Stand-in for ``deeptutor.services.llm.stream`` recording every call."""

    def __init__(self, chunks: list[str] | None = None, error: Exception | None = None) -> None:
        self.chunks = list(chunks or [])
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> AsyncIterator[str]:
        self.calls.append(kwargs)
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[str]:
        for chunk in self.chunks:
            yield chunk
        if self.error is not None:
            raise self.error


class FakeLLMConfig:
    def __init__(
        self,
        api_key: str = "cfg-key",
        base_url: str = "cfg-url",
        model: str = "cfg-model",
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model


def _config_not_configured() -> FakeLLMConfig:
    raise ValueError("no llm config in test")


def _default_token_kwargs(model: str, max_tokens: int) -> dict[str, int]:
    return {"max_tokens": max_tokens}


class LLMHarness:
    """Patches the function-level imports used by reason/brainstorm."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        chunks: list[str] | None = None,
        error: Exception | None = None,
        agent_params: dict[str, Any] | None = None,
        llm_config_getter: Callable[[], Any] = _config_not_configured,
        token_kwargs: Callable[[str, int], dict[str, int]] = _default_token_kwargs,
    ) -> None:
        self.stream = FakeLLMStream(chunks, error)
        self.agent_names: list[str] = []
        params = dict(agent_params or {})

        def _fake_agent_params(name: str) -> dict[str, Any]:
            self.agent_names.append(name)
            return dict(params)

        monkeypatch.setattr("deeptutor.services.llm.stream", self.stream)
        monkeypatch.setattr("deeptutor.services.llm.get_token_limit_kwargs", token_kwargs)
        monkeypatch.setattr("deeptutor.services.config.get_agent_params", _fake_agent_params)
        monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", llm_config_getter)


@pytest.fixture
def llm_harness(monkeypatch: pytest.MonkeyPatch) -> Callable[..., LLMHarness]:
    def _make(**kwargs: Any) -> LLMHarness:
        return LLMHarness(monkeypatch, **kwargs)

    return _make


# ---------------------------------------------------------------------------
# deeptutor.tools.reason
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reason_returns_query_answer_model_contract(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    llm_harness(chunks=["  Step A \n", " Step B  "])
    result = await reason_mod.reason(
        query="Derive the closed form",
        context="Original question",
        api_key="k",
        base_url="u",
        model="m1",
    )
    assert result == {
        "query": "Derive the closed form",
        "answer": "Step A \n Step B",
        "model": "m1",
    }


@pytest.mark.asyncio
async def test_reason_prompt_carries_context_and_focus_sections(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    harness = llm_harness(chunks=["ok"])
    await reason_mod.reason(
        query="the focus",
        context="the context",
        api_key="k",
        base_url="u",
        model="m1",
    )
    call = harness.stream.calls[0]
    assert call["prompt"] == "## Context\nthe context\n\n## Reasoning Focus\nthe focus"
    assert call["system_prompt"] == reason_mod._SYSTEM_PROMPT
    assert "deep reasoning" in call["system_prompt"]


@pytest.mark.asyncio
async def test_reason_prompt_without_context_omits_context_section(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    harness = llm_harness(chunks=["ok"])
    await reason_mod.reason(query="the focus", api_key="k", base_url="u", model="m1")
    assert harness.stream.calls[0]["prompt"] == "## Reasoning Focus\nthe focus"


@pytest.mark.asyncio
async def test_reason_forwards_model_and_credentials_to_llm_stream(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    harness = llm_harness(chunks=["ok"])
    await reason_mod.reason(
        query="q", api_key="explicit-key", base_url="https://explicit", model="explicit-model"
    )
    call = harness.stream.calls[0]
    assert call["model"] == "explicit-model"
    assert call["api_key"] == "explicit-key"
    assert call["base_url"] == "https://explicit"


@pytest.mark.asyncio
async def test_reason_falls_back_to_global_llm_config(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    cfg = FakeLLMConfig(api_key="cfg-key", base_url="cfg-url", model="cfg-model")
    harness = llm_harness(chunks=["x"], llm_config_getter=lambda: cfg)
    result = await reason_mod.reason(query="q")
    assert result["model"] == "cfg-model"
    call = harness.stream.calls[0]
    assert call["model"] == "cfg-model"
    assert call["api_key"] == "cfg-key"
    assert call["base_url"] == "cfg-url"


@pytest.mark.asyncio
async def test_reason_explicit_args_override_global_config(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    cfg = FakeLLMConfig(api_key="cfg-key", base_url="cfg-url", model="cfg-model")
    harness = llm_harness(chunks=["x"], llm_config_getter=lambda: cfg)
    result = await reason_mod.reason(query="q", api_key="k", base_url="u", model="m1")
    assert result["model"] == "m1"
    assert harness.stream.calls[0]["api_key"] == "k"


@pytest.mark.asyncio
async def test_reason_without_any_model_raises_before_llm_call(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    harness = llm_harness()
    with pytest.raises(ValueError, match="No model configured for reason tool"):
        await reason_mod.reason(query="q")
    assert harness.stream.calls == []


@pytest.mark.asyncio
async def test_reason_applies_solve_agent_param_defaults(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    harness = llm_harness(chunks=["x"], agent_params={"max_tokens": 111, "temperature": 0.25})
    await reason_mod.reason(query="q", api_key="k", base_url="u", model="m1")
    assert harness.agent_names == ["solve"]
    call = harness.stream.calls[0]
    assert call["temperature"] == 0.25
    assert call["max_tokens"] == 111


@pytest.mark.asyncio
async def test_reason_explicit_limits_override_agent_params(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    harness = llm_harness(chunks=["x"], agent_params={"max_tokens": 111, "temperature": 0.25})
    await reason_mod.reason(
        query="q", api_key="k", base_url="u", model="m1", max_tokens=222, temperature=0.5
    )
    call = harness.stream.calls[0]
    assert call["temperature"] == 0.5
    assert call["max_tokens"] == 222


@pytest.mark.asyncio
async def test_reason_forwards_resolved_token_limit_kwargs_verbatim(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    def _completion_tokens(model: str, max_tokens: int) -> dict[str, int]:
        return {"max_completion_tokens": max_tokens}

    harness = llm_harness(
        chunks=["x"], agent_params={"max_tokens": 111}, token_kwargs=_completion_tokens
    )
    await reason_mod.reason(query="q", api_key="k", base_url="u", model="gpt-5-mini")
    call = harness.stream.calls[0]
    assert call["max_completion_tokens"] == 111
    assert "max_tokens" not in call


@pytest.mark.asyncio
async def test_reason_empty_stream_yields_empty_answer(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    llm_harness(chunks=[])
    result = await reason_mod.reason(query="q", api_key="k", base_url="u", model="m1")
    assert result["answer"] == ""
    assert result["query"] == "q"


@pytest.mark.asyncio
async def test_reason_model_exception_propagates(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    harness = llm_harness(chunks=["partial"], error=RuntimeError("model exploded"))
    with pytest.raises(RuntimeError, match="model exploded"):
        await reason_mod.reason(query="q", api_key="k", base_url="u", model="m1")
    assert len(harness.stream.calls) == 1


# ---------------------------------------------------------------------------
# deeptutor.tools.brainstorm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_brainstorm_returns_topic_answer_model_contract(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    llm_harness(chunks=["# Brainstorm\n", "\n## 1. idea"])
    result = await brainstorm_mod.brainstorm(
        topic="  spaced topic  ",
        context="ctx",
        api_key="k",
        base_url="u",
        model="m1",
    )
    assert result == {
        "topic": "  spaced topic  ",
        "answer": "# Brainstorm\n\n## 1. idea",
        "model": "m1",
    }


@pytest.mark.asyncio
async def test_brainstorm_prompt_topics_first_then_context(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    harness = llm_harness(chunks=["x"])
    await brainstorm_mod.brainstorm(
        topic="  spaced topic  ", context="ctx", api_key="k", base_url="u", model="m1"
    )
    call = harness.stream.calls[0]
    assert call["prompt"] == "## Topic\nspaced topic\n\n## Context\nctx"
    assert call["system_prompt"] == brainstorm_mod._SYSTEM_PROMPT
    assert "brainstorming" in call["system_prompt"]


@pytest.mark.asyncio
async def test_brainstorm_whitespace_context_omits_context_section(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    harness = llm_harness(chunks=["x"])
    await brainstorm_mod.brainstorm(topic="t", context="   ", api_key="k", base_url="u", model="m1")
    assert harness.stream.calls[0]["prompt"] == "## Topic\nt"


@pytest.mark.asyncio
async def test_brainstorm_without_any_model_raises_before_llm_call(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    harness = llm_harness()
    with pytest.raises(ValueError, match="No model configured for brainstorm tool"):
        await brainstorm_mod.brainstorm(topic="t")
    assert harness.stream.calls == []


@pytest.mark.asyncio
async def test_brainstorm_applies_brainstorm_agent_param_defaults(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    harness = llm_harness(chunks=["x"], agent_params={"max_tokens": 2048, "temperature": 0.8})
    await brainstorm_mod.brainstorm(topic="t", api_key="k", base_url="u", model="m1")
    assert harness.agent_names == ["brainstorm"]
    call = harness.stream.calls[0]
    assert call["temperature"] == 0.8
    assert call["max_tokens"] == 2048


@pytest.mark.asyncio
async def test_brainstorm_explicit_limits_override_agent_params(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    harness = llm_harness(chunks=["x"], agent_params={"max_tokens": 2048, "temperature": 0.8})
    await brainstorm_mod.brainstorm(
        topic="t", api_key="k", base_url="u", model="m1", max_tokens=999, temperature=0.1
    )
    call = harness.stream.calls[0]
    assert call["temperature"] == 0.1
    assert call["max_tokens"] == 999


@pytest.mark.asyncio
async def test_brainstorm_falls_back_to_global_llm_config(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    cfg = FakeLLMConfig(api_key="cfg-key", base_url="cfg-url", model="cfg-model")
    harness = llm_harness(chunks=["x"], llm_config_getter=lambda: cfg)
    result = await brainstorm_mod.brainstorm(topic="t")
    assert result["model"] == "cfg-model"
    call = harness.stream.calls[0]
    assert call["api_key"] == "cfg-key"
    assert call["base_url"] == "cfg-url"


@pytest.mark.asyncio
async def test_brainstorm_empty_stream_yields_empty_answer(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    llm_harness(chunks=[])
    result = await brainstorm_mod.brainstorm(topic="t", api_key="k", base_url="u", model="m1")
    assert result["answer"] == ""
    assert result["topic"] == "t"


@pytest.mark.asyncio
async def test_brainstorm_model_exception_propagates(
    llm_harness: Callable[..., LLMHarness],
) -> None:
    harness = llm_harness(error=RuntimeError("brainstorm backend down"))
    with pytest.raises(RuntimeError, match="brainstorm backend down"):
        await brainstorm_mod.brainstorm(topic="t", api_key="k", base_url="u", model="m1")
    assert len(harness.stream.calls) == 1


# ---------------------------------------------------------------------------
# deeptutor.tools.solve_tool — compatibility re-exports
# ---------------------------------------------------------------------------


def test_solve_tool_reexports_are_capability_objects() -> None:
    for name in (
        "SOLVE_TOOL_NAMES",
        "SOLVE_TOOL_TYPES",
        "SolveFinishStepTool",
        "SolvePlanTool",
        "SolveReplanTool",
    ):
        assert getattr(solve_tool_mod, name) is getattr(solve_tools, name)


def test_solve_tool_all_matches_capability_module() -> None:
    assert solve_tool_mod.__all__ == solve_tools.__all__
    assert set(solve_tool_mod.__all__) == {
        "SOLVE_TOOL_NAMES",
        "SOLVE_TOOL_TYPES",
        "SolveFinishStepTool",
        "SolvePlanTool",
        "SolveReplanTool",
    }


def test_solve_tool_names_align_with_tool_definitions() -> None:
    assert solve_tool_mod.SOLVE_TOOL_NAMES == (
        "solve_plan",
        "solve_finish_step",
        "solve_replan",
    )
    assert solve_tool_mod.SOLVE_TOOL_NAMES == tuple(
        cls().get_definition().name for cls in solve_tool_mod.SOLVE_TOOL_TYPES
    )


def test_solve_tool_types_are_instantiable_base_tools() -> None:
    for cls in solve_tool_mod.SOLVE_TOOL_TYPES:
        assert issubclass(cls, BaseTool)
        tool = cls()
        assert tool.get_definition().name in solve_tool_mod.SOLVE_TOOL_NAMES
        assert tool.get_definition().description
