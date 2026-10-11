"""Contract tests for the visualize ``CodeGeneratorAgent``.

Everything is mocked at the ``BaseAgent.call_llm`` seam — no test reaches
the network. Together they pin:

- how the code-generation prompt is assembled and formatted, and the hard
  ``ValueError`` when the agent's prompts are missing;
- the LLM output parsing contract: the language hint per render type, the
  fenced-block fallback, the root-tag trimming net, and HTML document
  acceptance;
- failure / timeout degradation: LLM errors propagate (the capability layer
  owns the user-facing fallback), while an empty payload degrades to an
  empty string instead of raising.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.agents.visualize.agents.code_generator_agent import CodeGeneratorAgent
from deeptutor.agents.visualize.models import VisualizationAnalysis

PROMPTS = {
    "system_base": "BASE RULES",
    "rules_general": "GENERAL RULES",
    "rules_svg": "SVG RULES",
    "rules_chartjs": "CHARTJS RULES",
    "rules_mermaid": "MERMAID RULES",
    "rules_html": "HTML RULES",
    "user_template": (
        "user={user_input}|history={history_context}|type={render_type}|analysis={analysis_json}"
    ),
}


@pytest.fixture(autouse=True)
def _stub_agent_params(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decouple from the local, git-ignored ``agents.yaml``.

    ``BaseAgent.__init__`` eagerly calls ``get_agent_params(module_name)``,
    which raises ``FileNotFoundError`` on a clean checkout (CI included)
    because ``data/user/settings/agents.yaml`` is untracked. Stub it with a
    default dict so instantiating ``CodeGeneratorAgent`` stays config-free.
    """
    monkeypatch.setattr(
        "deeptutor.agents.base_agent.get_agent_params",
        lambda _module_name: {},
    )


def _make_agent(
    monkeypatch: pytest.MonkeyPatch,
    *,
    prompts: dict[str, str] | None = PROMPTS,
    reply: str = "",
    error: Exception | None = None,
) -> tuple[CodeGeneratorAgent, dict[str, Any]]:
    agent = CodeGeneratorAgent(
        api_key="test-key",
        base_url="https://llm.invalid",
        api_version="2024-10-01",
        language="en",
    )
    agent.prompts = prompts
    recorded: dict[str, Any] = {}

    async def fake_call_llm(self: BaseAgent, **kwargs: Any) -> str:
        recorded.update(kwargs)
        if error is not None:
            raise error
        return reply

    monkeypatch.setattr(BaseAgent, "call_llm", fake_call_llm)
    return agent, recorded


def _analysis(render_type: str) -> VisualizationAnalysis:
    return VisualizationAnalysis(
        render_type=render_type,  # type: ignore[arg-type]
        description="demo",
        data_description="two series",
        chart_type="bar",
        visual_elements=["bars"],
        rationale="simple comparison",
    )


async def _run(agent: CodeGeneratorAgent, render_type: str) -> str:
    return await agent.process(
        user_input="  draw a bar chart  ",
        history_context="",
        analysis=_analysis(render_type),
    )


def test_constructor_passes_connection_settings_through() -> None:
    agent = CodeGeneratorAgent(
        api_key="key-123",
        base_url="https://llm.invalid",
        api_version="2024-10-01",
        language="en",
    )

    assert agent.api_key == "key-123"
    assert agent.base_url == "https://llm.invalid"
    assert agent.api_version == "2024-10-01"
    assert agent.language == "en"
    assert (agent.module_name, agent.agent_name) == ("visualize", "code_generator_agent")


@pytest.mark.asyncio
async def test_prompt_assembly_and_user_template_formatting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, recorded = _make_agent(monkeypatch, reply="```svg\n<svg/>\n```")
    analysis = _analysis("svg")

    await agent.process(
        user_input="  draw a bar chart  ",
        history_context="",
        analysis=analysis,
    )

    assert recorded["system_prompt"] == "BASE RULES\n\nGENERAL RULES\n\nSVG RULES"
    analysis_json = json.dumps(analysis.model_dump(), ensure_ascii=False, indent=2)
    assert recorded["user_prompt"] == (
        "user=draw a bar chart|history=(none)|type=svg|analysis=" + analysis_json
    )


