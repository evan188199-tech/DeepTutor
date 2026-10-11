"""Focused contract tests for six low-coverage book block generators.

Covers payload assembly and malformed-LLM-output degradation for the
flash_cards / deep_dive / timeline / callout / interactive / user_note
generators. All LLM and visualize-pipeline boundaries are stubbed, so no
network access happens.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.book.blocks import (
    callout as callout_block,
)
from deeptutor.book.blocks import (
    deep_dive as deep_dive_block,
)
from deeptutor.book.blocks import (
    flash_cards as flash_cards_block,
)
from deeptutor.book.blocks import (
    interactive as interactive_block,
)
from deeptutor.book.blocks import (
    timeline as timeline_block,
)
from deeptutor.book.blocks import (
    user_note as user_note_block,
)
from deeptutor.book.blocks.base import BlockContext
from deeptutor.book.models import Block, BlockStatus, BlockType, Chapter, Page


def _context(
    block_type: BlockType,
    params: dict[str, object] | None = None,
    *,
    language: str = "en",
    objectives: list[str] | None = None,
) -> BlockContext:
    chapter = Chapter(
        id="ch-six",
        title="Mechanics",
        summary="Stress and strain",
        learning_objectives=objectives if objectives is not None else ["Relate stress to strain"],
    )
    block = Block(type=block_type, params=params or {})
    return BlockContext(
        book_id="book-six",
        chapter=chapter,
        page=Page(id="page-six", book_id="book-six", chapter_id=chapter.id),
        block=block,
        language=language,
        rag_enabled=False,
    )


# ── flash_cards ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flash_cards_assembles_cards_and_clamps_to_max_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    async def fake_llm_json(**kwargs: object) -> dict[str, object]:
        seen.update(kwargs)
        return {
            "cards": [
                {"front": "F" * 400, "back": "B" * 700, "hint": "  H" * 120},
                *[{"front": f"Q{i}", "back": f"A{i}"} for i in range(10)],
            ],
            "_metadata": {"model": "stub"},
        }

    monkeypatch.setattr(flash_cards_block, "llm_json", fake_llm_json)
    ctx = _context(BlockType.FLASH_CARDS, params={"count": 99})

    result = await flash_cards_block.FlashCardsGenerator().generate(ctx)

    assert result.status == BlockStatus.READY
    assert seen["expected_key"] == "cards"
    assert seen["reasoning_effort"] == "none"
    cards = result.payload["cards"]
    assert len(cards) == 8  # hard cap of 8 cards
    assert cards[0]["front"] == "F" * 300
    assert cards[0]["back"] == "B" * 600
    assert cards[0]["hint"] == "H  " * 66 + "H "
    assert result.metadata == {"model": "stub"}


@pytest.mark.asyncio
async def test_flash_cards_skips_malformed_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_llm_json(**_: object) -> dict[str, object]:
        return {
            "cards": [
                "not-a-dict",
                {"front": "   ", "back": "B"},  # blank front
                {"front": "Keep", "back": " This ", "hint": None},
                {"front": "Only front"},  # missing back
            ],
        }

    monkeypatch.setattr(flash_cards_block, "llm_json", fake_llm_json)
    ctx = _context(BlockType.FLASH_CARDS)

    result = await flash_cards_block.FlashCardsGenerator().generate(ctx)

    assert result.status == BlockStatus.READY
    assert result.payload["cards"] == [{"front": "Keep", "back": "This", "hint": ""}]


@pytest.mark.asyncio
async def test_flash_cards_min_count_clamp_keeps_three_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_llm_json(**_: object) -> dict[str, object]:
        return {
            "cards": [{"front": f"Q{i}", "back": f"A{i}"} for i in range(5)],
        }

    monkeypatch.setattr(flash_cards_block, "llm_json", fake_llm_json)
    ctx = _context(BlockType.FLASH_CARDS, params={"count": 1})

    result = await flash_cards_block.FlashCardsGenerator().generate(ctx)

    assert result.status == BlockStatus.READY
    assert [card["front"] for card in result.payload["cards"]] == [
        "Q0",
        "Q1",
        "Q2",
    ]


@pytest.mark.asyncio
async def test_flash_cards_degrades_when_no_usable_cards_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_llm_json(**_: object) -> dict[str, object]:
        return {"cards": "not-a-list"}

    monkeypatch.setattr(flash_cards_block, "llm_json", fake_llm_json)
    ctx = _context(BlockType.FLASH_CARDS)

    result = await flash_cards_block.FlashCardsGenerator().generate(ctx)

    assert result.status == BlockStatus.ERROR
    assert "flashcards" in result.error
    assert result.payload == {}
    assert result.metadata["failure"]["retryable"] is True


# ── deep_dive ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deep_dive_assembles_truncated_suggestions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_llm_json(**_: object) -> dict[str, object]:
        return {
            "suggestions": [
                {"topic": "T" * 200, "rationale": "R" * 400},
                "junk",
                {"rationale": "no topic"},
            ],
            "_metadata": {"k": "v"},
        }

    monkeypatch.setattr(deep_dive_block, "llm_json", fake_llm_json)
    ctx = _context(BlockType.DEEP_DIVE)

    result = await deep_dive_block.DeepDiveGenerator().generate(ctx)

    assert result.status == BlockStatus.READY
    assert result.payload["suggestions"] == [{"topic": "T" * 160, "rationale": "R" * 300}]
    assert result.metadata == {"k": "v"}


@pytest.mark.asyncio
async def test_deep_dive_degrades_when_no_suggestions_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_llm_json(**_: object) -> dict[str, object]:
        return {"suggestions": []}

    monkeypatch.setattr(deep_dive_block, "llm_json", fake_llm_json)
    ctx = _context(BlockType.DEEP_DIVE)

    result = await deep_dive_block.DeepDiveGenerator().generate(ctx)

    assert result.status == BlockStatus.ERROR
    assert "suggestions" in result.error
    assert result.metadata["failure"]["retryable"] is True


# ── timeline ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_timeline_assembles_truncated_events_capped_at_eight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_llm_json(**_: object) -> dict[str, object]:
        return {
            "events": [
                {
                    "date": "D" * 100,
                    "title": "T" * 200,
                    "description": "X" * 700,
                }
                for _ in range(9)
            ]
            + ["junk"]
        }

    monkeypatch.setattr(timeline_block, "llm_json", fake_llm_json)
    ctx = _context(BlockType.TIMELINE)

    result = await timeline_block.TimelineGenerator().generate(ctx)

    assert result.status == BlockStatus.READY
    events = result.payload["events"]
    assert len(events) == 8
    assert events[0] == {
        "date": "D" * 80,
        "title": "T" * 160,
        "description": "X" * 600,
    }


@pytest.mark.asyncio
async def test_timeline_degrades_when_no_events_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_llm_json(**_: object) -> dict[str, object]:
        return {}

    monkeypatch.setattr(timeline_block, "llm_json", fake_llm_json)
    ctx = _context(BlockType.TIMELINE)

    result = await timeline_block.TimelineGenerator().generate(ctx)

    assert result.status == BlockStatus.ERROR
    assert "timeline events" in result.error
    assert result.metadata["failure"]["retryable"] is True


# ── callout ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_callout_uses_variant_label_and_known_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    async def fake_llm_text(**kwargs: object) -> str:
        seen.update(kwargs)
        return "A common pitfall explained."

    monkeypatch.setattr(callout_block, "llm_text", fake_llm_text)
    ctx = _context(BlockType.CALLOUT, params={"variant": "common_pitfall"})

    result = await callout_block.CalloutGenerator().generate(ctx)

    assert result.status == BlockStatus.READY
    assert result.payload == {
        "variant": "common_pitfall",
        "label": "Watch Out",
        "body": "A common pitfall explained.",
    }
    assert seen["reasoning_effort"] == "none"
    assert "Watch Out" in seen["user_prompt"]
    assert "common_pitfall" in seen["user_prompt"]


@pytest.mark.asyncio
async def test_callout_unknown_variant_falls_back_with_zh_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_llm_text(**_: object) -> str:
        return "正文"

    monkeypatch.setattr(callout_block, "llm_text", fake_llm_text)
    ctx = _context(BlockType.CALLOUT, params={"variant": "wild_idea"}, language="zh")

    result = await callout_block.CalloutGenerator().generate(ctx)

    assert result.status == BlockStatus.READY
    assert result.payload["variant"] == "wild_idea"
    assert result.payload["label"] == "核心要点"


@pytest.mark.asyncio
async def test_callout_degrades_on_blank_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_llm_text(**_: object) -> str:
        return "   \n"

    monkeypatch.setattr(callout_block, "llm_text", fake_llm_text)
    ctx = _context(BlockType.CALLOUT)

    result = await callout_block.CalloutGenerator().generate(ctx)

    assert result.status == BlockStatus.ERROR
    assert "no visible callout content" in result.error
    assert result.metadata["failure"]["retryable"] is True


# ── interactive ──────────────────────────────────────────────────────────────

_HTML_DOC = "<!DOCTYPE html><html><body><div id='demo'></div></body></html>"


class _FakePipeline:
    last_init_kwargs: dict[str, object] = {}

    def __init__(
        self, *, api_key: object, base_url: object, api_version: object, language: object
    ) -> None:
        type(self).last_init_kwargs = {
            "api_key": api_key,
            "base_url": base_url,
            "api_version": api_version,
            "language": language,
        }

    async def run_analysis(
        self, *, user_input: str, history_context: str, render_mode: str
    ) -> object:
        from deeptutor.agents.visualize.models import VisualizationAnalysis

        self.run_analysis_kwargs = {
            "user_input": user_input,
            "history_context": history_context,
            "render_mode": render_mode,
        }
        return VisualizationAnalysis(
            render_type="html",
            description="Interactive demo",
            chart_type="custom",
        )

    async def run_code_generation(
        self, *, user_input: str, history_context: str, analysis: object
    ) -> str:
        self.run_code_kwargs = {"analysis": analysis}
        return _HTML_DOC


def _install_interactive_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.agents.visualize import pipeline as visualize_pipeline
    from deeptutor.services.llm import config as llm_config

    cfg = SimpleNamespace(
        api_key=["sk-a", "sk-b"],
        base_url="http://llm.local/v1",
        api_version="v1",
    )
    monkeypatch.setattr(llm_config, "get_llm_config", lambda: cfg)
    monkeypatch.setattr(interactive_block, "primary_api_key", lambda value: f"pk-of-{value}")
    monkeypatch.setattr(visualize_pipeline, "VisualizePipeline", _FakePipeline)


@pytest.mark.asyncio
async def test_interactive_wraps_validated_html_pipeline_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_interactive_stubs(monkeypatch)
    ctx = _context(BlockType.INTERACTIVE, params={"focus": "springs"})

    result = await interactive_block.InteractiveGenerator().generate(ctx)

    assert result.status == BlockStatus.READY
    assert result.payload["render_type"] == "html"
    assert result.payload["code"] == {"language": "html", "content": _HTML_DOC}
    assert result.payload["description"] == "Interactive demo"
    assert result.payload["chart_type"] == "custom"
    assert result.metadata == {
        "review_changed": False,
        "review_notes": "Passed local validation.",
    }
    assert _FakePipeline.last_init_kwargs == {
        "api_key": "pk-of-['sk-a', 'sk-b']",
        "base_url": "http://llm.local/v1",
        "api_version": "v1",
        "language": "en",
    }


@pytest.mark.asyncio
async def test_interactive_degrades_when_pipeline_stage_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_interactive_stubs(monkeypatch)

    async def exploding_run_analysis(self, **_: object) -> object:
        raise RuntimeError("analysis stage exploded")

    monkeypatch.setattr(_FakePipeline, "run_analysis", exploding_run_analysis)
    ctx = _context(BlockType.INTERACTIVE)

    result = await interactive_block.InteractiveGenerator().generate(ctx)

    assert result.status == BlockStatus.ERROR
    assert result.error.startswith("interactive generation failed")
    assert "analysis stage exploded" in result.error
    assert result.metadata["failure"]["retryable"] is True


# ── user_note ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_note_passes_body_through_without_llm() -> None:
    ctx = _context(BlockType.USER_NOTE, params={"body": "  **My note**\n"})

    result = await user_note_block.UserNoteGenerator().generate(ctx)

    assert result.status == BlockStatus.READY
    assert result.payload == {
        "format": "markdown",
        "body": "**My note**",
        "author": "user",
    }
    assert "failure" not in result.metadata


@pytest.mark.asyncio
async def test_user_note_defaults_to_empty_body_when_params_missing() -> None:
    ctx = _context(BlockType.USER_NOTE)

    result = await user_note_block.UserNoteGenerator().generate(ctx)

    assert result.status == BlockStatus.READY
    assert result.payload == {"format": "markdown", "body": "", "author": "user"}
