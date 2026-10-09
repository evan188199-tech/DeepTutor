"""FigureGenerator (deeptutor/book/blocks/figure.py) contract + degradation branches.

Weak-top100 #91: the static-figure block wraps VisualizePipeline with
``render_mode="figure"``, validates the draft with the deterministic local
checker, spends one targeted repair call on failure, and must raise
``GenerationFailure`` (never a broken payload) when the figure still fails.

All tests are offline: the pipeline is faked, validation runs locally, and
prompt bundles are read from the repo.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.book.blocks.base import (
    BlockContext,
    GenerationFailure,
    get_block_registry,
)
from deeptutor.book.blocks.figure import FigureGenerator
from deeptutor.book.models import Block, BlockStatus, BlockType, Chapter, Page

SVG_OK = '<svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="40" fill="blue" /></svg>'
SVG_NO_VIEWBOX = '<svg width="100"><circle cx="50" cy="50" r="40" /></svg>'
MERMAID_OK = "flowchart TD\n    A[Start] --> B[End]"
CHARTJS_OK = '{"type": "bar", "data": {"labels": ["a"], "datasets": []}}'


def _make_ctx(params=None, *, language="en", summary="How plants convert light into energy.", objectives=None):
    chapter = Chapter(
        title="Photosynthesis",
        summary=summary,
        learning_objectives=objectives
        if objectives is not None
        else ["Explain the light reactions", "Describe the Calvin cycle"],
    )
    page = Page(book_id="book-1", chapter_id=chapter.id, title=chapter.title)
    block = Block(type=BlockType.FIGURE, params=dict(params or {}))
    return BlockContext(book_id="book-1", chapter=chapter, page=page, block=block, language=language)


def _analysis(render_type="svg", description="a diagram", chart_type="flowchart"):
    from deeptutor.agents.visualize.models import VisualizationAnalysis

    return VisualizationAnalysis(
        render_type=render_type,
        description=description,
        chart_type=chart_type,
    )


def _review(code, changed=False, notes="ok"):
    from deeptutor.agents.visualize.models import ReviewResult

    return ReviewResult(optimized_code=code, changed=changed, review_notes=notes)


def _install_llm_config(monkeypatch, api_key):
    import deeptutor.services.llm.config as config_module

    monkeypatch.setattr(
        config_module,
        "get_llm_config",
        lambda: SimpleNamespace(
            api_key=api_key,
            base_url="https://llm.example.invalid",
            api_version="v2024",
        ),
    )


def _install_pipeline(monkeypatch, *, analysis, codes, reviews, analysis_exc=None):
    import deeptutor.agents.visualize.pipeline as pipeline_module

    rec = SimpleNamespace(init_kwargs=None, analysis_calls=[], code_calls=[], repair_calls=[])

    class _FakePipeline:
        def __init__(self, *, api_key, base_url, api_version, language):
            rec.init_kwargs = {
                "api_key": api_key,
                "base_url": base_url,
                "api_version": api_version,
                "language": language,
            }

        async def run_analysis(self, *, user_input, history_context, render_mode, attachments=None):
            rec.analysis_calls.append(
                {
                    "user_input": user_input,
                    "history_context": history_context,
                    "render_mode": render_mode,
                }
            )
            if analysis_exc is not None:
                raise analysis_exc
            return analysis

        async def run_code_generation(self, *, user_input, history_context, analysis):
            rec.code_calls.append({"user_input": user_input, "history_context": history_context})
            return codes[min(len(rec.code_calls) - 1, len(codes) - 1)]

        async def run_repair(self, *, user_input, analysis, code, error):
            rec.repair_calls.append({"code": code, "error": error})
            return reviews[min(len(rec.repair_calls) - 1, len(reviews) - 1)]

    monkeypatch.setattr(pipeline_module, "VisualizePipeline", _FakePipeline)
    return rec


def test_figure_generator_registered_for_block_type():
    assert FigureGenerator.block_type is BlockType.FIGURE
    gen = get_block_registry().get(BlockType.FIGURE)
    assert isinstance(gen, FigureGenerator)


@pytest.mark.asyncio
async def test_happy_path_valid_svg_skips_repair(monkeypatch):
    _install_llm_config(monkeypatch, "sk-single")
    rec = _install_pipeline(monkeypatch, analysis=_analysis(), codes=[SVG_OK], reviews=[])

    block = await FigureGenerator().generate(_make_ctx())

    assert block.status is BlockStatus.READY
    assert block.error == ""
    assert block.payload == {
        "render_type": "svg",
        "code": {"language": "svg", "content": SVG_OK},
        "description": "a diagram",
        "chart_type": "flowchart",
    }
    assert block.metadata["review_changed"] is False
    assert block.metadata["review_notes"] == "Passed local validation."
    assert block.source_anchors == []
    assert "failure" not in block.metadata
    assert rec.repair_calls == []
    assert rec.analysis_calls[0]["render_mode"] == "figure"
    assert rec.init_kwargs == {
        "api_key": "sk-single",
        "base_url": "https://llm.example.invalid",
        "api_version": "v2024",
        "language": "en",
    }


@pytest.mark.asyncio
async def test_prompt_context_includes_chapter_summary_and_objectives(monkeypatch):
    _install_llm_config(monkeypatch, "sk")
    rec = _install_pipeline(monkeypatch, analysis=_analysis(), codes=[SVG_OK], reviews=[])

    await FigureGenerator().generate(_make_ctx())

    call = rec.analysis_calls[0]
    assert "How plants convert light into energy." in call["history_context"]
    assert "Learning objectives:" in call["history_context"]
    assert "- Explain the light reactions" in call["history_context"]
    assert "- Describe the Calvin cycle" in call["history_context"]
    assert 'for the chapter "Photosynthesis"' in call["user_input"]
    assert "diagram figure" in call["user_input"]


@pytest.mark.asyncio
async def test_params_override_chapter_fields_and_add_focus_clause(monkeypatch):
    _install_llm_config(monkeypatch, "sk")
    rec = _install_pipeline(monkeypatch, analysis=_analysis(), codes=[SVG_OK], reviews=[])
    ctx = _make_ctx(
        {
            "chapter_title": "Custom Title",
            "chapter_summary": "Custom summary.",
            "objectives": ["O1"],
            "variant": "chart",
            "focus": "leaf anatomy",
        }
    )

    await FigureGenerator().generate(ctx)

    call = rec.analysis_calls[0]
    assert 'for the chapter "Custom Title"' in call["user_input"]
    assert "chart figure" in call["user_input"]
    assert " focusing on leaf anatomy" in call["user_input"]
    assert "Custom summary." in call["history_context"]
    assert "- O1" in call["history_context"]
    assert "How plants convert light into energy." not in call["history_context"]


@pytest.mark.asyncio
async def test_blank_chapter_context_omits_history_and_focus(monkeypatch):
    _install_llm_config(monkeypatch, "sk")
    rec = _install_pipeline(monkeypatch, analysis=_analysis(), codes=[SVG_OK], reviews=[])
    ctx = _make_ctx(summary="", objectives=[], language="en")

    await FigureGenerator().generate(ctx)

    call = rec.analysis_calls[0]
    assert call["history_context"] == ""
    assert " focusing on" not in call["user_input"]
    assert "diagram figure" in call["user_input"]


@pytest.mark.asyncio
async def test_local_validation_failure_triggers_single_repair(monkeypatch):
    _install_llm_config(monkeypatch, "sk")
    rec = _install_pipeline(
        monkeypatch,
        analysis=_analysis(),
        codes=[SVG_NO_VIEWBOX],
        reviews=[_review(SVG_OK, changed=True, notes="added viewBox")],
    )

    block = await FigureGenerator().generate(_make_ctx())

    assert block.status is BlockStatus.READY
    assert block.payload["code"]["content"] == SVG_OK
    assert block.payload["render_type"] == "svg"
    assert block.metadata["review_changed"] is True
    assert block.metadata["review_notes"] == "added viewBox"
    assert len(rec.analysis_calls) == 1
    assert len(rec.code_calls) == 1
    assert len(rec.repair_calls) == 1
    assert rec.repair_calls[0]["code"] == SVG_NO_VIEWBOX
    assert "viewBox" in rec.repair_calls[0]["error"]


@pytest.mark.asyncio
async def test_invalid_initial_code_can_still_be_repaired(monkeypatch):
    _install_llm_config(monkeypatch, "sk")
    rec = _install_pipeline(
        monkeypatch,
        analysis=_analysis(),
        codes=[""],
        reviews=[_review(SVG_OK, changed=True, notes="rebuilt the figure")],
    )

    block = await FigureGenerator().generate(_make_ctx())

    assert block.status is BlockStatus.READY
    assert block.payload["code"] == {"language": "svg", "content": SVG_OK}
    assert rec.repair_calls[0]["error"] == "Generated code is empty."


@pytest.mark.asyncio
async def test_repair_output_still_invalid_raises_generation_failure(monkeypatch):
    _install_llm_config(monkeypatch, "sk")
    _install_pipeline(
        monkeypatch,
        analysis=_analysis(),
        codes=[SVG_NO_VIEWBOX],
        reviews=[_review("", changed=True, notes="gave up")],
    )

    with pytest.raises(GenerationFailure) as excinfo:
        await FigureGenerator()._generate(_make_ctx())

    assert "figure failed validation after repair" in str(excinfo.value)


@pytest.mark.asyncio
async def test_failed_repair_marks_block_error_with_failure_metadata(monkeypatch):
    _install_llm_config(monkeypatch, "sk")
    _install_pipeline(
        monkeypatch,
        analysis=_analysis(),
        codes=[SVG_NO_VIEWBOX],
        reviews=[_review("", changed=True, notes="gave up")],
    )

    block = await FigureGenerator().generate(_make_ctx())

    assert block.status is BlockStatus.ERROR
    assert "figure failed validation after repair" in block.error
    failure = block.metadata["failure"]
    assert failure["kind"] == "generator_error"
    assert failure["retryable"] is True
    assert failure["source"] == "FigureGenerator"
    assert block.payload == {}


@pytest.mark.asyncio
async def test_pipeline_exception_wrapped_as_generation_failure(monkeypatch):
    _install_llm_config(monkeypatch, "sk")
    _install_pipeline(
        monkeypatch,
        analysis=_analysis(),
        codes=[],
        reviews=[],
        analysis_exc=RuntimeError("boom"),
    )

    with pytest.raises(GenerationFailure) as excinfo:
        await FigureGenerator()._generate(_make_ctx())

    assert "figure generation failed: boom" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, RuntimeError)


@pytest.mark.asyncio
async def test_missing_pipeline_symbol_degrades_to_generation_failure(monkeypatch):
    _install_llm_config(monkeypatch, "sk")
    import deeptutor.agents.visualize.pipeline as pipeline_module

    monkeypatch.delattr(pipeline_module, "VisualizePipeline")

    with pytest.raises(GenerationFailure) as excinfo:
        await FigureGenerator()._generate(_make_ctx())

    assert "figure generation failed" in str(excinfo.value)


@pytest.mark.asyncio
async def test_missing_prompt_bundle_raises_runtime_error_unwrapped(monkeypatch):
    import deeptutor.book.blocks._prompts as prompts_module

    class _EmptyManager:
        def load_prompts(self, **kwargs):
            return {}

    monkeypatch.setattr(prompts_module, "get_prompt_manager", lambda: _EmptyManager())

    with pytest.raises(RuntimeError, match="Missing prompt bundle"):
        await FigureGenerator()._generate(_make_ctx())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "render_type,code,lang_tag",
    [
        ("mermaid", MERMAID_OK, "mermaid"),
        ("chartjs", CHARTJS_OK, "javascript"),
    ],
)
async def test_language_tag_follows_render_type(monkeypatch, render_type, code, lang_tag):
    _install_llm_config(monkeypatch, "sk")
    _install_pipeline(monkeypatch, analysis=_analysis(render_type=render_type), codes=[code], reviews=[])

    block = await FigureGenerator().generate(_make_ctx())

    assert block.status is BlockStatus.READY
    assert block.payload["render_type"] == render_type
    assert block.payload["code"]["language"] == lang_tag
    assert block.payload["code"]["content"] == code


@pytest.mark.asyncio
async def test_chinese_language_bundle_supported(monkeypatch):
    _install_llm_config(monkeypatch, "sk")
    rec = _install_pipeline(monkeypatch, analysis=_analysis(), codes=[SVG_OK], reviews=[])

    block = await FigureGenerator().generate(_make_ctx(language="zh"))

    assert block.status is BlockStatus.READY
    assert rec.init_kwargs["language"] == "zh"


@pytest.mark.asyncio
async def test_key_pool_list_reduced_to_primary_key(monkeypatch):
    _install_llm_config(monkeypatch, ["sk-b", "sk-a"])
    rec = _install_pipeline(monkeypatch, analysis=_analysis(), codes=[SVG_OK], reviews=[])

    await FigureGenerator().generate(_make_ctx())

    assert rec.init_kwargs["api_key"] == "sk-b"
