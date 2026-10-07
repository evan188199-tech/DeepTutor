"""ReviewAgent envelope contract: decision states and abnormal input.

The repair agent is only invoked after deterministic local validation has
failed, and its single job is to turn one concrete error into one
``ReviewResult`` envelope. Downstream consumers trust that envelope as-is —
``figure.py`` falls back to the original code only when ``optimized_code``
is empty — so the shape, the decision fields, and the failure mode on
unusable model output are all contract. These tests pin the contract with a
stubbed LLM and no server.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from pydantic import ValidationError

from deeptutor.agents.visualize.agents.review_agent import ReviewAgent
from deeptutor.agents.visualize.models import ReviewResult, VisualizationAnalysis

SEP = "\n@@DT@@\n"

FULL_REPLY = json.dumps(
    {
        "optimized_code": "<svg xmlns='http://www.w3.org/2000/svg'/>",
        "changed": True,
        "review_notes": "merged two svg roots",
    }
)


def _analysis() -> VisualizationAnalysis:
    return VisualizationAnalysis(
        render_type="svg",
        description="a small flowchart",
        data_description="three nodes",
        chart_type="",
        visual_elements=["boxes", "arrows"],
        rationale="reference map",
    )


def _agent(
    monkeypatch: pytest.MonkeyPatch, reply: str
) -> tuple[ReviewAgent, list[dict[str, Any]]]:
    agent = ReviewAgent()
    agent.prompts = {
        "repair_system": "Repair the code.",
        "repair_user_template": SEP.join(
            (
                "{user_input}",
                "{render_type}",
                "{error}",
                "{code}",
                "{analysis_json}",
            )
        ),
    }
    calls: list[dict[str, Any]] = []

    async def fake_stream_llm(**kwargs: Any) -> AsyncIterator[str]:
        calls.append(kwargs)
        yield reply

    monkeypatch.setattr(agent, "stream_llm", fake_stream_llm)
    return agent, calls


async def _process(agent: ReviewAgent) -> ReviewResult:
    return await agent.process(
        user_input="draw a flow",
        analysis=_analysis(),
        code="<svg broken",
        error="SyntaxError: mismatched tag",
    )


@pytest.mark.asyncio
async def test_full_envelope_roundtrip_and_llm_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, calls = _agent(monkeypatch, FULL_REPLY)

    result = await _process(agent)

    assert isinstance(result, ReviewResult)
    assert result.optimized_code == "<svg xmlns='http://www.w3.org/2000/svg'/>"
    assert result.changed is True
    assert result.review_notes == "merged two svg roots"

    assert len(calls) == 1
    call = calls[0]
    assert call["system_prompt"] == "Repair the code."
    assert call["response_format"] == {"type": "json_object"}
    assert call["stage"] == "reviewing"
    assert call["trace_meta"]["call_kind"] == "viz_code_repair"
    assert call["trace_meta"]["trace_role"] == "review"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "expected_code", "expected_changed", "expected_notes"),
    [
        pytest.param(
            FULL_REPLY,
            "<svg xmlns='http://www.w3.org/2000/svg'/>",
            True,
            "merged two svg roots",
            id="repaired-changed",
        ),
        pytest.param(
            json.dumps({"optimized_code": "<svg fixed/>"}),
            "<svg fixed/>",
            False,
            "",
            id="passed-through-unchanged-defaults",
        ),
        pytest.param(
            f"<think>only the broken tag matters</think>\n{FULL_REPLY}",
            "<svg xmlns='http://www.w3.org/2000/svg'/>",
            True,
            "merged two svg roots",
            id="reasoning-prelude-stripped",
        ),
        pytest.param(
            f"Here is the repair:\n```json\n{FULL_REPLY}\n```",
            "<svg xmlns='http://www.w3.org/2000/svg'/>",
            True,
            "merged two svg roots",
            id="fenced-json-extracted",
        ),
        pytest.param(
            json.dumps(
                {"optimized_code": "", "changed": False, "review_notes": "cannot fix"}
            ),
            "",
            False,
            "cannot fix",
            id="empty-code-is-a-valid-envelope",
        ),
    ],
)
async def test_envelope_decision_states(
    monkeypatch: pytest.MonkeyPatch,
    reply: str,
    expected_code: str,
    expected_changed: bool,
    expected_notes: str,
) -> None:
    """The envelope survives the reply transports models actually use.

    ``changed``/``review_notes`` default when absent, and an empty
    ``optimized_code`` stays verbatim so the caller can fall back to the
    original code.
    """

    agent, _ = _agent(monkeypatch, reply)

    result = await _process(agent)

    assert result.optimized_code == expected_code
    assert result.changed is expected_changed
    assert result.review_notes == expected_notes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_input", "expected_error_field"),
    [
        pytest.param(
            "  SyntaxError: mismatched tag  ",
            "SyntaxError: mismatched tag",
            id="error-stripped",
        ),
        pytest.param("", "(unspecified)", id="empty-error-placeholder"),
        pytest.param("   ", "(unspecified)", id="whitespace-error-placeholder"),
    ],
)
async def test_user_prompt_substitution(
    monkeypatch: pytest.MonkeyPatch,
    error_input: str,
    expected_error_field: str,
) -> None:
    agent, calls = _agent(monkeypatch, FULL_REPLY)

    await agent.process(
        user_input="  draw a flow  ",
        analysis=_analysis(),
        code="<svg broken",
        error=error_input,
    )

    fields = calls[0]["user_prompt"].split(SEP)
    assert fields[0] == "draw a flow"
    assert fields[1] == "svg"
    assert fields[2] == expected_error_field
    assert fields[3] == "<svg broken"
    assert json.loads(fields[4]) == _analysis().model_dump()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompts",
    [
        pytest.param({}, id="no-prompts"),
        pytest.param({"repair_user_template": "{error}"}, id="missing-system"),
        pytest.param({"repair_system": "Repair."}, id="missing-user-template"),
        pytest.param(
            {"repair_system": "", "repair_user_template": "{error}"},
            id="empty-system",
        ),
    ],
)
async def test_missing_repair_prompts_are_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch, prompts: dict[str, str]
) -> None:
    agent, _ = _agent(monkeypatch, FULL_REPLY)
    agent.prompts = prompts

    with pytest.raises(ValueError, match="repair prompts are not configured"):
        await _process(agent)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "error_type"),
    [
        pytest.param("", ValidationError, id="empty-reply"),
        pytest.param("{}", ValidationError, id="empty-object"),
        pytest.param(
            '{"changed": true, "review_notes": "no code"}',
            ValidationError,
            id="missing-optimized-code",
        ),
        pytest.param(
            "I cannot repair this code.",
            json.JSONDecodeError,
            id="prose-without-json",
        ),
    ],
)
async def test_unusable_llm_output_raises_instead_of_guessing(
    monkeypatch: pytest.MonkeyPatch, reply: str, error_type: type[Exception]
) -> None:
    agent, _ = _agent(monkeypatch, reply)

    with pytest.raises(error_type) as excinfo:
        await _process(agent)

    if error_type is ValidationError:
        assert "optimized_code" in str(excinfo.value)
