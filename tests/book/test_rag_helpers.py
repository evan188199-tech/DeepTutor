"""Contract tests for ``deeptutor.book.blocks._rag_helpers``.

``optional_rag_lookup`` is the best-effort retrieval helper shared by every
block generator. These tests pin its input normalisation (blank query), the
local exploration-chunk path, the live ``rag_search`` fallback, and every
empty-result / exception degradation branch — with the retrieval layer fully
mocked, so nothing here needs a service or a real KB.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.book.blocks._rag_helpers import (
    RagLookup,
    _coerce_anchors,
    optional_rag_lookup,
)
from deeptutor.book.models import SourceChunk


class _StubCtx:
    """Minimal stand-in for ``BlockContext`` — only what the helper reads."""

    def __init__(
        self,
        *,
        chunks: list[SourceChunk] | None = None,
        chunk_error: Exception | None = None,
        rag_enabled: bool = True,
        knowledge_bases: list[str] | None = None,
    ) -> None:
        self._chunks = chunks or []
        self._chunk_error = chunk_error
        self.rag_enabled = rag_enabled
        self.knowledge_bases = knowledge_bases if knowledge_bases is not None else ["my-kb"]

    @property
    def primary_kb(self) -> str | None:
        return self.knowledge_bases[0] if self.knowledge_bases else None

    def relevant_chunks(self, query: str, *, limit: int = 6) -> list[SourceChunk]:
        if self._chunk_error is not None:
            raise self._chunk_error
        return self._chunks[:limit]


def _install_live_rag(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: Any = None,
    error: Exception | None = None,
    provider: str = "lightrag",
    resolve_error: Exception | None = None,
) -> list[dict[str, Any]]:
    """Patch the lazily-imported live-RAG collaborators; return the call log."""
    calls: list[dict[str, Any]] = []

    def fake_resolve_kb(kb_ref: str, *, require_write: bool = False) -> Any:
        if resolve_error is not None:
            raise resolve_error
        return SimpleNamespace(base_dir=f"/data/kbs/{kb_ref}", name=kb_ref)

    def fake_resolve_bound_provider(base_dir: str, kb_name: str | None) -> str:
        return provider

    async def fake_rag_search(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if error is not None:
            raise error
        return result

    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_kb", fake_resolve_kb)
    monkeypatch.setattr(
        "deeptutor.services.rag.provider_binding.resolve_bound_provider",
        fake_resolve_bound_provider,
    )
    monkeypatch.setattr("deeptutor.tools.rag_tool.rag_search", fake_rag_search)
    return calls


def _assert_empty(lookup: RagLookup) -> None:
    assert lookup.text == ""
    assert lookup.anchors == []
    assert lookup.used is False


# ── Input normalisation ──────────────────────────────────────────────────────


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
@pytest.mark.asyncio
async def test_blank_query_returns_unused_lookup_without_touching_ctx(query: str) -> None:
    class _ExplodingCtx:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"blank query must not touch ctx.{name}")

    lookup = await optional_rag_lookup(query=query, ctx=_ExplodingCtx())

    _assert_empty(lookup)


# ── Step 1: local exploration chunks ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_local_chunks_build_bullets_and_anchors() -> None:
    chunks = [
        SourceChunk(text="Chunk one", source="kb", kb_name="expl-kb", ref="doc-1"),
        SourceChunk(text="Chunk two", chunk_id="ch-2"),  # exercises every fallback
    ]
    # rag disabled on purpose: a satisfied local sweep must not need live RAG.
    ctx = _StubCtx(chunks=chunks, rag_enabled=False)

    lookup = await optional_rag_lookup(query="fourier transform", ctx=ctx)

    assert lookup.used is True
    assert lookup.text == "- Chunk one\n\n- Chunk two"
    assert [a.kind for a in lookup.anchors] == ["kb", "kb"]
    first, second = lookup.anchors
    assert (first.kb_name, first.ref, first.snippet) == ("expl-kb", "doc-1", "Chunk one")
    # empty chunk fields fall back: kb_name -> ctx.primary_kb, ref -> chunk_id.
    assert second.kb_name == "my-kb"
    assert second.ref == "ch-2"
    assert second.snippet == "Chunk two"


@pytest.mark.asyncio
async def test_local_chunks_with_only_empty_text_fall_through_to_live_rag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _StubCtx(chunks=[SourceChunk(text="   ", ref="doc-1")])
    calls = _install_live_rag(monkeypatch, result={"answer": "live answer"})

    lookup = await optional_rag_lookup(query="topic", ctx=ctx)

    assert lookup.used is True
    assert lookup.text == "live answer"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_missing_relevant_chunks_method_falls_back_to_live_rag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A ctx without the BookEngine-v2 exploration hook raises AttributeError,
    # which must be swallowed, not propagated.
    ctx = SimpleNamespace(rag_enabled=True, primary_kb="my-kb")
    calls = _install_live_rag(monkeypatch, result={"answer": "live answer"})

    lookup = await optional_rag_lookup(query="topic", ctx=ctx)

    assert lookup.used is True
    assert lookup.text == "live answer"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_relevant_chunks_generic_failure_falls_back_to_live_rag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _StubCtx(chunk_error=RuntimeError("exploration sweep unavailable"))
    calls = _install_live_rag(monkeypatch, result={"answer": "live answer"})

    lookup = await optional_rag_lookup(query="topic", ctx=ctx)

    assert lookup.used is True
    assert lookup.text == "live answer"
    assert len(calls) == 1


# ── Step 2: gating on rag_enabled / primary_kb ────────────────────────────────


@pytest.mark.parametrize(
    ("rag_enabled", "knowledge_bases"),
    [(False, ["my-kb"]), (True, [])],
    ids=["rag-disabled", "no-primary-kb"],
)
@pytest.mark.asyncio
async def test_rag_gate_blocks_live_search(
    rag_enabled: bool, knowledge_bases: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _StubCtx(rag_enabled=rag_enabled, knowledge_bases=knowledge_bases)
    calls = _install_live_rag(monkeypatch, result={"answer": "must not be reached"})

    lookup = await optional_rag_lookup(query="topic", ctx=ctx)

    _assert_empty(lookup)
    assert calls == []


# ── Step 2: provider short-circuit and resolution failure ─────────────────────


@pytest.mark.parametrize("provider", ["pageindex", "pageindex-oss"])
@pytest.mark.asyncio
async def test_pageindex_provider_short_circuits_live_search(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _StubCtx()
    calls = _install_live_rag(monkeypatch, provider=provider, result={"answer": "no"})

    lookup = await optional_rag_lookup(query="topic", ctx=ctx)

    _assert_empty(lookup)
    assert calls == []


@pytest.mark.asyncio
async def test_provider_resolution_failure_still_attempts_live_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _StubCtx()
    calls = _install_live_rag(
        monkeypatch,
        resolve_error=RuntimeError("kb metadata unreadable"),
        result={"answer": "live answer"},
    )

    lookup = await optional_rag_lookup(query="topic", ctx=ctx)

    assert lookup.used is True
    assert lookup.text == "live answer"
    assert len(calls) == 1


# ── Step 2: live search degradation branches ──────────────────────────────────


@pytest.mark.asyncio
async def test_rag_search_exception_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _StubCtx()
    _install_live_rag(monkeypatch, error=RuntimeError("index unreachable"))

    lookup = await optional_rag_lookup(query="topic", ctx=ctx)

    _assert_empty(lookup)


@pytest.mark.asyncio
async def test_non_dict_result_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _StubCtx()
    _install_live_rag(monkeypatch, result="raw text is not a payload")

    lookup = await optional_rag_lookup(query="topic", ctx=ctx)

    _assert_empty(lookup)


@pytest.mark.parametrize(
    "result",
    [
        {"answer": "RAG search failed.", "error_type": "provider_error"},
        {"answer": "needs re-index", "needs_reindex": True},
    ],
    ids=["error-type", "needs-reindex"],
)
@pytest.mark.asyncio
async def test_inband_failure_flags_return_empty(
    result: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # RAGService reports failure in-band; the message must never be mistaken
    # for retrieved evidence.
    ctx = _StubCtx()
    _install_live_rag(monkeypatch, result=result)

    lookup = await optional_rag_lookup(query="topic", ctx=ctx)

    _assert_empty(lookup)


@pytest.mark.asyncio
async def test_successful_result_builds_text_and_anchors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _StubCtx()
    _install_live_rag(
        monkeypatch,
        result={
            "answer": "  synthesised answer  ",
            "sources": [{"id": "doc-1", "text": "evidence one"}],
        },
    )

    lookup = await optional_rag_lookup(query="topic", ctx=ctx)

    assert lookup.used is True
    assert lookup.text == "synthesised answer"
    assert len(lookup.anchors) == 1
    anchor = lookup.anchors[0]
    assert (anchor.kind, anchor.ref, anchor.snippet) == ("kb", "doc-1", "evidence one")
    # anchors with no kb_name are backfilled from the primary KB.
    assert anchor.kb_name == "my-kb"


@pytest.mark.asyncio
async def test_empty_answer_and_sources_keep_lookup_unused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _StubCtx()
    _install_live_rag(monkeypatch, result={"answer": "   ", "sources": []})

    lookup = await optional_rag_lookup(query="topic", ctx=ctx)

    _assert_empty(lookup)


# ── _coerce_anchors contract ──────────────────────────────────────────────────


def test_coerce_anchors_none_and_junk_entries_yield_empty() -> None:
    assert _coerce_anchors(None) == []
    assert _coerce_anchors([]) == []
    assert _coerce_anchors(["not-a-dict", 42, None]) == []


def test_coerce_anchors_ref_and_snippet_fallbacks() -> None:
    anchors = _coerce_anchors(
        [
            {"doc_id": "d-1", "snippet": "via doc_id/snippet"},
            {"path": "p/2", "content": "via path/content"},
            {"source": "s-3", "text": "via source/text"},
            {"kb": "named-kb"},
        ]
    )

    assert [a.ref for a in anchors] == ["d-1", "p/2", "s-3", ""]
    assert [a.snippet for a in anchors] == [
        "via doc_id/snippet",
        "via path/content",
        "via source/text",
        "",
    ]
    assert [a.kb_name for a in anchors] == ["", "", "", "named-kb"]
    assert all(a.kind == "kb" for a in anchors)


def test_coerce_anchors_caps_at_six_sources() -> None:
    sources = [{"id": f"doc-{i}", "text": f"snippet {i}"} for i in range(9)]

    anchors = _coerce_anchors(sources)

    assert len(anchors) == 6
    assert [a.ref for a in anchors] == [f"doc-{i}" for i in range(6)]


def test_coerce_anchors_truncates_oversized_fields() -> None:
    anchors = _coerce_anchors(
        [
            {
                "id": "x" * 500,
                "text": "y" * 500,
                "kb_name": "z" * 500,
            }
        ]
    )

    assert len(anchors) == 1
    assert len(anchors[0].ref) == 200
    assert len(anchors[0].snippet) == 300
    assert len(anchors[0].kb_name) == 120
