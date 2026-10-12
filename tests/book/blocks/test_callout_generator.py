from __future__ import annotations

import pytest

from deeptutor.book.blocks import callout as callout_module
from deeptutor.book.blocks.base import BlockContext
from deeptutor.book.blocks.callout import _VARIANT_LABELS, CalloutGenerator
from deeptutor.book.models import Block, BlockStatus, BlockType, Chapter, Page


def _ctx(params: dict | None = None, language: str = "en") -> BlockContext:
    chapter = Chapter(
        title="Convolution",
        summary="Bridging time and frequency",
        learning_objectives=["Explain the convolution theorem"],
    )
    return BlockContext(
        book_id="book-1",
        chapter=chapter,
        page=Page(chapter_id=chapter.id),
        block=Block(type=BlockType.CALLOUT, params=params or {}),
        language=language,
    )


@pytest.mark.asyncio
async def test_default_variant_writes_english_label_and_body(monkeypatch) -> None:
    seen = {}

    async def fake_llm_text(**kwargs):
        seen.update(kwargs)
        return "Convolution in time is multiplication in frequency."

    monkeypatch.setattr(callout_module, "llm_text", fake_llm_text)
    block = await CalloutGenerator().generate(_ctx())

    assert block.status == BlockStatus.READY
    assert block.payload == {
        "variant": "key_idea",
        "label": "Key Idea",
        "body": "Convolution in time is multiplication in frequency.",
    }
    assert block.source_anchors == []
    assert block.metadata == {}
    assert seen["max_tokens"] == 250
    assert seen["temperature"] == 0.5
    assert seen["reasoning_effort"] == "none"
    assert seen["language"] == "en"
    assert "Callout variant: key_idea (Key Idea)" in seen["user_prompt"]
    assert "Chapter: Convolution" in seen["user_prompt"]
    assert "Summary: Bridging time and frequency" in seen["user_prompt"]
    assert "Objectives: Explain the convolution theorem" in seen["user_prompt"]


@pytest.mark.asyncio
async def test_chinese_language_selects_the_chinese_label(monkeypatch) -> None:
    captured = {}

    async def fake_llm_text(**kwargs):
        captured["user_prompt"] = kwargs["user_prompt"]
        return "时域卷积等于频域相乘。"

    monkeypatch.setattr(callout_module, "llm_text", fake_llm_text)
    block = await CalloutGenerator().generate(_ctx(language="zh"))

    assert block.status == BlockStatus.READY
    assert block.payload["label"] == "核心要点"
    assert "Callout 变体：key_idea（核心要点）" in captured["user_prompt"]
    assert "章节：Convolution" in captured["user_prompt"]


@pytest.mark.asyncio
async def test_every_known_variant_maps_to_its_label_pair(monkeypatch) -> None:
    for variant, (en_label, zh_label) in _VARIANT_LABELS.items():
        captured = {}

        async def fake_llm_text(**kwargs):
            captured[kwargs["language"]] = kwargs["user_prompt"]
            return "body text"

        monkeypatch.setattr(callout_module, "llm_text", fake_llm_text)
        en_block = await CalloutGenerator().generate(_ctx({"variant": variant}, language="en"))
        zh_block = await CalloutGenerator().generate(_ctx({"variant": variant}, language="zh"))

        assert en_block.status == BlockStatus.READY
        assert en_block.payload["variant"] == variant
        assert en_block.payload["label"] == en_label
        assert zh_block.payload["label"] == zh_label
        assert f"Callout variant: {variant} ({en_label})" in captured["en"]
        assert f"Callout 变体：{variant}（{zh_label}）" in captured["zh"]


@pytest.mark.asyncio
async def test_unknown_variant_falls_back_to_key_idea_label(monkeypatch) -> None:
    captured = {}

    async def fake_llm_text(**kwargs):
        captured["user_prompt"] = kwargs["user_prompt"]
        return "body text"

    monkeypatch.setattr(callout_module, "llm_text", fake_llm_text)
    block = await CalloutGenerator().generate(_ctx({"variant": "mystery"}))

    assert block.status == BlockStatus.READY
    assert block.payload["variant"] == "mystery"
    assert block.payload["label"] == "Key Idea"
    assert "Callout variant: mystery (Key Idea)" in captured["user_prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [None, {}, {"variant": ""}, {"variant": None}])
async def test_missing_variant_params_still_default_to_key_idea(monkeypatch, params) -> None:
    async def fake_llm_text(**kwargs):
        return "body"

    monkeypatch.setattr(callout_module, "llm_text", fake_llm_text)
    block = await CalloutGenerator().generate(_ctx(params))

    assert block.status == BlockStatus.READY
    assert block.payload["variant"] == "key_idea"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["", "   ", "\n\t "])
async def test_blank_body_marks_the_block_error(monkeypatch, body) -> None:
    async def fake_llm_text(**kwargs):
        return body

    monkeypatch.setattr(callout_module, "llm_text", fake_llm_text)
    block = await CalloutGenerator().generate(_ctx())

    assert block.status == BlockStatus.ERROR
    assert block.error == "LLM returned no visible callout content."
    assert block.payload == {}
    assert block.metadata["failure"]["kind"] == "empty_response"
    assert block.metadata["failure"]["retryable"] is True


@pytest.mark.asyncio
async def test_empty_summary_and_objectives_use_none_placeholder(monkeypatch) -> None:
    captured = {}

    async def fake_llm_text(**kwargs):
        captured["user_prompt"] = kwargs["user_prompt"]
        return "body"

    monkeypatch.setattr(callout_module, "llm_text", fake_llm_text)
    chapter = Chapter(title="T", summary="", learning_objectives=[])
    ctx = BlockContext(
        book_id="book-1",
        chapter=chapter,
        page=Page(chapter_id=chapter.id),
        block=Block(type=BlockType.CALLOUT, params={}),
        language="en",
    )
    block = await CalloutGenerator().generate(ctx)

    assert block.status == BlockStatus.READY
    assert "Summary: (none)" in captured["user_prompt"]
    assert "Objectives: (none)" in captured["user_prompt"]


@pytest.mark.asyncio
async def test_params_override_chapter_fields(monkeypatch) -> None:
    captured = {}

    async def fake_llm_text(**kwargs):
        captured["user_prompt"] = kwargs["user_prompt"]
        return "body"

    monkeypatch.setattr(callout_module, "llm_text", fake_llm_text)
    block = await CalloutGenerator().generate(
        _ctx(
            {
                "chapter_title": "Override",
                "chapter_summary": "Custom",
                "objectives": ["o1", "o2"],
            }
        )
    )

    assert block.status == BlockStatus.READY
    assert "Chapter: Override" in captured["user_prompt"]
    assert "Summary: Custom" in captured["user_prompt"]
    assert "Objectives: o1; o2" in captured["user_prompt"]


def test_generator_declares_callout_block_type() -> None:
    assert CalloutGenerator.block_type == BlockType.CALLOUT
