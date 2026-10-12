from __future__ import annotations

import pytest

from deeptutor.book.blocks import timeline as timeline_module
from deeptutor.book.blocks.base import BlockContext
from deeptutor.book.blocks.timeline import TimelineGenerator
from deeptutor.book.models import Block, BlockStatus, BlockType, Chapter, Page


def _ctx(params: dict | None = None, language: str = "en") -> BlockContext:
    chapter = Chapter(
        title="History of Fourier Analysis",
        summary="From the 1807 memoir to the FFT",
    )
    return BlockContext(
        book_id="book-1",
        chapter=chapter,
        page=Page(chapter_id=chapter.id),
        block=Block(type=BlockType.TIMELINE, params=params or {}),
        language=language,
    )


@pytest.mark.asyncio
async def test_generate_returns_truncated_events_and_ready_block(monkeypatch) -> None:
    seen = {}

    async def fake_llm(**kwargs):
        seen.update(kwargs)
        return {
            "events": [
                {
                    "date": "1807",
                    "title": "t" * 200,
                    "description": "d" * 900,
                },
                "not-a-dict",
                {
                    "date": "1" * 90,
                    "title": "Fourier series published",
                    "description": "Analytic theory appears",
                },
            ],
            "_metadata": {"model": "task-model"},
        }

    monkeypatch.setattr(timeline_module, "llm_json", fake_llm)
    block = await TimelineGenerator().generate(_ctx())

    assert block.status == BlockStatus.READY
    assert block.error == ""
    assert "failure" not in block.metadata
    assert block.metadata == {"model": "task-model"}
    assert block.payload["events"] == [
        {"date": "1807", "title": "t" * 160, "description": "d" * 600},
        {"date": "1" * 80, "title": "Fourier series published", "description": "Analytic theory appears"},
    ]
    assert seen["expected_key"] == "events"
    assert seen["max_tokens"] == 800
    assert seen["temperature"] == 0.4
    assert seen["reasoning_effort"] == "none"
    assert seen["language"] == "en"


@pytest.mark.asyncio
async def test_generate_keeps_at_most_eight_events(monkeypatch) -> None:
    async def fake_llm(**kwargs):
        return {
            "events": [
                {"date": str(year), "title": f"e{year}", "description": "d"}
                for year in range(12)
            ]
        }

    monkeypatch.setattr(timeline_module, "llm_json", fake_llm)
    block = await TimelineGenerator().generate(_ctx())

    assert block.status == BlockStatus.READY
    events = block.payload["events"]
    assert len(events) == 8
    assert [event["date"] for event in events] == [str(year) for year in range(8)]


@pytest.mark.asyncio
async def test_generate_coerces_missing_fields_to_empty_strings(monkeypatch) -> None:
    async def fake_llm(**kwargs):
        return {"events": [{"title": 42}]}

    monkeypatch.setattr(timeline_module, "llm_json", fake_llm)
    block = await TimelineGenerator().generate(_ctx())

    assert block.status == BlockStatus.READY
    assert block.payload["events"] == [{"date": "", "title": "42", "description": ""}]


@pytest.mark.asyncio
async def test_generate_uses_chapter_fields_and_marks_empty_summary(monkeypatch) -> None:
    captured = {}

    async def fake_llm(**kwargs):
        captured["user_prompt"] = kwargs["user_prompt"]
        return {"events": [{"date": "1807", "title": "t", "description": "d"}]}

    monkeypatch.setattr(timeline_module, "llm_json", fake_llm)
    chapter = Chapter(title="Own Title", summary="")
    ctx = BlockContext(
        book_id="book-1",
        chapter=chapter,
        page=Page(chapter_id=chapter.id),
        block=Block(type=BlockType.TIMELINE, params={}),
        language="zh",
    )
    block = await TimelineGenerator().generate(ctx)

    assert block.status == BlockStatus.READY
    assert "章节：Own Title" in captured["user_prompt"]
    assert "摘要：(无)" in captured["user_prompt"]


@pytest.mark.asyncio
async def test_params_override_chapter_fields(monkeypatch) -> None:
    captured = {}

    async def fake_llm(**kwargs):
        captured["user_prompt"] = kwargs["user_prompt"]
        return {"events": [{"date": "1807", "title": "t", "description": "d"}]}

    monkeypatch.setattr(timeline_module, "llm_json", fake_llm)
    block = await TimelineGenerator().generate(
        _ctx({"chapter_title": "Override", "chapter_summary": "Custom"})
    )

    assert block.status == BlockStatus.READY
    assert "Chapter: Override" in captured["user_prompt"]
    assert "Summary: Custom" in captured["user_prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"events": []},
        {"events": "not-a-list"},
        {},
        {"events": ["not-a-dict"]},
    ],
)
async def test_generate_marks_block_error_when_no_event_survives(monkeypatch, payload) -> None:
    async def fake_llm(**kwargs):
        return payload

    monkeypatch.setattr(timeline_module, "llm_json", fake_llm)
    block = await TimelineGenerator().generate(_ctx())

    assert block.status == BlockStatus.ERROR
    assert block.error == "LLM did not return any timeline events."
    assert block.payload == {}
    assert block.metadata["failure"]["kind"] == "empty_response"
    assert block.metadata["failure"]["retryable"] is True
    assert block.metadata["failure"]["source"] == "TimelineGenerator"


@pytest.mark.asyncio
async def test_non_dict_metadata_is_dropped(monkeypatch) -> None:
    async def fake_llm(**kwargs):
        return {"events": [{"date": "1807", "title": "t", "description": "d"}], "_metadata": "junk"}

    monkeypatch.setattr(timeline_module, "llm_json", fake_llm)
    block = await TimelineGenerator().generate(_ctx())

    assert block.status == BlockStatus.READY
    assert block.metadata == {}


def test_generator_declares_timeline_block_type() -> None:
    assert TimelineGenerator.block_type == BlockType.TIMELINE
