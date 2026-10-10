"""Focused tests for CodeGeneratorAgent prompt assembly, structured-output
validation retries, and LLM failure degradation (#AGEN-1344 coverage axis).

All LLM interaction is mocked; nothing here renders Manim or touches a
provider. Config plumbing is patched so the tests do not depend on a runtime
settings home.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from deeptutor.agents.math_animator.agents.code_generator_agent import (
    CodeGeneratorAgent,
)
from deeptutor.agents.math_animator.models import ConceptAnalysis, GeneratedCode, SceneDesign


def _agent(monkeypatch: pytest.MonkeyPatch) -> CodeGeneratorAgent:
    monkeypatch.setattr(
        "deeptutor.agents.base_agent.get_agent_params",
        lambda _module: {"temperature": 0.5, "max_tokens": 4096},
    )
    agent = CodeGeneratorAgent()
    agent.prompts = {
        "generate_system": "GENERATE-SYSTEM-PROMPT",
        "generate_user_template": (
            "{user_input}|{output_mode}|{duration_requirement}|{analysis_json}|{design_json}"
        ),
        "retry_system": "RETRY-SYSTEM-PROMPT",
        "retry_user_template": (
            "{user_input}|{output_mode}|{attempt}|{duration_requirement}"
            "|{error_message}|{current_code}"
        ),
    }
    monkeypatch.setattr(agent, "get_max_retries", lambda: 1)
    monkeypatch.setattr(agent, "get_max_tokens", lambda: 4096)

    calls: list[dict[str, object]] = []

    async def fake_stream(**kwargs) -> AsyncIterator[str]:
        calls.append(kwargs)
        yield '{"code": "from manim import Scene", "rationale": "ok"}'

    monkeypatch.setattr(agent, "stream_llm", fake_stream)
    agent._test_calls = calls  # type: ignore[attr-defined]
    return agent


def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(
        "deeptutor.agents.math_animator.agents.code_generator_agent.asyncio.sleep",
        fake_sleep,
    )


@pytest.mark.asyncio
async def test_generate_prompt_assembles_all_fields_and_duration_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)

    generated = await agent.generate(
        user_input="  Animate the chain rule  ",
        output_mode="gif",
        analysis=ConceptAnalysis(learning_goal="链式法则"),
        design=SceneDesign(title="Chain rule scene"),
        duration_target_seconds=7.5,
    )

    assert generated.code == "from manim import Scene"
    calls = agent._test_calls
    assert len(calls) == 1
    kwargs = calls[0]
    assert kwargs["system_prompt"] == "GENERATE-SYSTEM-PROMPT"
    assert kwargs["stage"] == "code_generation"
    assert kwargs["response_format"] == {"type": "json_object"}
    user_prompt = str(kwargs["user_prompt"])
    assert "Animate the chain rule" in user_prompt
    assert "  " not in user_prompt.split("|", 1)[0]
    assert user_prompt.startswith("Animate the chain rule|gif|")
    assert "用户明确目标时长约 7.5 秒" in user_prompt
    assert "链式法则" in user_prompt
    assert "Chain rule scene" in user_prompt
    trace = kwargs["trace_meta"]
    assert trace["phase"] == "code_generation"
    assert trace["call_kind"] == "math_code_generation"
    assert trace["trace_role"] == "generate"
    assert trace["structured_attempt"] == 1
    assert str(trace["call_id"]).startswith("math-codegen-")


@pytest.mark.asyncio
async def test_generate_prompt_without_duration_uses_standard_pace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)

    await agent.generate(
        user_input="Animate the chain rule",
        output_mode="video",
        analysis=ConceptAnalysis(),
        design=SceneDesign(),
        duration_target_seconds=None,
    )

    user_prompt = str(agent._test_calls[0]["user_prompt"])
    assert user_prompt.split("|")[2] == "用户未给出明确秒数时长，可按标准教学节奏生成。"
    assert "目标时长约" not in user_prompt


@pytest.mark.asyncio
async def test_generate_fails_fast_when_generation_prompts_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    agent.prompts = {}

    with pytest.raises(ValueError, match="generation prompts are not configured"):
        await agent.generate(
            user_input="Animate a proof",
            output_mode="video",
            analysis=ConceptAnalysis(),
            design=SceneDesign(),
        )
    assert agent._test_calls == []


@pytest.mark.asyncio
async def test_repair_prompt_assembles_error_context_and_attempt_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)

    generated = await agent.repair(
        user_input="Animate the chain rule",
        output_mode="video",
        current_code="x = 1  # broken",
        error_message="NameError: name 'foo' is not defined",
        attempt=2,
        duration_target_seconds=None,
    )

    assert generated.code == "from manim import Scene"
    kwargs = agent._test_calls[0]
    assert kwargs["system_prompt"] == "RETRY-SYSTEM-PROMPT"
    assert kwargs["stage"] == "code_retry"
    assert kwargs["reasoning_effort"] is None
    user_prompt = str(kwargs["user_prompt"])
    assert user_prompt.startswith("Animate the chain rule|video|2|")
    assert "无明确目标时长" in user_prompt
    assert "NameError: name 'foo' is not defined" in user_prompt
    assert "x = 1  # broken" in user_prompt
    trace = kwargs["trace_meta"]
    assert trace["phase"] == "code_retry"
    assert trace["call_kind"] == "math_code_retry"
    assert trace["trace_role"] == "repair"
    assert trace["attempt"] == 2
    assert trace["structured_attempt"] == 1
    assert str(trace["call_id"]).startswith("math-retry-")


@pytest.mark.asyncio
async def test_repair_fails_fast_when_retry_prompts_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    agent.prompts = {}

    with pytest.raises(ValueError, match="retry prompts are not configured"):
        await agent.repair(
            user_input="Animate a proof",
            output_mode="video",
            current_code="broken",
            error_message="SyntaxError",
            attempt=1,
        )
    assert agent._test_calls == []


@pytest.mark.asyncio
async def test_blank_code_field_in_valid_json_is_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_sleep(monkeypatch)
    agent = _agent(monkeypatch)

    async def blank_then_good(**kwargs) -> AsyncIterator[str]:
        agent._test_calls.append(kwargs)
        if len(agent._test_calls) == 1:
            yield '{"code": "   \\n ", "rationale": ""}'
        else:
            yield '{"code": "from manim import Scene", "rationale": "ok"}'

    monkeypatch.setattr(agent, "stream_llm", blank_then_good)

    generated = await agent.generate(
        user_input="Animate a proof",
        output_mode="video",
        analysis=ConceptAnalysis(),
        design=SceneDesign(),
    )

    assert generated.code == "from manim import Scene"
    assert len(agent._test_calls) == 2
    assert str(agent._test_calls[1]["user_prompt"]).endswith(
        "Return exactly one JSON object with a non-empty `code` field."
    )


@pytest.mark.asyncio
async def test_schema_type_violation_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_sleep(monkeypatch)
    agent = _agent(monkeypatch)

    async def wrong_type_then_good(**kwargs) -> AsyncIterator[str]:
        agent._test_calls.append(kwargs)
        if len(agent._test_calls) == 1:
            yield '{"code": 123}'
        else:
            yield '{"code": "x = 1", "rationale": "ok"}'

    monkeypatch.setattr(agent, "stream_llm", wrong_type_then_good)

    generated = await agent.generate(
        user_input="Animate a proof",
        output_mode="video",
        analysis=ConceptAnalysis(),
        design=SceneDesign(),
    )

    assert generated.code == "x = 1"
    assert len(agent._test_calls) == 2


@pytest.mark.asyncio
async def test_fenced_json_in_prose_is_accepted_first_try(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)

    async def fenced_stream(**kwargs) -> AsyncIterator[str]:
        agent._test_calls.append(kwargs)
        yield (
            "Here is your animation script:\n"
            "```json\n"
            '{"code": "from manim import Scene", "rationale": "ok"}\n'
            "```\n"
            "Enjoy!"
        )

    monkeypatch.setattr(agent, "stream_llm", fenced_stream)

    generated = await agent.generate(
        user_input="Animate a proof",
        output_mode="video",
        analysis=ConceptAnalysis(),
        design=SceneDesign(),
    )

    assert generated.code == "from manim import Scene"
    assert len(agent._test_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stream_error", [asyncio.TimeoutError, ConnectionError])
async def test_stream_failure_propagates_without_structured_retry(
    monkeypatch: pytest.MonkeyPatch,
    stream_error: type[BaseException],
) -> None:
    """Transport/timeout failures degrade to the caller, not to a fake retry.

    The structured-retry loop only covers a *successful* response with no
    usable code; a stream that raises must reach the pipeline's render retry
    untouched instead of being rewritten into GeneratedCodeOutputError.
    """

    _no_sleep(monkeypatch)
    agent = _agent(monkeypatch)

    async def failing_stream(**kwargs) -> AsyncIterator[str]:
        agent._test_calls.append(kwargs)
        raise stream_error
        yield ""  # pragma: no cover

    monkeypatch.setattr(agent, "stream_llm", failing_stream)

    with pytest.raises(stream_error):
        await asyncio.wait_for(
            agent.generate(
                user_input="Animate a proof",
                output_mode="video",
                analysis=ConceptAnalysis(),
                design=SceneDesign(),
            ),
            timeout=5,
        )
    assert len(agent._test_calls) == 1


@pytest.mark.asyncio
async def test_process_entrypoint_forwards_to_generate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _agent(monkeypatch)
    sentinel = GeneratedCode(code="from manim import Scene", rationale="ok")
    seen: dict[str, object] = {}

    async def fake_generate(**kwargs):
        seen.update(kwargs)
        return sentinel

    monkeypatch.setattr(agent, "generate", fake_generate)

    analysis = ConceptAnalysis(learning_goal="chain rule")
    design = SceneDesign(title="t")
    result = await agent.process(
        user_input="Animate a proof",
        output_mode="video",
        analysis=analysis,
        design=design,
    )

    assert result is sentinel
    assert seen["user_input"] == "Animate a proof"
    assert seen["output_mode"] == "video"
    assert seen["analysis"] is analysis
    assert seen["design"] is design
    assert seen["duration_target_seconds"] is None
