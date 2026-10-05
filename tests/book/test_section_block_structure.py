from __future__ import annotations

import pytest

from deeptutor.book.blocks import section as section_mod
from deeptutor.book.blocks._rag_helpers import RagLookup
from deeptutor.book.blocks.base import BlockContext
from deeptutor.book.blocks.section import (
    SectionGenerator,
    _clip,
    _fallback_outline,
    _none_label,
    _subsection_token_budget,
)
from deeptutor.book.models import (
    Block,
    BlockStatus,
    BlockType,
    Chapter,
    ExplorationReport,
    Page,
    SourceAnchor,
    SourceChunk,
)


def _make_ctx(
    params: dict | None = None,
    exploration: ExplorationReport | None = None,
    language: str = "en",
    kbs: tuple[str, ...] = ("kb-main",),
) -> BlockContext:
    chapter = Chapter(
        id="ch-1",
        title="Fourier Analysis",
        summary="Chapter summary",
        learning_objectives=["chapter objective"],
    )
    block = Block(type=BlockType.SECTION, params=dict(params or {}))
    page = Page(book_id="bk-1", chapter_id=chapter.id, blocks=[block])
    return BlockContext(
        book_id="bk-1",
        chapter=chapter,
        page=page,
        block=block,
        language=language,
        knowledge_bases=list(kbs),
        exploration=exploration,
    )


def _install_rag(monkeypatch: pytest.MonkeyPatch, lookup: RagLookup, queries: list[str]) -> None:
    async def fake_rag_lookup(*, query: str, ctx) -> RagLookup:
        queries.append(query)
        return lookup

    monkeypatch.setattr(section_mod, "optional_rag_lookup", fake_rag_lookup)


def _install_outline(monkeypatch: pytest.MonkeyPatch, outcome) -> list[dict]:
    prompts: list[dict] = []

    async def fake_llm_json(**kwargs) -> object:
        prompts.append(kwargs)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(section_mod, "llm_json", fake_llm_json)
    return prompts


def _install_text(monkeypatch: pytest.MonkeyPatch, bodies: list[str]) -> list[dict]:
    prompts: list[dict] = []

    async def fake_llm_text(**kwargs) -> str:
        prompts.append(kwargs)
        return bodies[len(prompts) - 1]

    monkeypatch.setattr(section_mod, "llm_text", fake_llm_text)
    return prompts


def test_subsection_token_budget_boundaries() -> None:
    assert _subsection_token_budget(0) == 1200
    assert _subsection_token_budget(-50) == 1200
    assert _subsection_token_budget(None) == 1200
    assert _subsection_token_budget(320) == 1360
    assert _subsection_token_budget(100000) == 8000


def test_clip_and_none_label_helpers() -> None:
    assert _clip("  hi  ", 10) == "hi"
    assert _clip("x" * 50, 10) == "x" * 10 + "…"
    assert _clip(None, 5) == ""
    assert _clip("", 5) == ""
    long = "y" * 11
    assert _clip(long, 11) == long
    assert _none_label("zh") == "(无)"
    assert _none_label("en") == "(none)"


def test_fallback_outline_structure_en_zh() -> None:
    en = _fallback_outline("Photosynthesis", ["Define rates"], 900, "en")
    assert [s["role"] for s in en["subsections"]] == ["core", "example", "application"]
    assert all(s["target_words"] == 300 for s in en["subsections"])
    assert en["subsections"][0]["focus"] == "Define rates"
    assert en["subsections"][1]["focus"] == "Photosynthesis"
    assert "Photosynthesis" in en["intro"]

    zh = _fallback_outline("光合作用", [], 100, "zh")
    assert [s["heading"] for s in zh["subsections"]] == ["核心定义", "典型例子", "应用 / 比较"]
    assert all(s["target_words"] == 220 for s in zh["subsections"])
    assert all(s["focus"] == "光合作用" for s in zh["subsections"])
    assert "光合作用" in zh["intro"]


