from __future__ import annotations

import pytest

from deeptutor.book.blocks import flash_cards as fc_module
from deeptutor.book.blocks.base import BlockContext, GenerationFailure
from deeptutor.book.blocks.flash_cards import FlashCardsGenerator
from deeptutor.book.models import Block, BlockStatus, BlockType, Chapter, Page


def _ctx(block_params: dict | None = None, language: str = "en") -> BlockContext:
    chapter = Chapter(
        title="Sampling Theory",
        summary="How discrete samples represent signals",
        learning_objectives=["State the Nyquist criterion"],
    )
    return BlockContext(
        book_id="book-1",
        chapter=chapter,
        page=Page(chapter_id=chapter.id),
        block=Block(type=BlockType.FLASH_CARDS, params=block_params or {}),
        language=language,
    )


def _fake_llm(payload):
    async def _llm(**kwargs):
        return payload

    return _llm


@pytest.mark.asyncio
async def test_generate_returns_sanitized_cards_and_ready_block(monkeypatch) -> None:
    seen = {}

    async def fake_llm(**kwargs):
        seen.update(kwargs)
        return {
            "cards": [
                {"front": "  State the Nyquist criterion.  ", "back": "x" * 700, "hint": "y" * 300},
                {"front": "", "back": "missing front"},
                "not-a-dict",
                {"front": "Third card", "back": "Fine"},
            ],
            "_metadata": {"model": "task-model"},
        }

    monkeypatch.setattr(fc_module, "llm_json", fake_llm)
    block = await FlashCardsGenerator().generate(_ctx())

    assert block.status == BlockStatus.READY
    assert block.error == ""
    assert "failure" not in block.metadata
    assert block.metadata == {"model": "task-model"}
    assert block.payload["cards"] == [
        {
            "front": "State the Nyquist criterion.",
            "back": "x" * 600,
            "hint": "y" * 200,
        },
        {"front": "Third card", "back": "Fine", "hint": ""},
    ]
    assert seen["expected_key"] == "cards"
    assert seen["max_tokens"] == 900
    assert seen["language"] == "en"


@pytest.mark.asyncio
async def test_generate_uses_params_overrides_and_clamps_count(monkeypatch) -> None:
    captured = {}

    async def fake_llm(**kwargs):
        captured.update(kwargs)
        return {"cards": [{"front": "f", "back": "b"} for _ in range(12)]}

    monkeypatch.setattr(fc_module, "llm_json", fake_llm)
    block = await FlashCardsGenerator().generate(
        _ctx(
            {
                "chapter_title": "Custom Title",
                "chapter_summary": "Custom Summary",
                "objectives": ["obj a", "obj b"],
                "count": "99",
            }
        )
    )

    assert block.status == BlockStatus.READY
    cards = block.payload["cards"]
    assert len(cards) == 8
    assert all(card["front"] == "f" and card["back"] == "b" for card in cards)
    assert "with 8 high-signal cards." in captured["system_prompt"]
    assert "Custom Title" in captured["user_prompt"]
    assert "Custom Summary" in captured["user_prompt"]
    assert "obj a; obj b" in captured["user_prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_count", "expected"),
    [("99", 8), (12, 8), ("1", 3), (0, 5), (None, 5)],
)
async def test_generate_clamps_count_to_the_three_to_eight_window(
    monkeypatch, raw_count, expected
) -> None:
    captured = {}

    async def fake_llm(**kwargs):
        captured["system_prompt"] = kwargs["system_prompt"]
        return {"cards": [{"front": f"f{i}", "back": "b"} for i in range(20)]}

    monkeypatch.setattr(fc_module, "llm_json", fake_llm)
    block = await FlashCardsGenerator().generate(_ctx({"count": raw_count}))

    assert block.status == BlockStatus.READY
    assert len(block.payload["cards"]) == expected
    assert f"with {expected} high-signal cards." in captured["system_prompt"]


@pytest.mark.asyncio
async def test_generate_reports_generator_error_for_non_numeric_count(monkeypatch) -> None:
    async def fake_llm(**kwargs):
        raise AssertionError("llm_json must not be reached when count is invalid")

    monkeypatch.setattr(fc_module, "llm_json", fake_llm)
    block = await FlashCardsGenerator().generate(_ctx({"count": "two"}))

    assert block.status == BlockStatus.ERROR
    assert "invalid literal for int" in block.error
    assert block.metadata["failure"]["kind"] == "generator_error"


@pytest.mark.asyncio
async def test_generate_falls_back_to_chapter_fields_and_marks_empty_summary(monkeypatch) -> None:
    captured = {}

    async def fake_llm(**kwargs):
        captured["user_prompt"] = kwargs["user_prompt"]
        return {"cards": [{"front": "f", "back": "b"}]}

    monkeypatch.setattr(fc_module, "llm_json", fake_llm)
    chapter = Chapter(title="Own Title", summary="", learning_objectives=[])
    ctx = BlockContext(
        book_id="book-1",
        chapter=chapter,
        page=Page(chapter_id=chapter.id),
        block=Block(type=BlockType.FLASH_CARDS, params={}),
        language="zh",
    )
    block = await FlashCardsGenerator().generate(ctx)

    assert block.status == BlockStatus.READY
    assert "Own Title" in captured["user_prompt"]
    assert "摘要：(无)" in captured["user_prompt"]
    assert "目标：(无)" in captured["user_prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"cards": []},
        {"cards": [{"front": "  ", "back": "b"}]},
        {"cards": "not-a-list"},
        {},
        {"cards": [{"front": "f"}]},
    ],
)
async def test_generate_marks_block_error_when_no_usable_card_survives(monkeypatch, payload) -> None:
    async def fake_llm(**kwargs):
        return payload

    monkeypatch.setattr(fc_module, "llm_json", fake_llm)
    block = await FlashCardsGenerator().generate(_ctx())

    assert block.status == BlockStatus.ERROR
    assert block.error == "LLM did not return any flashcards."
    assert block.payload == {}
    assert block.metadata["failure"]["kind"] == "empty_response"
    assert block.metadata["failure"]["retryable"] is True
    assert block.metadata["failure"]["source"] == "FlashCardsGenerator"


@pytest.mark.asyncio
async def test_generate_treats_non_dict_llm_payload_as_failure(monkeypatch) -> None:
    async def fake_llm(**kwargs):
        return ["cards", "in", "a", "list"]

    monkeypatch.setattr(fc_module, "llm_json", fake_llm)
    block = await FlashCardsGenerator().generate(_ctx())

    assert block.status == BlockStatus.ERROR
    assert block.metadata["failure"]["kind"] == "empty_response"


@pytest.mark.asyncio
async def test_generate_propagates_generation_failure_metadata(monkeypatch) -> None:
    async def fake_llm(**kwargs):
        raise GenerationFailure("LLM did not return any flashcards.")

    monkeypatch.setattr(fc_module, "llm_json", fake_llm)
    block = await FlashCardsGenerator().generate(_ctx())

    assert block.status == BlockStatus.ERROR
    assert block.metadata["failure"]["message"] == "LLM did not return any flashcards."
    assert block.metadata["failure"]["kind"] == "empty_response"


def test_generator_declares_flash_cards_block_type() -> None:
    assert FlashCardsGenerator.block_type == BlockType.FLASH_CARDS
