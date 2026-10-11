"""SectionArchitect contract: one structured LLM call, honest degradation.

The architect's LLM layer is best effort: it sends the chapter spec (plus the
cached exploration summary) through :func:`llm_json`, then validates, clips
and coerces whatever comes back. Anything unusable — malformed, empty, a
raised error — must degrade to the always-available static template layer
instead of raising into the pipeline. ``llm_json`` is the seam stubbed here,
so no network is involved.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.book.agents import page_planner as planner_module
from deeptutor.book.agents.page_planner import PagePlanner, SectionArchitect
from deeptutor.book.models import (
    BlockType,
    Chapter,
    ContentType,
    ExplorationReport,
    SourceAnchor,
)


def _chapter(**overrides: Any) -> Chapter:
    fields: dict[str, Any] = {
        "title": "Vector Spaces",
        "summary": "From basis to dimension",
        "learning_objectives": ["Define a basis", "Compute dimension"],
        "source_anchors": [SourceAnchor(kind="kb", kb_name="kb0", ref="doc-1", snippet="a span")],
        "content_type": ContentType.THEORY,
    }
    fields.update(overrides)
    return Chapter(**fields)


def _stub_llm_json(
    monkeypatch: pytest.MonkeyPatch,
    payloads: list[Any],
    *,
    calls: list[dict[str, Any]] | None = None,
) -> None:
    """Replace the module-level ``llm_json`` seam with a scripted replay.

    Entries are returned payloads; a callable entry is invoked instead and may
    raise. Each call's kwargs are appended to ``calls``.
    """
    queue = list(payloads)
    log = calls if calls is not None else []

    async def _llm_json(**kwargs: Any) -> dict[str, Any]:
        log.append(kwargs)
        step = queue.pop(0)
        if callable(step):
            return step(**kwargs)
        return step

    monkeypatch.setattr(planner_module, "llm_json", _llm_json)


@pytest.mark.asyncio
async def test_plan_blocks_async_builds_blocks_from_a_good_llm_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    _stub_llm_json(
        monkeypatch,
        [
            {
                "blocks": [
                    {
                        "type": "section",
                        "params": {"role": "intro", "target_words": 800},
                        "transition_in": "t" * 300,
                        "focus": "f" * 300,
                    },
                    {"type": "quiz", "params": {"num_questions": 2}},
                ]
            }
        ],
        calls=calls,
    )
    chapter = _chapter()

    blocks = await SectionArchitect().plan_blocks_async(
        chapter, exploration=ExplorationReport(summary="Retrieved-passage brief")
    )

    assert [b.type for b in blocks] == [BlockType.SECTION, BlockType.QUIZ]
    intro = blocks[0]
    assert intro.params["role"] == "intro"
    assert intro.params["chapter_title"] == "Vector Spaces"
    assert intro.params["chapter_summary"] == "From basis to dimension"
    assert intro.params["objectives"] == chapter.learning_objectives
    assert intro.params["anchors"] == [a.model_dump() for a in chapter.source_anchors]
    # Long free-form LLM strings are clipped before they reach a block.
    assert intro.metadata["transition_in"] == "t" * 240
    assert intro.params["focus"] == "f" * 240
    quiz = blocks[1]
    assert quiz.params["num_questions"] == 2
    assert quiz.metadata == {}

    # The call itself asks for the architect payload shape.
    assert len(calls) == 1
    assert calls[0]["expected_key"] == "blocks"


@pytest.mark.asyncio
async def test_the_llm_prompt_assembles_chapter_and_exploration_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    _stub_llm_json(monkeypatch, [{"blocks": [{"type": "quiz"}]}], calls=calls)
    chapter = _chapter()

    await SectionArchitect().plan_blocks_async(
        chapter, exploration=ExplorationReport(summary="Span of vectors covered")
    )

    assert "Vector Spaces" in calls[0]["user_prompt"]
    assert "Define a basis" in calls[0]["user_prompt"]
    assert "Span of vectors covered" in calls[0]["user_prompt"]
    assert calls[0]["system_prompt"].strip()


@pytest.mark.asyncio
async def test_malformed_blocks_payload_falls_back_to_the_static_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_llm_json(monkeypatch, [{"blocks": "not-a-list"}])
    architect = SectionArchitect()

    blocks = await architect.plan_blocks_async(_chapter())

    static = architect.plan_blocks(_chapter())
    assert [b.type for b in blocks] == [b.type for b in static]


@pytest.mark.asyncio
async def test_empty_blocks_payload_falls_back_to_the_static_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_llm_json(monkeypatch, [{"blocks": []}, {}])
    architect = SectionArchitect()
    static_types = [b.type for b in architect.plan_blocks(_chapter())]

    for payload in ({"blocks": []}, {}):
        blocks = await architect.plan_blocks_async(_chapter())
        assert [b.type for b in blocks] == static_types


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_the_static_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("provider down")

    _stub_llm_json(monkeypatch, [_boom])
    architect = SectionArchitect()

    blocks = await architect.plan_blocks_async(_chapter())

    static = architect.plan_blocks(_chapter())
    assert [b.type for b in blocks] == [b.type for b in static]


@pytest.mark.asyncio
async def test_malformed_items_are_skipped_and_a_section_is_always_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_llm_json(
        monkeypatch,
        [
            {
                "blocks": [
                    "prose",
                    None,
                    {"type": 123},
                    {"type": "hologram"},
                    {"type": "quiz", "params": {"num_questions": 1}},
                ]
            }
        ],
    )

    blocks = await SectionArchitect().plan_blocks_async(_chapter())

    assert [b.type for b in blocks] == [BlockType.SECTION, BlockType.QUIZ]
    assert blocks[0].params["role"] == "core"


@pytest.mark.asyncio
async def test_allowed_filter_drops_other_types_but_keeps_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_llm_json(
        monkeypatch,
        [{"blocks": [{"type": "quiz"}, {"type": "callout"}]}],
    )

    blocks = await SectionArchitect().plan_blocks_async(_chapter(), allowed={BlockType.QUIZ})

    assert [b.type for b in blocks] == [BlockType.SECTION, BlockType.QUIZ]


@pytest.mark.asyncio
async def test_all_llm_items_filtered_by_allowed_yields_one_core_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_llm_json(
        monkeypatch,
        [{"blocks": [{"type": "figure"}, {"type": "callout"}]}],
    )

    blocks = await SectionArchitect().plan_blocks_async(_chapter(), allowed={BlockType.QUIZ})

    assert len(blocks) == 1
    assert blocks[0].type == BlockType.SECTION
    assert blocks[0].params["role"] == "core"


@pytest.mark.asyncio
async def test_plan_is_capped_at_twelve_blocks_and_transition_text_is_clipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_llm_json(
        monkeypatch,
        [{"blocks": [{"type": "section", "transition_in": "x" * 300} for _ in range(14)]}],
    )

    blocks = await SectionArchitect().plan_blocks_async(_chapter())

    assert len(blocks) == 12
    assert all(b.type == BlockType.SECTION for b in blocks)
    assert blocks[0].metadata["transition_in"] == "x" * 240


@pytest.mark.asyncio
async def test_target_words_follow_the_reader_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_llm_json(
        monkeypatch,
        [
            {"blocks": [{"type": "section", "params": {"target_words": 1000}}]},
            {"blocks": [{"type": "section", "params": {"target_words": 100}}]},
        ],
    )

    deep = await SectionArchitect().plan_blocks_async(_chapter(), depth="deep")
    brief = await SectionArchitect().plan_blocks_async(_chapter(), depth="brief")

    assert deep[0].params["target_words"] == 1600  # 1000 x 1.6
    assert brief[0].params["target_words"] == 120  # 100 x 0.5, floored at 120


@pytest.mark.asyncio
async def test_llm_disabled_and_page_planner_alias_never_call_the_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("the static layer must not reach the LLM")

    _stub_llm_json(monkeypatch, [_boom])
    architect = SectionArchitect(llm_enabled=False)
    static_types = [b.type for b in architect.plan_blocks(_chapter())]

    blocks = await architect.plan_blocks_async(_chapter())
    alias_blocks = await PagePlanner().plan_blocks_async(_chapter())

    assert [b.type for b in blocks] == static_types
    assert [b.type for b in alias_blocks] == static_types


def test_static_plan_selects_template_by_content_type_and_applies_depth() -> None:
    chapter = _chapter(content_type=ContentType.DERIVATION)

    deep = SectionArchitect().plan_blocks(chapter, depth="brief")

    assert deep[0].type == BlockType.SECTION
    assert deep[0].params["role"] == "setup"
    assert deep[0].params["target_words"] == 700  # 1400 x 0.5
    assert BlockType.ANIMATION in {b.type for b in deep}