@pytest.mark.asyncio
async def test_make_outline_normalizes_and_clamps_llm_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "intro": "i" * 700,
        "key_takeaway": "k" * 500,
        "subsections": [
            {
                "heading": "h" * 120,
                "role": "  CoRe ",
                "focus": "f" * 300,
                "target_words": 9999,
            },
            "not-a-dict",
            {"role": "core"},
            {"heading": "Keep", "role": "example", "target_words": 100},
            {"heading": "S3", "target_words": "junk"},
        ]
        + [{"heading": f"H{i}", "role": "core"} for i in range(4)],
    }
    _install_outline(monkeypatch, payload)
    outline = await SectionGenerator()._make_outline(
        ctx=_make_ctx(),
        chapter_title="Fourier Analysis",
        chapter_summary="",
        objectives=["objective one"],
        focus_topic="Fourier Analysis",
        section_role="core",
        target_words=1800,
        rag_context="",
    )

    subs = outline["subsections"]
    assert len(subs) == 4
    assert [s["heading"] for s in subs[1:]] == ["Keep", "S3", "H0"]
    first = subs[0]
    assert first["heading"] == "h" * 80 + "…"
    assert first["role"] == "core"
    assert first["focus"] == "f" * 240 + "…"
    assert first["target_words"] == 520
    assert subs[1]["target_words"] == 160
    assert subs[2]["target_words"] == 320
    assert outline["intro"] == "i" * 600 + "…"
    assert outline["key_takeaway"] == "k" * 400 + "…"

    _install_outline(
        monkeypatch,
        {"subsections": [{"heading": f"H{i}", "role": "core"} for i in range(7)]},
    )
    capped = await SectionGenerator()._make_outline(
        ctx=_make_ctx(),
        chapter_title="Fourier Analysis",
        chapter_summary="",
        objectives=[],
        focus_topic="Fourier Analysis",
        section_role="core",
        target_words=1800,
        rag_context="",
    )
    assert [s["heading"] for s in capped["subsections"]] == ["H0", "H1", "H2", "H3", "H4", "H5"]


@pytest.mark.asyncio
async def test_make_outline_falls_back_on_invalid_llm_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _make_ctx()
    expected = _fallback_outline("Fourier Analysis", ["chapter objective"], 1800, "en")
    for bad in ["nope", None, 42, {}, {"subsections": []}, {"subsections": "many"}]:
        _install_outline(monkeypatch, bad)
        outline = await SectionGenerator()._make_outline(
            ctx=ctx,
            chapter_title="Fourier Analysis",
            chapter_summary="",
            objectives=["chapter objective"],
            focus_topic="Fourier Analysis",
            section_role="core",
            target_words=1800,
            rag_context="",
        )
        assert outline == expected
    _install_outline(monkeypatch, RuntimeError("llm down"))
    outline = await SectionGenerator()._make_outline(
        ctx=ctx,
        chapter_title="Fourier Analysis",
        chapter_summary="",
        objectives=["chapter objective"],
        focus_topic="Fourier Analysis",
        section_role="core",
        target_words=1800,
        rag_context="",
    )
    assert outline == expected


