"""Orchestration contract for the SectionArchitect (BookEngine stage 3).

Extends ``test_block_type_controls.py`` (allow-list filtering) with the
previously untested degradation and normalization branches of
``deeptutor/book/agents/page_planner.py``: LLM-disabled shortcut, LLM
failure/timeout fallback to the static planner, unusable payloads, item
normalization/caps, the SECTION coverage guarantee, depth scaling and the
``PagePlanner`` legacy alias. The LLM is mocked at
``page_planner.llm_json`` — no service is started.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.book.agents import page_planner
from deeptutor.book.agents.page_planner import PagePlanner, SectionArchitect
from deeptutor.book.models import BlockType, Chapter, ContentType, SourceAnchor


def _chapter(content_type: ContentType = ContentType.THEORY) -> Chapter:
    return Chapter(
        id="ch_arch",
        title="Section architect",
        summary="A chapter used to exercise the architect.",
        learning_objectives=["Explain static fallback", "Scale target words"],
        content_type=content_type,
        source_anchors=[SourceAnchor(kind="kb", kb_name="notes", ref="doc-1", snippet="vectors")],
    )


def _install_llm(monkeypatch: pytest.MonkeyPatch, payload: Any) -> None:
    async def fake_llm_json(**_kwargs: Any) -> dict[str, Any]:
        return payload

    monkeypatch.setattr(page_planner, "llm_json", fake_llm_json)


def _stable(plan: list) -> list[dict[str, Any]]:
    """Drop per-instance volatile fields so two plans can be compared."""
    volatile = {"id", "created_at", "updated_at"}
    return [b.model_dump(exclude=volatile) for b in plan]


def _install_llm_error(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    async def boom(**_kwargs: Any) -> dict[str, Any]:
        raise exc

    monkeypatch.setattr(page_planner, "llm_json", boom)


@pytest.mark.asyncio
async def test_llm_disabled_shortcuts_to_static_without_calling_the_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail(**_kwargs: Any) -> None:
        raise AssertionError("llm_json must not be called when llm_enabled is False")

    monkeypatch.setattr(page_planner, "llm_json", _fail)
    architect = SectionArchitect(phase=2, llm_enabled=False)

    plan = await architect.plan_blocks_async(_chapter())

    assert _stable(plan) == _stable(architect.plan_blocks(_chapter()))
    assert plan[0].type is BlockType.SECTION
    assert plan[0].params["role"] == "introduction"


@pytest.mark.asyncio
async def test_llm_failure_and_timeout_fall_back_to_static_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    architect = SectionArchitect(phase=2)
    static = architect.plan_blocks(_chapter())

    for exc in (TimeoutError("llm timed out"), RuntimeError("provider down")):
        _install_llm_error(monkeypatch, exc)
        assert _stable(await architect.plan_blocks_async(_chapter())) == _stable(static)


@pytest.mark.parametrize("payload", [{}, {"blocks": []}, {"blocks": "nope"}])
@pytest.mark.asyncio
async def test_unusable_llm_payload_falls_back_to_static_plan(
    monkeypatch: pytest.MonkeyPatch, payload: Any
) -> None:
    _install_llm(monkeypatch, payload)
    architect = SectionArchitect(phase=2)
    static = architect.plan_blocks(_chapter())

    assert _stable(await architect.plan_blocks_async(_chapter())) == _stable(static)


@pytest.mark.asyncio
async def test_llm_plan_normalizes_items_and_drops_invalid_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_llm(
        monkeypatch,
        {
            "blocks": [
                {
                    "type": "SECTION",
                    "params": {"role": "opening", "target_words": 900},
                    "transition_in": "t" * 300,
                    "focus": "f" * 300,
                },
                "not-a-dict",
                {"type": "user_note"},  # real type but not LLM-plannable
                {"type": "hologram"},  # not a BlockType at all
                {"type": "quiz", "params": "not-a-dict"},
            ]
        },
    )

    blocks = await SectionArchitect(phase=2).plan_blocks_async(_chapter())

    assert [b.type for b in blocks] == [BlockType.SECTION, BlockType.QUIZ]
    section, quiz = blocks

    assert section.params["role"] == "opening"
    assert section.params["target_words"] == 900
    assert section.metadata["transition_in"] == "t" * 240  # clipped
    assert section.params["focus"] == "f" * 240  # clipped
    assert section.params["chapter_title"] == "Section architect"
    assert section.params["objectives"] == ["Explain static fallback", "Scale target words"]
    assert section.params["anchors"] == [
        {"kind": "kb", "kb_name": "notes", "ref": "doc-1", "snippet": "vectors"}
    ]

    # Non-dict params are discarded; chapter context is still injected.
    assert quiz.params["chapter_title"] == "Section architect"
    assert "role" not in quiz.params
    assert "transition_in" not in quiz.metadata


@pytest.mark.asyncio
async def test_llm_plan_is_capped_at_twelve_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_llm(
        monkeypatch,
        {
            "blocks": [{"type": "section", "params": {"role": "opening"}}]
            + [{"type": "quiz", "params": {"role": f"r{i}"}} for i in range(13)]
        },
    )

    blocks = await SectionArchitect(phase=2).plan_blocks_async(_chapter())

    assert len(blocks) == 12
    assert blocks[0].type is BlockType.SECTION
    assert all(b.type is BlockType.QUIZ for b in blocks[1:])


@pytest.mark.asyncio
async def test_llm_plan_without_section_gets_one_injected_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_llm(monkeypatch, {"blocks": [{"type": "quiz"}, {"type": "flash_cards"}]})

    blocks = await SectionArchitect(phase=2).plan_blocks_async(_chapter())

    assert [b.type for b in blocks] == [
        BlockType.SECTION,
        BlockType.QUIZ,
        BlockType.FLASH_CARDS,
    ]
    assert blocks[0].params["role"] == "core"
    assert blocks[0].params["target_words"] == 1700


def test_depth_scales_target_words_with_a_floor() -> None:
    architect = SectionArchitect(phase=2, llm_enabled=False)
    chapter = _chapter()

    standard = architect.plan_blocks(chapter)
    brief = architect.plan_blocks(chapter, depth="brief")
    unknown = architect.plan_blocks(chapter, depth="banana")

    assert standard[0].params["target_words"] == 1200
    assert brief[0].params["target_words"] == 600  # 1200 × 0.5
    assert unknown[0].params["target_words"] == 1200  # unknown depth → scale 1.0

    # LLM-authored plans funnel through the same scaling and floor.
    block = page_planner._build_block(
        BlockType.SECTION, {"target_words": 100}, chapter, depth="brief"
    )
    assert block.params["target_words"] == 120  # floor


def test_overview_content_type_reuses_the_theory_template() -> None:
    architect = SectionArchitect(phase=2, llm_enabled=False)

    overview = architect.plan_blocks(_chapter(ContentType.OVERVIEW))
    theory = architect.plan_blocks(_chapter(ContentType.THEORY))

    assert [b.type for b in overview] == [b.type for b in theory]
    assert [b.params.get("role") for b in overview] == [b.params.get("role") for b in theory]


@pytest.mark.asyncio
async def test_page_planner_alias_stays_llm_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail(**_kwargs: Any) -> None:
        raise AssertionError("PagePlanner must not reach the LLM layer")

    monkeypatch.setattr(page_planner, "llm_json", _fail)
    planner = PagePlanner(phase=2)

    assert planner.llm_enabled is False
    plan = await planner.plan_blocks_async(_chapter())

    assert [b.type for b in plan] == [b.type for b in planner.plan_blocks(_chapter())]
