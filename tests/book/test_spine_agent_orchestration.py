"""Orchestration contract for ``SpineAgent`` (BookEngine stage 2).

Covers the previously untested normalization and degradation paths of
``deeptutor/book/agents/spine_agent.py``: proposal/user prompt assembly,
LLM JSON coercion into ``Chapter`` models, and the fallback overview
chapter when the LLM payload is unusable. The LLM is mocked at
``BaseAgent.stream_llm`` — no service is started.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.book.agents.spine_agent import SpineAgent
from deeptutor.book.models import BookProposal, ContentType


def _proposal() -> BookProposal:
    return BookProposal(
        title="Linear Algebra",
        description="Vectors to eigenvalues",
        scope=" undergraduate",
        target_level="first-year",
        estimated_chapters=3,
        rationale="foundation for ML",
    )


def _spine_agent(monkeypatch: pytest.MonkeyPatch) -> SpineAgent:
    """Build a SpineAgent without touching data/user/settings/agents.yaml."""
    monkeypatch.setattr("deeptutor.agents.base_agent.get_agent_params", lambda _module_name: {})
    return SpineAgent(api_key="test-key", base_url="http://localhost:9", language="en")


def _install_stream(monkeypatch: pytest.MonkeyPatch, chunks: list[str]) -> dict[str, Any]:
    recorded: dict[str, Any] = {}

    async def _stream_llm(self: BaseAgent, **kwargs: Any):
        recorded.update(kwargs)
        for chunk in chunks:
            yield chunk

    monkeypatch.setattr(BaseAgent, "stream_llm", _stream_llm)
    return recorded


@pytest.mark.asyncio
async def test_process_builds_spine_from_valid_llm_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = _install_stream(
        monkeypatch,
        [
            json.dumps(
                {
                    "chapters": [
                        {"title": "Vectors", "order": 7},
                        {"title": "Matrices"},
                        {"title": "Eigenvalues"},
                    ]
                }
            )
        ],
    )

    spine = await _spine_agent(monkeypatch).process(book_id="bk_1", proposal=_proposal())

    assert spine.book_id == "bk_1"
    assert [c.title for c in spine.chapters] == ["Vectors", "Matrices", "Eigenvalues"]
    # The order field is re-indexed deterministically regardless of LLM output.
    assert [c.order for c in spine.chapters] == [0, 1, 2]
    assert recorded["stage"] == "spine"
    assert recorded["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_process_routes_proposal_and_material_into_the_user_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = _install_stream(monkeypatch, [json.dumps({"chapters": [{"title": "Vectors"}]})])

    agent = _spine_agent(monkeypatch)
    await agent.process(
        book_id="bk_1",
        proposal=_proposal(),
        source_material="  KB excerpt about vector spaces  ",
    )

    user_prompt = recorded["user_prompt"]
    assert "title: Linear Algebra" in user_prompt
    assert "description: Vectors to eigenvalues" in user_prompt
    assert "target_level: first-year" in user_prompt
    assert "estimated_chapters: 3" in user_prompt
    assert "KB excerpt about vector spaces" in user_prompt
    assert recorded["system_prompt"]

    recorded.clear()
    await agent.process(book_id="bk_1", proposal=_proposal(), source_material="   \n")
    assert "(no extra material provided)" in recorded["user_prompt"]


@pytest.mark.asyncio
async def test_process_normalizes_and_clips_llm_chapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "chapters": [
            "not-a-dict",
            {"title": "x" * 200, "learning_objectives": ["  "], "summary": "y" * 500},
            {"title": "Vectors", "content_type": "derivation"},
            {"title": "VECTORS"},  # duplicate (case-insensitive) → dropped
            {
                "title": "Matrices",
                "learning_objectives": "not-a-list",
                "source_anchors": "not-a-list",
                "prerequisites": {"0": "Vectors"},
                "content_type": "hologram",
            },
            {
                "title": "Eigenvalues",
                "learning_objectives": [f"obj {i}" for i in range(9)],
                "prerequisites": ["p" * 300 for _ in range(6)],
                "source_anchors": [
                    {
                        "kind": "kb",
                        "kb_name": "k" * 200,
                        "ref": "r" * 400,
                        "snippet": "s" * 500,
                    }
                ]
                + ["junk"] * 8,
            },
        ]
    }
    _install_stream(monkeypatch, [json.dumps(payload)])

    spine = await _spine_agent(monkeypatch).process(book_id="bk_1", proposal=_proposal())

    titles = [c.title for c in spine.chapters]
    assert titles == ["x" * 160 + "…", "Vectors", "Matrices", "Eigenvalues"]

    clipped = spine.chapters[0]
    assert clipped.summary == "y" * 400 + "…"
    assert clipped.learning_objectives == []

    matrices = spine.chapters[2]
    assert matrices.learning_objectives == []
    assert matrices.source_anchors == []
    assert matrices.prerequisites == []
    assert matrices.content_type is ContentType.THEORY

    eigen = spine.chapters[3]
    assert len(eigen.learning_objectives) == 6  # capped
    assert len(eigen.prerequisites) == 4  # capped
    assert len(eigen.prerequisites[0]) == 161  # clipped at 160 + ellipsis
    assert len(eigen.source_anchors) == 1
    anchor = eigen.source_anchors[0]
    assert anchor.kind == "kb"
    assert anchor.kb_name == "k" * 120 + "…"
    assert anchor.ref == "r" * 200 + "…"
    assert anchor.snippet == "s" * 300 + "…"


@pytest.mark.parametrize(
    "raw",
    [
        "the model replied with prose only, no JSON here",
        "[]",
        json.dumps({"chapters": "two"}),
        json.dumps({"chapters": ["still not dicts", 7]}),
    ],
)
@pytest.mark.asyncio
async def test_process_falls_back_to_overview_chapter_on_malformed_output(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    _install_stream(monkeypatch, [raw])

    spine = await _spine_agent(monkeypatch).process(book_id="bk_1", proposal=_proposal())

    assert len(spine.chapters) == 1
    fallback = spine.chapters[0]
    assert fallback.title == "Linear Algebra – Overview"
    assert fallback.order == 0
    assert fallback.content_type is ContentType.THEORY
    assert fallback.summary == "Vectors to eigenvalues"
    assert spine.chapters[0].learning_objectives


@pytest.mark.asyncio
async def test_process_does_not_swallow_a_failing_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(self: BaseAgent, **_kwargs: Any):
        yield ""
        raise RuntimeError("provider down")

    monkeypatch.setattr(BaseAgent, "stream_llm", _boom)

    with pytest.raises(RuntimeError, match="provider down"):
        await _spine_agent(monkeypatch).process(book_id="bk_1", proposal=_proposal())