@pytest.mark.asyncio
async def test_generate_happy_path_builds_section_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queries: list[str] = []
    rag = RagLookup(
        text="rag evidence",
        used=True,
        anchors=[SourceAnchor(kind="kb", kb_name="kb-main", ref="doc-1", snippet="rag snippet")],
    )
    _install_rag(monkeypatch, rag, queries)
    _install_outline(
        monkeypatch,
        {
            "intro": "Section intro",
            "key_takeaway": "Take away",
            "subsections": [
                {
                    "heading": "Why transform",
                    "role": "CORE",
                    "focus": "motivation",
                    "target_words": 400,
                },
                {"heading": "Worked example", "role": "example"},
            ],
        },
    )
    bodies = ["### Why transform\n\nAlready headed.", "Plain body."]
    text_prompts = _install_text(monkeypatch, bodies)
    exploration = ExplorationReport(
        chunks=[
            SourceChunk(
                chunk_id="c1",
                source="kb",
                kb_name="kb-main",
                ref="doc-1",
                text="fourier analysis ground truth",
            ),
            SourceChunk(
                chunk_id="c2",
                source="notebook",
                ref="rec-9",
                text="fourier notes from user notebook",
            ),
        ]
    )
    ctx = _make_ctx(exploration=exploration)
    out = await SectionGenerator().generate(ctx)

    assert out.status is BlockStatus.READY
    assert out.error == ""
    assert "failure" not in out.metadata
    assert queries == ["Fourier Analysis: Fourier Analysis"]
    payload = out.payload
    assert payload["format"] == "section"
    assert payload["intro"] == "Section intro"
    assert payload["key_takeaway"] == "Take away"
    assert payload["focus"] == "Fourier Analysis"
    assert payload["role"] == "core"
    subs = payload["subsections"]
    assert len(subs) == 2
    assert [s["heading"] for s in subs] == ["Why transform", "Worked example"]
    assert subs[0]["role"] == "core"
    assert subs[0]["focus"] == "motivation"
    assert subs[0]["target_words"] == 400
    assert subs[1]["role"] == "example"
    assert subs[1]["focus"] == ""
    assert subs[1]["target_words"] == 320
    assert subs[0]["body"] == "### Why transform\n\nAlready headed."
    assert subs[1]["body"] == "### Worked example\n\nPlain body."
    assert "Section intro" in text_prompts[0]["user_prompt"]
    assert "Worked example" in text_prompts[1]["user_prompt"]
    assert out.metadata["subsection_count"] == 2
    assert out.metadata["outline_target_words"] == 1800
    assert out.metadata["used_rag"] is True
    assert out.metadata["kb"] == "kb-main"
    assert [(a.kind, a.ref) for a in out.source_anchors] == [("kb", "doc-1"), ("notebook", "rec-9")]
    assert out.source_anchors[1].kb_name == "kb-main"
    assert out.source_anchors[1].snippet == "fourier notes from user notebook"


@pytest.mark.asyncio
async def test_generate_section_block_roundtrips_through_pydantic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_rag(monkeypatch, RagLookup(), [])
    _install_outline(
        monkeypatch,
        {
            "intro": "intro",
            "key_takeaway": "takeaway",
            "subsections": [{"heading": "Sub A", "role": "core", "target_words": 300}],
        },
    )
    _install_text(monkeypatch, ["### Sub A\n\nBody text."])
    out = await SectionGenerator().generate(_make_ctx())

    restored = Block.model_validate(out.model_dump(mode="json"))
    assert restored.payload == out.payload
    assert restored.source_anchors == out.source_anchors
    assert restored.status is BlockStatus.READY
    assert restored.metadata["subsection_count"] == 1
    assert list(restored.payload["subsections"][0].keys()) == [
        "heading",
        "role",
        "focus",
        "body",
        "target_words",
    ]


@pytest.mark.asyncio
async def test_generate_params_override_chapter_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queries: list[str] = []
    _install_rag(monkeypatch, RagLookup(), queries)
    outline_prompts = _install_outline(
        monkeypatch,
        {
            "intro": "i",
            "key_takeaway": "k",
            "subsections": [{"heading": "S", "role": "core"}],
        },
    )
    _install_text(monkeypatch, ["### S\n\nBody."])
    params = {
        "chapter_title": "Custom Title",
        "chapter_summary": "Custom summary",
        "objectives": ["o1", "o2"],
        "focus": "custom focus",
        "role": "intro",
        "target_words": 2400,
    }
    out = await SectionGenerator().generate(_make_ctx(params=params))

    assert queries == ["Custom Title: custom focus"]
    prompt = outline_prompts[0]["user_prompt"]
    assert "Custom Title" in prompt
    assert "Custom summary" in prompt
    assert "custom focus" in prompt
    assert "- o1" in prompt and "- o2" in prompt
    assert out.payload["focus"] == "custom focus"
    assert out.payload["role"] == "intro"
    assert out.metadata["outline_target_words"] == 2400


