"""Focused coverage for the small ``book/blocks`` generator family.

Covers the zero-test modules flagged by the coverage scan — ``user_note``,
``callout``, ``timeline``, ``flash_cards``, ``deep_dive`` — plus the two
pipeline-backed visual blocks ``animation`` and ``interactive``: normal
payloads and the failure paths that surface as ``GenerationFailure``.

All LLM / pipeline / config dependencies are faked; nothing here talks to a
service or requires the optional ``math-animator`` extras.
"""

from __future__ import annotations

import importlib.util
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from deeptutor.book.blocks import (
    animation as animation_module,
)
from deeptutor.book.blocks import (
    callout as callout_module,
)
from deeptutor.book.blocks import (
    deep_dive as deep_dive_module,
)
from deeptutor.book.blocks import (
    flash_cards as flash_cards_module,
)
from deeptutor.book.blocks import (
    interactive as interactive_module,
)
from deeptutor.book.blocks import (
    timeline as timeline_module,
)
from deeptutor.book.blocks import (
    user_note as user_note_module,
)
from deeptutor.book.blocks.base import BlockContext
from deeptutor.book.models import Block, BlockStatus, BlockType, Chapter, ContentType, Page


def _ctx(
    block_type: BlockType,
    params: dict[str, Any] | None = None,
    *,
    language: str = "en",
) -> BlockContext:
    chapter = Chapter(
        id="ch_small",
        title="Small module chapter",
        summary="Chapter summary text.",
        learning_objectives=["obj one", "obj two"],
        content_type=ContentType.THEORY,
    )
    page = Page(id="pg_small", book_id="bk_small", chapter_id=chapter.id)
    block = Block(id="blk_small", type=block_type, params=params or {})
    return BlockContext(
        book_id="bk_small", chapter=chapter, page=page, block=block, language=language
    )


