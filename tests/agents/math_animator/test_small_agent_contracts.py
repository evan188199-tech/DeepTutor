"""Output-parsing and degradation contracts for the three small math-animator stages.

Covers :class:`ConceptAnalysisAgent`, :class:`ConceptDesignAgent` and
:class:`SummaryAgent` with a fake LLM: what a streamed answer must look like
to be accepted, and what happens when it is missing, mis-shaped, or the
provider fails. No network access.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
from typing import Any

import pytest

from deeptutor.agents.math_animator.agents.concept_analysis_agent import (
    ConceptAnalysisAgent,
)
from deeptutor.agents.math_animator.agents.concept_design_agent import (
    ConceptDesignAgent,
)
from deeptutor.agents.math_animator.agents.summary_agent import SummaryAgent
from deeptutor.agents.math_animator.models import (
    ConceptAnalysis,
    RenderResult,
    SceneDesign,
)
from deeptutor.core.context import Attachment

ANALYSIS_TEMPLATE = (
    "input={user_input} history={history_context} mode={output_mode} "
    "style={style_hint} refs={reference_count}"
)
DESIGN_TEMPLATE = (
    "input={user_input} mode={output_mode} style={style_hint}\nanalysis={analysis_json}"
)
SUMMARY_TEMPLATE = (
    "input={user_input} mode={output_mode}\n"
    "analysis={analysis_json}\ndesign={design_json}\nrender={render_json}"
)


def _recording_stream(
    calls: list[dict[str, Any]],
    behavior,
):
    async def fake_stream(**kwargs) -> AsyncIterator[str]:
        calls.append(kwargs)
        result = behavior(len(calls), kwargs)
        if isinstance(result, BaseException):
            raise result
        yield result

    return fake_stream


def _analysis_call(agent: ConceptAnalysisAgent, attachments: list[Attachment]):
    return agent.process(
        user_input="  Explain a circle  ",
        history_context="",
        output_mode="video",
        style_hint="",
        attachments=attachments,
    )


def _design_call(agent: ConceptDesignAgent):
    return agent.process(
        user_input="Explain a circle",
        output_mode="video",
        analysis=ConceptAnalysis(learning_goal="understand a circle"),
        style_hint="",
    )


def _summary_call(agent: SummaryAgent):
    return agent.process(
        user_input="Explain a circle",
        output_mode="video",
        analysis=ConceptAnalysis(learning_goal="understand a circle"),
        design=SceneDesign(title="Circle", scene_outline=["draw a circle"]),
        render_result=RenderResult(output_mode="video", quality="good"),
    )


# ---------------------------------------------------------------------------
# ConceptAnalysisAgent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analysis_parses_fenced_payload_counts_image_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = ConceptAnalysisAgent()
    agent.prompts = {"system": "Analyze.", "user_template": ANALYSIS_TEMPLATE}
    answer = (
        "```json\n"
        '{"learning_goal":"understand a circle","math_focus":["radius"],'
        '"unexpected_field":"drop me"}\n'
        "```"
    )
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(agent, "stream_llm", _recording_stream(calls, lambda _n, _k: answer))
    attachments = [
        Attachment(type="image", filename="a.png"),
        Attachment(type="file", filename="notes.pdf"),
        Attachment(type="image", filename="b.png"),
    ]

    result = await _analysis_call(agent, attachments)

    assert result.learning_goal == "understand a circle"
    assert result.math_focus == ["radius"]
    assert "unexpected_field" not in result.model_dump()
    user_prompt = calls[0]["user_prompt"]
    assert "refs=2" in user_prompt
    assert "refs=3" not in user_prompt
    assert "history=(none)" in user_prompt
    assert "style=(none)" in user_prompt
    assert "input=Explain a circle" in user_prompt
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert [message["role"] for message in calls[0]["messages"]] == ["system", "user"]


@pytest.mark.asyncio
async def test_analysis_recovers_prompts_through_one_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A worker that looked prompts up before install finished must recover once."""
    import deeptutor.agents.math_animator.agents.concept_analysis_agent as module

    agent = ConceptAnalysisAgent()
    agent.prompts = None
    reloads: list[tuple[str, ...]] = []

    class _Manager:
        def reload_prompts(self, module_name: str, agent_name: str, language: str) -> dict:
            reloads.append((module_name, agent_name, language))
            return {"system": "Analyze.", "user_template": ANALYSIS_TEMPLATE}

    monkeypatch.setattr(module, "get_prompt_manager", lambda: _Manager())
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        agent,
        "stream_llm",
        _recording_stream(calls, lambda _n, _k: '{"learning_goal":"goal"}'),
    )

    result = await _analysis_call(agent, [])

    assert result.learning_goal == "goal"
    assert reloads == [("math_animator", "concept_analysis_agent", agent.language)]


@pytest.mark.asyncio
async def test_analysis_prompts_still_missing_after_reload_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.agents.math_animator.agents.concept_analysis_agent as module

    agent = ConceptAnalysisAgent()
    agent.prompts = None

    class _Manager:
        def reload_prompts(self, *_args: str) -> dict:
            return {}

    monkeypatch.setattr(module, "get_prompt_manager", lambda: _Manager())

    with pytest.raises(ValueError, match="ConceptAnalysisAgent prompts are not configured"):
        await _analysis_call(agent, [])