@pytest.mark.asyncio
async def test_generate_empty_llm_outline_falls_back_and_stays_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_rag(monkeypatch, RagLookup(), [])
    _install_outline(monkeypatch, {"intro": "i", "subsections": []})
    _install_text(
        monkeypatch,
        [
            "### Core idea\n\nB1.",
            "### Worked example\n\nB2.",
            "### Applications & contrasts\n\nB3.",
        ],
    )

    out = await SectionGenerator().generate(_make_ctx())
    assert out.status is BlockStatus.READY
    assert out.metadata["subsection_count"] == 3
    assert [s["heading"] for s in out.payload["subsections"]] == [
        "Core idea",
        "Worked example",
        "Applications & contrasts",
    ]
    assert out.payload["intro"].startswith("This section unpacks")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text_outcome", "expected_kind", "expected_fragment"),
    [
        (RuntimeError("boom"), "provider_error", "subsection content"),
        ("   ", "empty_response", "no visible subsection"),
    ],
)
async def test_generate_subsection_llm_failure_marks_block_error(
    monkeypatch: pytest.MonkeyPatch,
    text_outcome: object,
    expected_kind: str,
    expected_fragment: str,
) -> None:
    _install_rag(monkeypatch, RagLookup(), [])
    _install_outline(
        monkeypatch,
        {"subsections": [{"heading": "S", "role": "core"}]},
    )

    async def fake_llm_text(**kwargs) -> str:
        if isinstance(text_outcome, Exception):
            raise text_outcome
        return text_outcome

    monkeypatch.setattr(section_mod, "llm_text", fake_llm_text)
    out = await SectionGenerator().generate(_make_ctx())

    assert out.status is BlockStatus.ERROR
    assert expected_fragment in out.error
    assert out.payload == {}
    assert out.metadata["failure"]["kind"] == expected_kind
    assert out.metadata["failure"]["retryable"] is True


@pytest.mark.asyncio
async def test_generate_invalid_target_words_param_marks_block_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_rag(monkeypatch, RagLookup(), [])
    out = await SectionGenerator().generate(_make_ctx(params={"target_words": "abc"}))
    assert out.status is BlockStatus.ERROR
    assert "failure" in out.metadata
    assert out.metadata["failure"]["kind"] == "generator_error"


@pytest.mark.asyncio
async def test_fill_subsection_selects_matching_chunks_and_prefixes_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks = [
        SourceChunk(chunk_id="c0", ref="r0", text="totally unrelated alpha"),
        SourceChunk(chunk_id="c1", ref="r1", text="momentum conservation basics here"),
        SourceChunk(chunk_id="c2", ref="r2", text="momentum and impulse examples"),
        SourceChunk(chunk_id="c3", ref="r3", text="momentum deep dive"),
        SourceChunk(chunk_id="c4", ref="r4", text="momentum fourth doc"),
    ]
    captured: list[str] = []

    async def fake_llm_text(**kwargs) -> str:
        captured.append(kwargs["user_prompt"])
        return "body text"

    monkeypatch.setattr(section_mod, "llm_text", fake_llm_text)
    gen = SectionGenerator()
    sub = {"heading": "Momentum", "role": "core", "focus": "impulse", "target_words": 300}

    body = await gen._fill_subsection(
        ctx=_make_ctx(),
        chapter_title="Physics",
        section_focus="momentum",
        outline_intro="intro line",
        sub=sub,
        chunks=chunks,
    )
    assert body == "### Momentum\n\nbody text"
    assert "momentum conservation basics" in captured[0]
    assert "momentum deep dive" in captured[0]
    assert "unrelated alpha" not in captured[0]
    assert "intro line" in captured[0]

    unrelated = [
        SourceChunk(chunk_id="u0", ref="u0", text="unrelated one"),
        SourceChunk(chunk_id="u1", ref="u1", text="unrelated two"),
        SourceChunk(chunk_id="u2", ref="u2", text="unrelated three"),
    ]
    await gen._fill_subsection(
        ctx=_make_ctx(),
        chapter_title="Physics",
        section_focus="momentum",
        outline_intro="intro line",
        sub=sub,
        chunks=unrelated,
    )
    assert "unrelated one" in captured[1]
    assert "unrelated two" in captured[1]
    assert "unrelated three" not in captured[1]