@pytest.mark.asyncio
async def test_missing_prompts_fail_fast_before_any_llm_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, recorded = _make_agent(monkeypatch, prompts=None)

    with pytest.raises(ValueError, match="prompts are not configured"):
        await _run(agent, "svg")

    assert recorded == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("render_type", "reply", "expected"),
    [
        pytest.param(
            "svg",
            "```text\nnotes\n```\n```svg\n<svg><rect/></svg>\n```",
            "<svg><rect/></svg>",
            id="svg-hint-skips-other-fences",
        ),
        pytest.param(
            "chartjs",
            "```text\nnotes\n```\n```javascript\nconst c = {type: 'bar'};\n```",
            "const c = {type: 'bar'};",
            id="chartjs-falls-back-to-javascript-hint",
        ),
        pytest.param(
            "mermaid",
            "```text\nnotes\n```\n```mermaid\ngraph TD;A-->B;\n```",
            "graph TD;A-->B;",
            id="mermaid-uses-mermaid-hint",
        ),
        pytest.param(
            "mindmap",
            "```text\nnotes\n```\n```mermaid\ngraph TD;A-->B;\n```",
            "graph TD;A-->B;",
            id="mindmap-shares-the-mermaid-hint",
        ),
        pytest.param(
            "html",
            "```text\nnotes\n```\n```html\n<p>hi</p>\n```",
            "<p>hi</p>",
            id="html-uses-html-hint",
        ),
        pytest.param(
            "manim_video",
            "```text\nnotes\n```\n```javascript\nfrom manim import Scene\n```",
            "from manim import Scene",
            id="unknown-render-types-use-the-javascript-hint",
        ),
    ],
)
async def test_render_type_selects_the_fenced_block(
    monkeypatch: pytest.MonkeyPatch,
    render_type: str,
    reply: str,
    expected: str,
) -> None:
    agent, _ = _make_agent(monkeypatch, reply=reply)

    code = await _run(agent, render_type)

    assert code == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("render_type", "reply", "expected"),
    [
        pytest.param(
            "svg",
            "Sure, here you go: <svg width='4'><rect/></svg> hope it helps!",
            "<svg width='4'><rect/></svg>",
            id="svg-unfenced-prose-trimmed-to-root-tags",
        ),
        pytest.param(
            "html",
            "```html\nHere you go:\n<!DOCTYPE html>\n<html><body>hi</body></html>\n```",
            "<!DOCTYPE html>\n<html><body>hi</body></html>",
            id="html-fenced-with-prose-trimmed-to-document",
        ),
        pytest.param(
            "html",
            "<!doctype html><html><body>hi</body></html>",
            "<!doctype html><html><body>hi</body></html>",
            id="html-unfenced-document-accepted-whole",
        ),
    ],
)
async def test_root_tag_trimming_defensive_net(
    monkeypatch: pytest.MonkeyPatch,
    render_type: str,
    reply: str,
    expected: str,
) -> None:
    agent, _ = _make_agent(monkeypatch, reply=reply)

    code = await _run(agent, render_type)

    assert code == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("render_type", ["svg", "chartjs", "html"])
async def test_empty_llm_response_degrades_to_empty_code(
    monkeypatch: pytest.MonkeyPatch,
    render_type: str,
) -> None:
    agent, _ = _make_agent(monkeypatch, reply="   ")

    code = await _run(agent, render_type)

    assert code == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "match"),
    [
        pytest.param(
            asyncio.TimeoutError("LLM timed out"), "timed out", id="llm-timeout-propagates"
        ),
        pytest.param(RuntimeError("provider 500"), "provider 500", id="provider-error-propagates"),
    ],
)
async def test_llm_failures_propagate_to_the_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    match: str,
) -> None:
    agent, _ = _make_agent(monkeypatch, error=error)

    with pytest.raises(type(error), match=match):
        await _run(agent, "svg")
