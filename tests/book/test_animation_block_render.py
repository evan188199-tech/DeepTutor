"""AnimationGenerator (book/blocks/animation.py) — render contract tests.

The animation block is the one generator that shells out to an optional
extras pipeline (Manim). These pin down, without any real rendering:

- the missing-extras degradation (fail closed with an install hint),
- brief composition: params override chapter text, chapter values fill in
  when params are absent, the history context is built from the summary
  and objectives, and an empty chapter yields an empty history,
- the artifact contract: a video artifact is preferred, a video
  ``content_type`` counts as a video marker, the first artifact is the
  fallback, and an empty artifact list leaves the URL fields blank
  instead of crashing,
- failure wrapping: a pipeline explosion becomes a ``GenerationFailure``
  (cause chained) and, through the public entry point, an ERROR block
  carrying failure metadata,
- the plumbing: quality clamping, key-pool reduction to a single key,
  language propagation, and the turn-id / attachments run contract.

Everything runs against fake pipeline modules injected into
``sys.modules`` — no Manim, LaTeX, ffmpeg or network is touched.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

import deeptutor.book.blocks.animation as animation_module
from deeptutor.book.blocks.animation import AnimationGenerator
from deeptutor.book.blocks.base import BlockContext, GenerationFailure
from deeptutor.book.models import Block, BlockStatus, BlockType, Chapter, Page

# ── fakes / helpers ──────────────────────────────────────────────────────


class _Artifact:
    """Stands in for a pydantic artifact model — only model_dump is used."""

    def __init__(self, data: dict):
        self._data = data

    def model_dump(self) -> dict:
        return dict(self._data)


def _artifact(**overrides) -> _Artifact:
    data: dict = {
        "type": "video",
        "url": "http://media.local/fourier.mp4",
        "filename": "fourier.mp4",
        "content_type": "video/mp4",
    }
    data.update(overrides)
    return _Artifact(data)


_UNSET = object()


def _pipeline_result(
    artifacts=None,
    *,
    summary_text: str | None = "The wave, explained",
    key_points: object = _UNSET,
    learning_goal: str | None = "Watch a standing wave",
    retry_attempts: int = 1,
) -> dict:
    if artifacts is None:
        artifacts = [_artifact()]
    if key_points is _UNSET:
        key_points = ["nodes", "antinodes"]
    return {
        "render_result": SimpleNamespace(artifacts=artifacts, retry_attempts=retry_attempts),
        "summary": SimpleNamespace(summary_text=summary_text, key_points=key_points),
        "analysis": SimpleNamespace(learning_goal=learning_goal),
    }


def _llm_config(**overrides) -> SimpleNamespace:
    config: dict = {
        "api_key": "sk-single",
        "base_url": "http://llm.local/v1",
        "api_version": "2024-02-01",
    }
    config.update(overrides)
    return SimpleNamespace(**config)


class _Recorder:
    def __init__(self) -> None:
        self.runs: list[dict] = []
        self.inits: list[dict] = []


def _install_fakes(
    monkeypatch,
    *,
    llm_config: SimpleNamespace | None = None,
    result: dict | None = None,
    error: Exception | None = None,
) -> _Recorder:
    """Swap the real math-animator / llm-config modules for recorders.

    The generator imports these lazily inside ``_generate``, so a
    ``sys.modules`` entry wins over whatever is installed. Returns a
    recorder holding every pipeline ``__init__`` and ``run`` call.
    """
    recorder = _Recorder()

    class _RecordingPipeline:
        def __init__(self, **kwargs):
            self.init_kwargs = kwargs
            recorder.inits.append(kwargs)

        async def run(self, **kwargs):
            recorder.runs.append(kwargs)
            if error is not None:
                raise error
            return result

    class _RequestConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    pipeline_mod = types.ModuleType("deeptutor.agents.math_animator.pipeline")
    pipeline_mod.MathAnimatorPipeline = _RecordingPipeline
    request_mod = types.ModuleType("deeptutor.agents.math_animator.request_config")
    request_mod.MathAnimatorRequestConfig = _RequestConfig
    llm_mod = types.ModuleType("deeptutor.services.llm.config")
    llm_mod.get_llm_config = lambda: llm_config or _llm_config()

    monkeypatch.setitem(sys.modules, "deeptutor.agents.math_animator.pipeline", pipeline_mod)
    monkeypatch.setitem(sys.modules, "deeptutor.agents.math_animator.request_config", request_mod)
    monkeypatch.setitem(sys.modules, "deeptutor.services.llm.config", llm_mod)
    return recorder


def _ctx(
    params: dict | None = None,
    *,
    chapter: Chapter | None = None,
    language: str = "en",
    book_id: str = "bk-1",
) -> BlockContext:
    chapter = chapter or Chapter(
        title="Fourier Series",
        summary="Decompose a signal into sines.",
        learning_objectives=["Convergence", "Orthogonality"],
    )
    block = Block(type=BlockType.ANIMATION, params=params or {})
    page = Page(book_id=book_id, chapter_id=chapter.id)
    return BlockContext(book_id=book_id, chapter=chapter, page=page, block=block, language=language)


# ── missing extras degrade ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_manim_extras_fail_closed_with_install_hint(monkeypatch) -> None:
    monkeypatch.setattr(animation_module.importlib.util, "find_spec", lambda _name: None)

    block = await AnimationGenerator().generate(_ctx())

    assert block.status is BlockStatus.ERROR
    assert "math-animator" in block.error
    assert "pip install" in block.error, "the hint must be actionable, not a bare failure"
    failure = block.metadata["failure"]
    assert failure["source"] == "AnimationGenerator"


# ── happy path / payload contract ────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_returns_video_payload_with_metadata(monkeypatch) -> None:
    recorder = _install_fakes(
        monkeypatch,
        result=_pipeline_result(
            retry_attempts=2,
            summary_text="Standing waves in 60 seconds",
            key_points=["nodes", "antinodes"],
            learning_goal="See resonance",
        ),
    )
    ctx = _ctx({"quality": "high", "style_hint": "cinematic"})

    block = await AnimationGenerator().generate(ctx)

    assert block.status is BlockStatus.READY
    assert block.error == ""
    payload = block.payload
    assert payload["render_type"] == "video"
    assert payload["video_url"] == "http://media.local/fourier.mp4"
    assert payload["filename"] == "fourier.mp4"
    assert payload["summary"] == "Standing waves in 60 seconds"
    assert payload["key_points"] == ["nodes", "antinodes"]
    assert payload["description"] == "See resonance"
    assert payload["artifacts"][0]["url"] == "http://media.local/fourier.mp4"
    assert block.source_anchors == []
    assert block.metadata["retry_attempts"] == 2
    assert block.metadata["quality"] == "high"

    (init,) = recorder.inits
    (run,) = recorder.runs
    assert init["language"] == "en"
    assert run["turn_id"] == f"book-{ctx.book_id}-{ctx.block.id}"
    assert run["attachments"] == []
    assert run["request_config"].quality == "high"
    assert run["request_config"].style_hint == "cinematic"


# ── artifact selection ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_video_typed_artifact_wins_over_earlier_non_video(monkeypatch) -> None:
    frame = _artifact(
        type="image",
        url="http://media.local/frame.png",
        filename="frame.png",
        content_type="image/png",
    )
    video = _artifact(url="http://media.local/final.mp4", filename="final.mp4")
    _install_fakes(monkeypatch, result=_pipeline_result(artifacts=[frame, video]))

    block = await AnimationGenerator().generate(_ctx())

    assert block.payload["video_url"] == "http://media.local/final.mp4"
    assert block.payload["filename"] == "final.mp4"


@pytest.mark.asyncio
async def test_video_content_type_counts_as_a_video_artifact(monkeypatch) -> None:
    frame = _artifact(type="image", url="http://media.local/frame.png", content_type="image/png")
    untyped_video = _artifact(type="", url="http://media.local/stream.mp4", filename="stream.mp4")
    _install_fakes(monkeypatch, result=_pipeline_result(artifacts=[frame, untyped_video]))

    block = await AnimationGenerator().generate(_ctx())

    assert block.payload["video_url"] == "http://media.local/stream.mp4"


@pytest.mark.asyncio
async def test_without_a_video_artifact_the_first_one_is_used(monkeypatch) -> None:
    first = _artifact(
        type="image",
        url="http://media.local/frame.png",
        filename="frame.png",
        content_type="image/png",
    )
    second = _artifact(
        type="image",
        url="http://media.local/frame2.png",
        filename="frame2.png",
        content_type="image/png",
    )
    _install_fakes(monkeypatch, result=_pipeline_result(artifacts=[first, second]))

    block = await AnimationGenerator().generate(_ctx())

    assert block.payload["video_url"] == "http://media.local/frame.png"
    assert block.payload["filename"] == "frame.png"


# ── empty states ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_artifact_list_degrades_to_blank_url_fields(monkeypatch) -> None:
    _install_fakes(monkeypatch, result=_pipeline_result(artifacts=[]))

    block = await AnimationGenerator().generate(_ctx())

    assert block.status is BlockStatus.READY
    assert block.payload["artifacts"] == []
    assert block.payload["video_url"] == ""
    assert block.payload["filename"] == ""


@pytest.mark.asyncio
async def test_absent_summary_and_key_points_degrade_to_empty_values(monkeypatch) -> None:
    _install_fakes(
        monkeypatch,
        result=_pipeline_result(summary_text=None, key_points=None, learning_goal=None),
    )

    block = await AnimationGenerator().generate(_ctx())

    assert block.status is BlockStatus.READY
    assert block.payload["summary"] == ""
    assert block.payload["key_points"] == []
    assert block.payload["description"] == ""


@pytest.mark.asyncio
async def test_empty_chapter_yields_empty_history_context(monkeypatch) -> None:
    recorder = _install_fakes(monkeypatch, result=_pipeline_result())
    bare = Chapter(title="", summary="", learning_objectives=[])

    await AnimationGenerator().generate(_ctx(None, chapter=bare))

    (run,) = recorder.runs
    assert run["history_context"] == ""
    assert "  " not in run["user_input"], "no focus clause must not leave a dangling space"


# ── brief composition ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_params_override_chapter_text_in_the_brief(monkeypatch) -> None:
    recorder = _install_fakes(monkeypatch, result=_pipeline_result())

    await AnimationGenerator().generate(
        _ctx(
            {
                "chapter_title": "Custom Title",
                "chapter_summary": "Custom summary.",
                "objectives": ["obj one", "obj two"],
                "focus": "SVD",
            }
        )
    )

    (run,) = recorder.runs
    assert "Custom Title" in run["user_input"]
    assert "focusing on SVD" in run["user_input"]
    assert "Chapter summary: Custom summary." in run["history_context"]
    assert "- obj one" in run["history_context"]
    assert "- obj two" in run["history_context"]


@pytest.mark.asyncio
async def test_missing_params_fall_back_to_the_chapter(monkeypatch) -> None:
    recorder = _install_fakes(monkeypatch, result=_pipeline_result())

    await AnimationGenerator().generate(_ctx({"objectives": []}))

    (run,) = recorder.runs
    assert "Fourier Series" in run["user_input"]
    assert "Decompose a signal into sines." in run["history_context"]
    assert "- Convergence" in run["history_context"]
    assert "- Orthogonality" in run["history_context"]
    assert "focusing on" not in run["user_input"], "an empty focus yields no clause"


@pytest.mark.asyncio
async def test_non_string_params_are_coerced_not_fatal(monkeypatch) -> None:
    """Malformed params degrade: focus/quality coerce, a null title degrades
    to the literal ``None`` (documenting today's behaviour) instead of
    crashing the block."""
    recorder = _install_fakes(monkeypatch, result=_pipeline_result())

    await AnimationGenerator().generate(
        _ctx({"focus": 42, "quality": 7, "style_hint": None, "chapter_title": None})
    )

    (run,) = recorder.runs
    assert "focusing on 42" in run["user_input"]
    assert "None" in run["user_input"]
    assert run["request_config"].quality == "medium"
    assert run["request_config"].style_hint == ""


# ── param validation ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("quality", "expected"),
    [
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("ultra", "medium"),
        ("", "medium"),
        (None, "medium"),
        (7, "medium"),
    ],
)
@pytest.mark.asyncio
async def test_quality_is_clamped_to_known_levels(
    monkeypatch, quality: object, expected: str
) -> None:
    recorder = _install_fakes(monkeypatch, result=_pipeline_result())

    block = await AnimationGenerator().generate(_ctx({"quality": quality}))

    assert block.metadata["quality"] == expected
    (run,) = recorder.runs
    assert run["request_config"].quality == expected


# ── credential plumbing ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("configured", "expected_pipeline_key"),
    [
        (["sk-a", "sk-b"], "sk-a"),
        ("sk-solo", "sk-solo"),
        ("", None),
        ([], None),
        (None, None),
    ],
)
@pytest.mark.asyncio
async def test_credential_reaches_the_pipeline_as_a_single_key(
    monkeypatch, configured: object, expected_pipeline_key: str | None
) -> None:
    """A rotated key list must never render as ``"['sk-a', 'sk-b']"`` in the
    pipeline's credential — the pool reduces to the first key at the boundary."""
    recorder = _install_fakes(
        monkeypatch, llm_config=_llm_config(api_key=configured), result=_pipeline_result()
    )

    block = await AnimationGenerator().generate(_ctx())

    assert block.status is BlockStatus.READY
    (init,) = recorder.inits
    assert init["api_key"] == expected_pipeline_key


@pytest.mark.asyncio
async def test_language_flows_into_pipeline_and_brief(monkeypatch) -> None:
    recorder = _install_fakes(monkeypatch, result=_pipeline_result())

    await AnimationGenerator().generate(_ctx(language="zh"))

    (init,) = recorder.inits
    (run,) = recorder.runs
    assert init["language"] == "zh"
    assert any("一" <= ch <= "鿿" for ch in run["user_input"]), "expected a Chinese brief"


# ── failure wrapping ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_explosion_becomes_generation_failure_with_cause(
    monkeypatch,
) -> None:
    boom = RuntimeError("manim render exploded")
    _install_fakes(monkeypatch, error=boom)

    with pytest.raises(GenerationFailure) as excinfo:
        await AnimationGenerator()._generate(_ctx())

    assert str(excinfo.value) == "animation generation failed: manim render exploded"
    assert excinfo.value.__cause__ is boom


@pytest.mark.asyncio
async def test_pipeline_explosion_marks_the_block_error_with_failure_metadata(
    monkeypatch,
) -> None:
    _install_fakes(monkeypatch, error=RuntimeError("ffmpeg vanished"))

    block = await AnimationGenerator().generate(_ctx())

    assert block.status is BlockStatus.ERROR
    assert block.error == "animation generation failed: ffmpeg vanished"
    failure = block.metadata["failure"]
    assert failure["source"] == "AnimationGenerator"
    assert failure["message"] == "animation generation failed: ffmpeg vanished"