@pytest.mark.asyncio
async def test_analysis_rejects_non_object_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare array is not an answer: the stage must fail, not plan nothing."""
    agent = ConceptAnalysisAgent()
    agent.prompts = {"system": "Analyze.", "user_template": ANALYSIS_TEMPLATE}
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        agent, "stream_llm", _recording_stream(calls, lambda _n, _k: '["just a list"]')
    )

    with pytest.raises(ValueError, match="returned no learning goal"):
        await _analysis_call(agent, [])

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_analysis_provider_failure_propagates_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider timeout surfaces to the pipeline; no low-effort second ask."""
    agent = ConceptAnalysisAgent()
    agent.prompts = {"system": "Analyze.", "user_template": ANALYSIS_TEMPLATE}
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        agent,
        "stream_llm",
        _recording_stream(calls, lambda _n, _k: TimeoutError("provider timed out")),
    )

    with pytest.raises(TimeoutError):
        await _analysis_call(agent, [])

    assert len(calls) == 1


# ---------------------------------------------------------------------------
# ConceptDesignAgent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_design_maps_payload_and_embeds_analysis_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = ConceptDesignAgent()
    agent.prompts = {"system": "Design.", "user_template": DESIGN_TEMPLATE}
    answer = json.dumps(
        {
            "title": "Circle",
            "scene_outline": ["draw a circle"],
            "visual_style": "chalk",
            "animation_notes": ["ease in"],
            "future_field": "ignored",
        }
    )
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(agent, "stream_llm", _recording_stream(calls, lambda _n, _k: answer))

    result = await _design_call(agent)

    assert result.title == "Circle"
    assert result.scene_outline == ["draw a circle"]
    assert result.visual_style == "chalk"
    assert result.animation_notes == ["ease in"]
    assert "future_field" not in result.model_dump()
    user_prompt = calls[0]["user_prompt"]
    assert "understand a circle" in user_prompt  # analysis_json embedded
    assert "style=(none)" in user_prompt  # empty style_hint placeholder
    assert calls[0]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_design_missing_prompts_raise_before_any_llm_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unlike the analysis stage, design has no prompt reload recovery."""
    agent = ConceptDesignAgent()
    agent.prompts = None

    def _unexpected_stream(**_kwargs) -> AsyncIterator[str]:  # pragma: no cover - guard
        raise AssertionError("stream_llm must not be called without prompts")
        yield ""

    monkeypatch.setattr(agent, "stream_llm", _unexpected_stream)

    with pytest.raises(ValueError, match="ConceptDesignAgent prompts are not configured"):
        await _design_call(agent)


@pytest.mark.asyncio
async def test_design_rejects_payload_without_scene_outline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A well-formed dict missing the expected key is still a failed stage."""
    agent = ConceptDesignAgent()
    agent.prompts = {"system": "Design.", "user_template": DESIGN_TEMPLATE}
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        agent, "stream_llm", _recording_stream(calls, lambda _n, _k: '{"title":"Circle"}')
    )

    with pytest.raises(ValueError, match="returned no scene outline"):
        await _design_call(agent)

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_design_provider_failure_propagates_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = ConceptDesignAgent()
    agent.prompts = {"system": "Design.", "user_template": DESIGN_TEMPLATE}
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        agent,
        "stream_llm",
        _recording_stream(calls, lambda _n, _k: TimeoutError("provider timed out")),
    )

    with pytest.raises(TimeoutError):
        await _design_call(agent)

    assert len(calls) == 1


# ---------------------------------------------------------------------------
# SummaryAgent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_maps_full_payload_and_embeds_pipeline_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = SummaryAgent()
    agent.prompts = {"system": "Summarize.", "user_template": SUMMARY_TEMPLATE}
    answer = json.dumps(
        {
            "summary_text": "A circle animation is ready.",
            "user_request": "Explain a circle",
            "generated_output": "circle.mp4",
            "key_points": ["radius", "area"],
        }
    )
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(agent, "stream_llm", _recording_stream(calls, lambda _n, _k: answer))

    result = await _summary_call(agent)

    assert result.summary_text == "A circle animation is ready."
    assert result.user_request == "Explain a circle"
    assert result.generated_output == "circle.mp4"
    assert result.key_points == ["radius", "area"]
    user_prompt = calls[0]["user_prompt"]
    assert "understand a circle" in user_prompt  # analysis_json
    assert "draw a circle" in user_prompt  # design_json
    assert "video" in user_prompt  # render_json output_mode
    assert calls[0]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_summary_missing_prompts_raise_before_any_llm_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = SummaryAgent()
    agent.prompts = None

    def _unexpected_stream(**_kwargs) -> AsyncIterator[str]:  # pragma: no cover - guard
        raise AssertionError("stream_llm must not be called without prompts")
        yield ""

    monkeypatch.setattr(agent, "stream_llm", _unexpected_stream)

    with pytest.raises(ValueError, match="SummaryAgent prompts are not configured"):
        await _summary_call(agent)


@pytest.mark.asyncio
async def test_summary_non_object_answer_degrades_to_empty_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rendering already succeeded: unparseable output keeps an empty summary.

    The reasoning-only degradation is covered elsewhere; this pins that the
    same grace applies to answers that parse but are not objects.
    """
    agent = SummaryAgent()
    agent.prompts = {"system": "Summarize.", "user_template": SUMMARY_TEMPLATE}
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        agent, "stream_llm", _recording_stream(calls, lambda _n, _k: '["not an object"]')
    )

    result = await _summary_call(agent)

    assert result.summary_text == ""
    assert result.key_points == []
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_summary_provider_failure_propagates_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = SummaryAgent()
    agent.prompts = {"system": "Summarize.", "user_template": SUMMARY_TEMPLATE}
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        agent,
        "stream_llm",
        _recording_stream(calls, lambda _n, _k: TimeoutError("provider timed out")),
    )

    with pytest.raises(TimeoutError):
        await _summary_call(agent)

    assert len(calls) == 1
