"""Focused unit tests for ``SmartRetriever``.

Covers the strategy selection (hint-provided vs LLM-generated queries),
the passage/source merge and ordering contract, and the degradation paths
(search failures, query-generation failure, aggregation failure).

The underlying retriever (``search`` callable) and the LLM ``complete``
function are fully mocked — no network, no product code changes.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from deeptutor.services.rag.smart_retriever import SmartRetriever

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_search(
    outcomes: dict[str, Any],
    delays: dict[str, float] | None = None,
):
    """Build a fake search callable keyed by query text.

    Each entry of ``outcomes`` maps a query to either an ``Exception``
    instance (the search fails) or a result mapping (the search succeeds).
    ``calls`` records every invocation so tests can assert the exact
    (query, kb_name) pairs and their order.
    """
    calls: list[dict[str, Any]] = []

    async def search(**kwargs: Any) -> dict[str, Any]:
        query = kwargs["query"]
        calls.append({"query": query, "kb_name": kwargs["kb_name"]})
        if delays:
            await asyncio.sleep(delays[query])
        outcome = outcomes[query]
        if isinstance(outcome, Exception):
            raise outcome
        return dict(outcome)

    search.calls = calls  # type: ignore[attr-defined]
    return search


def _patch_complete(
    monkeypatch: pytest.MonkeyPatch,
    behaviour: str | Exception | list[str | Exception],
) -> list[dict[str, Any]]:
    """Replace ``deeptutor.services.llm.complete`` (resolved at call time by
    ``smart_retriever``) with a recording stub.

    ``behaviour`` may be a single ``str`` (every call returns it), a single
    ``Exception`` instance (every call raises it), or a list consumed in
    call order (the last element repeats once exhausted). Returns the call
    log.
    """
    script = list(behaviour) if isinstance(behaviour, list) else [behaviour]
    calls: list[dict[str, Any]] = []

    async def fake_complete(prompt: str, **kwargs: Any) -> str:
        calls.append({"prompt": prompt, **kwargs})
        outcome = script[min(len(calls) - 1, len(script) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr("deeptutor.services.llm.complete", fake_complete)
    return calls


# ---------------------------------------------------------------------------
# Strategy selection: hint-provided vs LLM-generated queries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_hints_skip_llm_query_generation(monkeypatch: pytest.MonkeyPatch):
    """When query hints are supplied, no LLM query generation happens and
    each hint drives exactly one search."""
    llm_calls = _patch_complete(monkeypatch, "SYNTHESIS")
    search = _make_search({"hint-a": {"content": "pa", "query": "hint-a", "provider": "p1"}})

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("_generate_queries must not run when hints are given")

    retriever = SmartRetriever(search)
    monkeypatch.setattr(retriever, "_generate_queries", _boom)

    result = await retriever.retrieve("ctx", "kb", query_hints=["hint-a"])

    assert search.calls == [{"query": "hint-a", "kb_name": "kb"}]
    assert result["sources"] == [{"query": "hint-a", "provider": "p1"}]
    assert result["answer"] == "SYNTHESIS"
    # Exactly one LLM call happened — aggregation — never query generation.
    assert len(llm_calls) == 1
    assert llm_calls[0]["prompt"].startswith("Synthesise")


@pytest.mark.asyncio
async def test_generated_queries_parsed_numbered_lines_and_capped(
    monkeypatch: pytest.MonkeyPatch,
):
    """Without hints, queries come from the LLM: numbered/bulleted prefixes
    are stripped and the list is capped at ``max_queries``."""
    llm_calls = _patch_complete(
        monkeypatch,
        [
            "1. first query\n2) second query\nthird query\n4. fourth query",
            "SYNTHESIS",
        ],
    )
    search = _make_search(
        {
            "first query": {"content": "p1", "query": "first query", "provider": "prov1"},
            "second query": {"content": "p2", "query": "second query", "provider": "prov2"},
        }
    )

    result = await SmartRetriever(search).retrieve("ctx", "kb", max_queries=2)

    assert search.calls == [
        {"query": "first query", "kb_name": "kb"},
        {"query": "second query", "kb_name": "kb"},
    ]
    assert [c["prompt"] for c in llm_calls][0].startswith("Generate 2 diverse search queries")
    assert "Context:\nctx" in llm_calls[0]["prompt"]
    assert result["answer"] == "SYNTHESIS"


@pytest.mark.asyncio
async def test_query_generation_failure_falls_back_to_context_prefix(
    monkeypatch: pytest.MonkeyPatch,
):
    """If query generation fails, retrieval still proceeds with the first
    200 characters of the context as the single query."""
    context = "x" * 500
    _patch_complete(monkeypatch, RuntimeError("llm down"))
    search = _make_search(
        {context[:200]: {"content": "px", "query": context[:200], "provider": "prov"}}
    )

    result = await SmartRetriever(search).retrieve(context, "kb")

    assert search.calls == [{"query": context[:200], "kb_name": "kb"}]
    # Aggregation also fails (same stub), so passages degrade to plain join.
    assert result["answer"] == "px"


@pytest.mark.asyncio
async def test_blank_generated_queries_fall_back_to_context_prefix(
    monkeypatch: pytest.MonkeyPatch,
):
    """An LLM reply with no usable lines falls back to the context prefix."""
    context = "the real question here"
    _patch_complete(monkeypatch, "\n \n \n")
    search = _make_search(
        {context[:200]: {"content": "p", "query": context[:200], "provider": "prov"}}
    )

    result = await SmartRetriever(search).retrieve(context, "kb", max_queries=3)

    assert search.calls == [{"query": context[:200], "kb_name": "kb"}]
    assert result["sources"] == [{"query": context[:200], "provider": "prov"}]


# ---------------------------------------------------------------------------
# Merge / ordering contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_passages_and_sources_merge_in_query_order_not_completion_order(
    monkeypatch: pytest.MonkeyPatch,
):
    """``asyncio.gather`` preserves the input query order: a query that
    completes last still contributes the first passage and source."""
    llm_calls = _patch_complete(monkeypatch, "SYNTHESIS")
    search = _make_search(
        {
            "q1": {"content": "p1", "query": "q1", "provider": "prov1"},
            "q2": {"content": "p2", "query": "q2", "provider": "prov2"},
            "q3": {"content": "p3", "query": "q3", "provider": "prov3"},
        },
        delays={"q1": 0.02, "q2": 0.01, "q3": 0.0},
    )

    result = await SmartRetriever(search).retrieve("ctx", "kb", query_hints=["q1", "q2", "q3"])

    assert result["sources"] == [
        {"query": "q1", "provider": "prov1"},
        {"query": "q2", "provider": "prov2"},
        {"query": "q3", "provider": "prov3"},
    ]
    # Aggregation prompt receives the passages in query order, not in
    # completion order (q3 finished first).
    assert "p1\n---\np2\n---\np3" in llm_calls[0]["prompt"]
    assert result["answer"] == "SYNTHESIS"


@pytest.mark.asyncio
async def test_content_field_preferred_over_answer_and_empty_results_skipped(
    monkeypatch: pytest.MonkeyPatch,
):
    """Content extraction contract: ``content`` wins over ``answer``; results
    with neither contribute no passage and no source entry."""
    _patch_complete(monkeypatch, "SYNTHESIS")
    search = _make_search(
        {
            "q1": {"content": "c1", "answer": "a1", "query": "q1", "provider": "prov1"},
            "q2": {"answer": "a2", "query": "q2", "provider": "prov2"},
            "q3": {"content": "", "answer": "", "query": "q3", "provider": "prov3"},
            "q4": {"content": None, "answer": None},
        }
    )

    result = await SmartRetriever(search).retrieve(
        "ctx", "kb", query_hints=["q1", "q2", "q3", "q4"]
    )

    assert result["sources"] == [
        {"query": "q1", "provider": "prov1"},
        {"query": "q2", "provider": "prov2"},
    ]


# ---------------------------------------------------------------------------
# Degradation paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partial_search_failures_skipped_but_successes_kept(
    monkeypatch: pytest.MonkeyPatch,
):
    """A failing search is dropped silently; the remaining results still
    produce an aggregated answer and aligned sources."""
    llm_calls = _patch_complete(monkeypatch, "SYNTHESIS")
    search = _make_search(
        {
            "q1": RuntimeError("boom"),
            "q2": {"content": "p2", "query": "q2", "provider": "prov2"},
            "q3": {"content": "p3", "query": "q3", "provider": "prov3"},
        }
    )

    result = await SmartRetriever(search).retrieve("ctx", "kb", query_hints=["q1", "q2", "q3"])

    assert result["sources"] == [
        {"query": "q2", "provider": "prov2"},
        {"query": "q3", "provider": "prov3"},
    ]
    assert "p2\n---\np3" in llm_calls[0]["prompt"]
    assert result["answer"] == "SYNTHESIS"


@pytest.mark.asyncio
async def test_all_searches_fail_returns_empty_without_aggregation(
    monkeypatch: pytest.MonkeyPatch,
):
    """When every search fails the result is empty and the aggregation LLM
    call is skipped entirely."""
    llm_calls = _patch_complete(monkeypatch, "SHOULD-NOT-BE-CALLED")
    search = _make_search({"q1": RuntimeError("e1"), "q2": RuntimeError("e2")})

    result = await SmartRetriever(search).retrieve("ctx", "kb", query_hints=["q1", "q2"])

    assert result == {"answer": "", "sources": []}
    assert llm_calls == []


@pytest.mark.asyncio
async def test_aggregation_failure_joins_passages_with_blank_lines(
    monkeypatch: pytest.MonkeyPatch,
):
    """If the synthesis call fails, the answer degrades to the raw passages
    joined by blank lines while sources stay intact."""
    _patch_complete(monkeypatch, RuntimeError("synthesis down"))
    search = _make_search(
        {
            "q1": {"content": "p1", "query": "q1", "provider": "prov1"},
            "q2": {"content": "p2", "query": "q2", "provider": "prov2"},
        }
    )

    result = await SmartRetriever(search).retrieve("ctx", "kb", query_hints=["q1", "q2"])

    assert result["answer"] == "p1\n\np2"
    assert result["sources"] == [
        {"query": "q1", "provider": "prov1"},
        {"query": "q2", "provider": "prov2"},
    ]