def _install_fake_module(monkeypatch: pytest.MonkeyPatch, name: str, **attrs: Any) -> ModuleType:
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _fake_llm_config_module(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_module(
        monkeypatch,
        "deeptutor.services.llm.config",
        get_llm_config=lambda: SimpleNamespace(
            api_key="sk-test", base_url="http://llm.test", api_version=None
        ),
    )


# ---------------------------------------------------------------------------
# user_note — passthrough, no LLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_note_passthrough_body() -> None:
    block = await user_note_module.UserNoteGenerator().generate(
        _ctx(BlockType.USER_NOTE, {"body": "  hello **world**  "})
    )

    assert block.status == BlockStatus.READY
    assert block.payload == {"format": "markdown", "body": "hello **world**", "author": "user"}


@pytest.mark.asyncio
async def test_user_note_empty_params_defaults() -> None:
    block = await user_note_module.UserNoteGenerator().generate(_ctx(BlockType.USER_NOTE))

    assert block.status == BlockStatus.READY
    assert block.payload["body"] == ""
    assert block.payload["author"] == "user"


# ---------------------------------------------------------------------------
# callout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_callout_success_uses_variant_label(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_llm_text(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "Beware of unit drift."

    monkeypatch.setattr(callout_module, "llm_text", fake_llm_text)

    block = await callout_module.CalloutGenerator().generate(
        _ctx(BlockType.CALLOUT, {"variant": "common_pitfall"})
    )

    assert block.status == BlockStatus.READY
    assert block.payload["variant"] == "common_pitfall"
    assert block.payload["label"] == "Watch Out"
    assert block.payload["body"] == "Beware of unit drift."
    assert "common_pitfall" in captured["user_prompt"]
    assert "Watch Out" in captured["user_prompt"]


@pytest.mark.asyncio
async def test_callout_zh_label_and_unknown_variant_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_llm_text(**kwargs: Any) -> str:
        return "要点内容"

    monkeypatch.setattr(callout_module, "llm_text", fake_llm_text)

    block = await callout_module.CalloutGenerator().generate(
        _ctx(BlockType.CALLOUT, {"variant": "bogus"}, language="zh")
    )

    assert block.status == BlockStatus.READY
    assert block.payload["variant"] == "bogus"
    assert block.payload["label"] == "核心要点"


@pytest.mark.asyncio
async def test_callout_empty_body_marks_block_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_llm_text(**kwargs: Any) -> str:
        return "   "

    monkeypatch.setattr(callout_module, "llm_text", fake_llm_text)

    block = await callout_module.CalloutGenerator().generate(_ctx(BlockType.CALLOUT))

    assert block.status == BlockStatus.ERROR
    assert "no visible callout content" in block.error
    assert block.metadata["failure"]["kind"] == "empty_response"


# ---------------------------------------------------------------------------
# timeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeline_success_truncates_and_drops_non_dict_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_events: list[Any] = [
        {"date": str(i), "title": f"event {i}", "description": "d" * 700} for i in range(12)
    ]
    raw_events.insert(4, "not-a-dict")

    async def fake_llm_json(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["expected_key"] == "events"
        assert kwargs["reasoning_effort"] == "none"
        return {"events": raw_events, "_metadata": {"reasoning_retry": "none"}}

    monkeypatch.setattr(timeline_module, "llm_json", fake_llm_json)

    block = await timeline_module.TimelineGenerator().generate(_ctx(BlockType.TIMELINE))

    assert block.status == BlockStatus.READY
    events = block.payload["events"]
    assert len(events) == 7  # 8-item slice minus the dropped non-dict entry
    assert all(set(event) == {"date", "title", "description"} for event in events)
    assert all(len(event["description"]) == 600 for event in events)
    assert block.metadata["reasoning_retry"] == "none"


@pytest.mark.asyncio
async def test_timeline_empty_marks_block_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_llm_json(**kwargs: Any) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(timeline_module, "llm_json", fake_llm_json)

    block = await timeline_module.TimelineGenerator().generate(_ctx(BlockType.TIMELINE))

    assert block.status == BlockStatus.ERROR
    assert "timeline events" in block.error
    assert block.metadata["failure"]["kind"] == "empty_response"


# ---------------------------------------------------------------------------
# flash_cards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flash_cards_success_clamps_count_and_cleans_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_cards: list[Any] = [
        {"front": f"q{i}", "back": f"a{i}", "hint": "h" * 400} for i in range(20)
    ]
    raw_cards.append({"front": "", "back": "orphan"})  # dropped: empty front
    raw_cards.append("junk")  # dropped: not a dict

    async def fake_llm_json(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["expected_key"] == "cards"
        return {"cards": raw_cards}

    monkeypatch.setattr(flash_cards_module, "llm_json", fake_llm_json)

    block = await flash_cards_module.FlashCardsGenerator().generate(
        _ctx(BlockType.FLASH_CARDS, {"count": 99})
    )

    assert block.status == BlockStatus.READY
    cards = block.payload["cards"]
    assert len(cards) == 8  # clamped to the upper bound
    assert cards[0] == {"front": "q0", "back": "a0", "hint": "h" * 200}
    assert all(len(card["hint"]) <= 200 for card in cards)


@pytest.mark.asyncio
async def test_flash_cards_count_floor_and_empty_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_llm_json(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"cards": [{"topic": "wrong shape"}]}

    monkeypatch.setattr(flash_cards_module, "llm_json", fake_llm_json)

    block = await flash_cards_module.FlashCardsGenerator().generate(
        _ctx(BlockType.FLASH_CARDS, {"count": 1})
    )

    assert block.status == BlockStatus.ERROR
    assert "flashcards" in block.error
    assert block.metadata["failure"]["kind"] == "empty_response"
    # The clamped floor (3) reaches the system prompt, not the raw param value.
    assert "3" in captured["system_prompt"]
    assert "1" not in captured["system_prompt"].split("with ")[1].split(" ")[0]


# ---------------------------------------------------------------------------
# deep_dive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deep_dive_success_caps_at_five_and_filters_empty_topics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw: list[Any] = [{"topic": f"topic {i}", "rationale": "r" * 400} for i in range(7)]
    raw.append({"topic": "   "})
    raw.append("junk")

    async def fake_llm_json(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["expected_key"] == "suggestions"
        return {"suggestions": raw}

    monkeypatch.setattr(deep_dive_module, "llm_json", fake_llm_json)

    block = await deep_dive_module.DeepDiveGenerator().generate(_ctx(BlockType.DEEP_DIVE))

    assert block.status == BlockStatus.READY
    suggestions = block.payload["suggestions"]
    assert len(suggestions) == 5
    assert suggestions[0]["topic"] == "topic 0"
    assert suggestions[0]["rationale"] == "r" * 300


@pytest.mark.asyncio
async def test_deep_dive_empty_marks_block_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_llm_json(**kwargs: Any) -> dict[str, Any]:
        return {"suggestions": [{"topic": "   "}]}

    monkeypatch.setattr(deep_dive_module, "llm_json", fake_llm_json)

    block = await deep_dive_module.DeepDiveGenerator().generate(_ctx(BlockType.DEEP_DIVE))

    assert block.status == BlockStatus.ERROR
    assert "suggestions" in block.error
    assert block.metadata["failure"]["kind"] == "empty_response"


# ---------------------------------------------------------------------------
# animation (pipeline-backed; math-animator extras faked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_animation_requires_optional_extras(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(animation_module.importlib.util, "find_spec", lambda name: None)

    block = await animation_module.AnimationGenerator().generate(_ctx(BlockType.ANIMATION))

    assert block.status == BlockStatus.ERROR
    assert "math-animator" in block.error


@pytest.mark.asyncio
async def test_animation_success_builds_video_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(animation_module.importlib.util, "find_spec", lambda name: object())
    _fake_llm_config_module(monkeypatch)

    class _FakeRequestConfig:
        last: "dict[str, Any] | None" = None

        def __init__(self, *, output_mode: str, quality: str, style_hint: str) -> None:
            self.output_mode = output_mode
            self.quality = quality
            self.style_hint = style_hint
            _FakeRequestConfig.last = {
                "output_mode": output_mode,
                "quality": quality,
                "style_hint": style_hint,
            }

    class _FakePipeline:
        init_kwargs: dict[str, Any] = {}
        run_kwargs: dict[str, Any] = {}

        def __init__(self, **kwargs: Any) -> None:
            _FakePipeline.init_kwargs = kwargs

        async def run(self, **kwargs: Any) -> dict[str, Any]:
            _FakePipeline.run_kwargs = kwargs
            return {
                "render_result": SimpleNamespace(
                    artifacts=[
                        SimpleNamespace(
                            model_dump=lambda: {
                                "type": "image",
                                "url": "http://img",
                                "filename": "still.png",
                                "content_type": "image/png",
                            }
                        ),
                        SimpleNamespace(
                            model_dump=lambda: {
                                "type": "video",
                                "url": "http://video",
                                "filename": "clip.mp4",
                                "content_type": "video/mp4",
                            }
                        ),
                    ],
                    retry_attempts=1,
                ),
                "summary": SimpleNamespace(summary_text="clip summary", key_points=["a", "b"]),
                "analysis": SimpleNamespace(learning_goal="learn fourier"),
            }

    _install_fake_module(
        monkeypatch,
        "deeptutor.agents.math_animator.pipeline",
        MathAnimatorPipeline=_FakePipeline,
    )
    _install_fake_module(
        monkeypatch,
        "deeptutor.agents.math_animator.request_config",
        MathAnimatorRequestConfig=_FakeRequestConfig,
    )

    block = await animation_module.AnimationGenerator().generate(
        _ctx(BlockType.ANIMATION, {"quality": "ultra", "focus": "series"})
    )

    assert block.status == BlockStatus.READY
    assert block.payload["render_type"] == "video"
    # The video artifact wins over the image one for the primary URL.
    assert block.payload["video_url"] == "http://video"
    assert block.payload["filename"] == "clip.mp4"
    assert block.payload["summary"] == "clip summary"
    assert block.payload["key_points"] == ["a", "b"]
    assert block.payload["description"] == "learn fourier"
    assert len(block.payload["artifacts"]) == 2
    assert block.metadata["quality"] == "medium"  # "ultra" is not an allowed tier
    assert block.metadata["retry_attempts"] == 1
    assert _FakeRequestConfig.last is not None
    assert _FakeRequestConfig.last["quality"] == "medium"
    assert _FakePipeline.init_kwargs["language"] == "en"
    assert _FakePipeline.run_kwargs["turn_id"] == "book-bk_small-blk_small"
    assert "focusing on series" in _FakePipeline.run_kwargs["user_input"]


@pytest.mark.asyncio
async def test_animation_pipeline_failure_marks_block_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(animation_module.importlib.util, "find_spec", lambda name: object())
    _fake_llm_config_module(monkeypatch)

    class _BoomPipeline:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def run(self, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("renderer exploded")

    _install_fake_module(
        monkeypatch, "deeptutor.agents.math_animator.pipeline", MathAnimatorPipeline=_BoomPipeline
    )
    _install_fake_module(
        monkeypatch,
        "deeptutor.agents.math_animator.request_config",
        MathAnimatorRequestConfig=lambda **kw: SimpleNamespace(**kw),
    )

    block = await animation_module.AnimationGenerator().generate(_ctx(BlockType.ANIMATION))

    assert block.status == BlockStatus.ERROR
    assert "animation generation failed" in block.error
    assert "renderer exploded" in block.error
    assert block.metadata["failure"]["kind"] == "generator_error"


# ---------------------------------------------------------------------------
# interactive (pipeline-backed; visualize extras faked)
# ---------------------------------------------------------------------------


def _install_fake_visualize(monkeypatch: pytest.MonkeyPatch, code: str, ok: bool) -> None:
    _fake_llm_config_module(monkeypatch)

    class _FakePipeline:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def run_analysis(self, **kwargs: Any) -> SimpleNamespace:
            assert kwargs["render_mode"] == "html"
            return SimpleNamespace(description="an interactive demo", chart_type="widget")

        async def run_code_generation(self, **kwargs: Any) -> str:
            assert kwargs["analysis"].description == "an interactive demo"
            return code

    def _fake_validate(text: str, mode: str) -> tuple[bool, str]:
        assert mode == "html"
        return ok, "" if ok else "missing html document tag"

    _install_fake_module(
        monkeypatch, "deeptutor.agents.visualize.pipeline", VisualizePipeline=_FakePipeline
    )
    _install_fake_module(
        monkeypatch, "deeptutor.agents.visualize.utils", validate_visualization=_fake_validate
    )


@pytest.mark.asyncio
async def test_interactive_success_returns_html_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_visualize(monkeypatch, "<html><body>demo</body></html>", ok=True)

    block = await interactive_module.InteractiveGenerator().generate(
        _ctx(BlockType.INTERACTIVE, {"interaction": "sandbox"})
    )

    assert block.status == BlockStatus.READY
    assert block.payload["render_type"] == "html"
    assert block.payload["code"] == {
        "language": "html",
        "content": "<html><body>demo</body></html>",
    }
    assert block.payload["description"] == "an interactive demo"
    assert block.payload["chart_type"] == "widget"
    assert block.metadata["review_changed"] is False


@pytest.mark.asyncio
async def test_interactive_failed_validation_marks_block_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_visualize(monkeypatch, "not html at all", ok=False)

    block = await interactive_module.InteractiveGenerator().generate(_ctx(BlockType.INTERACTIVE))

    assert block.status == BlockStatus.ERROR
    assert "interactive html failed validation" in block.error
    assert "missing html document tag" in block.error


@pytest.mark.asyncio
async def test_interactive_pipeline_failure_marks_block_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_llm_config_module(monkeypatch)

    class _BoomPipeline:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def run_analysis(self, **kwargs: Any) -> SimpleNamespace:
            raise RuntimeError("analysis blew up")

    _install_fake_module(
        monkeypatch, "deeptutor.agents.visualize.pipeline", VisualizePipeline=_BoomPipeline
    )
    _install_fake_module(
        monkeypatch,
        "deeptutor.agents.visualize.utils",
        validate_visualization=lambda code, mode: (True, ""),
    )

    block = await interactive_module.InteractiveGenerator().generate(_ctx(BlockType.INTERACTIVE))

    assert block.status == BlockStatus.ERROR
    assert "interactive generation failed" in block.error
    assert "analysis blew up" in block.error
