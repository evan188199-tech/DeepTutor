"""Top-level RAG retrieval fallback-chain tests.

Failure-injection coverage for the orchestration layer above the pipelines
(``service.py``, ``smart_retriever.py``, ``provider_binding.py``,
``factory.py``): provider-binding degradation, the reasoning-as-retrieval
guard, hard pipeline failures vs. error-typed partial results, best-effort
side channels, and SmartRetriever partial-result / LLM-fallback semantics.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import deeptutor.services.llm as llm_module
import deeptutor.services.memory as memory_module
import deeptutor.services.path_service as path_service_module
from deeptutor.services.rag import service as rag_service_module
from deeptutor.services.rag.factory import DEFAULT_PROVIDER, normalize_provider_name
from deeptutor.services.rag.provider_binding import resolve_bound_provider
from deeptutor.services.rag.service import RAGService
from deeptutor.services.rag.smart_retriever import SmartRetriever

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _ScriptedPipeline:
    """Fake pipeline whose ``search`` raises or returns a canned result."""

    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.search_calls = 0

    async def initialize(self, kb_name: str, file_paths, **kwargs) -> bool:  # noqa: ARG002
        return True

    async def add_documents(self, kb_name: str, file_paths, **kwargs) -> bool:  # noqa: ARG002
        return True

    async def search(self, query: str, kb_name: str, **kwargs) -> dict[str, Any]:  # noqa: ARG002
        self.search_calls += 1
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return dict(self.outcome)


def _service_with(tmp_path, outcome: Any) -> tuple[RAGService, _ScriptedPipeline]:
    service = RAGService(kb_base_dir=str(tmp_path))
    pipeline = _ScriptedPipeline(outcome)
    service._pipelines[DEFAULT_PROVIDER] = pipeline  # type: ignore[attr-defined]
    return service, pipeline


def _make_sink(events: list[dict]):
    async def _emit(event_type: str, message: str, metadata: dict | None) -> None:
        events.append({"type": event_type, "message": message, "metadata": dict(metadata or {})})

    return _emit


# ---------------------------------------------------------------------------
# Provider binding fallback chain: kb_config.json → metadata.json → default
# ---------------------------------------------------------------------------


def test_binding_falls_back_to_metadata_when_config_lacks_entry(tmp_path) -> None:
    (tmp_path / "kb").mkdir()
    (tmp_path / "kb_config.json").write_text(json.dumps({"knowledge_bases": {}}), encoding="utf-8")
    (tmp_path / "kb" / "metadata.json").write_text(
        json.dumps({"rag_provider": "lightrag"}), encoding="utf-8"
    )

    assert resolve_bound_provider(tmp_path, "kb") == "lightrag"


def test_binding_survives_corrupt_kb_config_and_uses_metadata(tmp_path) -> None:
    (tmp_path / "kb").mkdir()
    (tmp_path / "kb_config.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "kb" / "metadata.json").write_text(
        json.dumps({"rag_provider": "graphrag"}), encoding="utf-8"
    )

    assert resolve_bound_provider(tmp_path, "kb") == "graphrag"


def test_binding_survives_corrupt_metadata_and_defaults(tmp_path) -> None:
    (tmp_path / "kb").mkdir()
    (tmp_path / "kb" / "metadata.json").write_text("]]] broken", encoding="utf-8")

    assert resolve_bound_provider(tmp_path, "kb") == DEFAULT_PROVIDER


def test_binding_normalizes_unknown_metadata_provider_to_default(tmp_path) -> None:
    (tmp_path / "kb").mkdir()
    (tmp_path / "kb" / "metadata.json").write_text(
        json.dumps({"rag_provider": "retired-engine"}), encoding="utf-8"
    )

    assert resolve_bound_provider(tmp_path, "kb") == DEFAULT_PROVIDER


def test_binding_defaults_when_kb_has_no_binding_files(tmp_path) -> None:
    (tmp_path / "kb").mkdir()

    assert resolve_bound_provider(tmp_path, "kb") == DEFAULT_PROVIDER
    # A missing KB name skips the file probes entirely.
    assert resolve_bound_provider(tmp_path, None) == DEFAULT_PROVIDER


def test_normalize_provider_name_collapses_unknown_to_default() -> None:
    assert normalize_provider_name(None) == DEFAULT_PROVIDER
    assert normalize_provider_name("") == DEFAULT_PROVIDER
    assert normalize_provider_name("   ") == DEFAULT_PROVIDER
    assert normalize_provider_name("no-such-engine") == DEFAULT_PROVIDER
    # Known names are case/whitespace tolerant.
    assert normalize_provider_name(" LightRAG ") == "lightrag"


# ---------------------------------------------------------------------------
# RAGService.search degradation paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_guard_blocks_pageindex_without_touching_pipeline(tmp_path) -> None:
    """Reasoning-as-retrieval engines answer with a guard result and never
    build or call a pipeline."""
    service = RAGService(kb_base_dir=str(tmp_path), provider="pageindex")

    result = await service.search(query="hello", kb_name="kb")

    assert result["error_type"] == "reasoning_as_retrieval_required"
    assert result["provider"] == "pageindex"
    assert result["sources"] == []
    assert result["content"] == ""
    assert "PageIndex" in result["answer"]
    assert service._pipelines == {}  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_search_propagates_pipeline_hard_failure(tmp_path) -> None:
    """A pipeline that raises (e.g. a retrieval timeout) surfaces to the
    caller — this layer signals degradations via error-typed results, not by
    swallowing exceptions."""
    service, _pipeline = _service_with(tmp_path, TimeoutError("retrieval timed out"))

    with pytest.raises(TimeoutError):
        await service.search(query="q", kb_name="kb")


@pytest.mark.asyncio
async def test_search_returns_error_typed_result_and_emits_error_event(
    tmp_path,
) -> None:
    """Pipeline-reported failures come back as partial results with the
    provider stamped, plus a call_state=error status event."""
    outcome = {
        "query": "q",
        "answer": "Index is missing. Please re-index.",
        "content": "Index is missing. Please re-index.",
        "error_type": "index_missing",
        "needs_reindex": True,
        "sources": [],
    }
    service, pipeline = _service_with(tmp_path, outcome)
    events: list[dict] = []

    result = await service.search(query="q", kb_name="kb", event_sink=_make_sink(events))

    assert result["error_type"] == "index_missing"
    assert result["needs_reindex"] is True
    assert result["provider"] == DEFAULT_PROVIDER  # authoritative overwrite
    assert pipeline.search_calls == 1

    error_events = [e for e in events if e["metadata"].get("call_state") == "error"]
    assert len(error_events) == 1
    assert error_events[0]["metadata"]["error_type"] == "index_missing"
    assert error_events[0]["metadata"]["needs_reindex"] is True
    assert "re-index" in error_events[0]["message"].lower()


@pytest.mark.asyncio
async def test_search_survives_memory_trace_failure(tmp_path, monkeypatch) -> None:
    """The L1 memory trace is best-effort: a broken memory store must never
    fail the search itself."""
    service, pipeline = _service_with(tmp_path, {"answer": "ok", "content": "ok", "sources": []})

    def _broken_store():
        raise RuntimeError("memory store offline")

    monkeypatch.setattr(memory_module, "get_memory_store", _broken_store, raising=True)

    result = await service.search(query="q", kb_name="kb")

    assert result["answer"] == "ok"
    assert result["provider"] == DEFAULT_PROVIDER
    assert pipeline.search_calls == 1


def test_init_falls_back_to_default_kb_base_dir_when_path_service_unavailable(
    monkeypatch,
) -> None:
    """Single-user/CLI fallback: when the multi-user path service cannot be
    reached, RAGService degrades to the runtime default KB directory."""

    def _unavailable():
        raise RuntimeError("path service unavailable")

    monkeypatch.setattr(path_service_module, "get_path_service", _unavailable, raising=True)

    service = RAGService()

    assert service.kb_base_dir == rag_service_module.DEFAULT_KB_BASE_DIR


def test_get_current_provider_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.delenv("RAG_PROVIDER", raising=False)
    assert RAGService.get_current_provider() == DEFAULT_PROVIDER

    monkeypatch.setenv("RAG_PROVIDER", "not-a-real-engine")
    assert RAGService.get_current_provider() == DEFAULT_PROVIDER

    monkeypatch.setenv("RAG_PROVIDER", "LIGHTRAG")
    assert RAGService.get_current_provider() == "lightrag"


# ---------------------------------------------------------------------------
# SmartRetriever: partial results, timeouts, LLM fallbacks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_keeps_partial_results_when_one_query_times_out(
    monkeypatch,
) -> None:
    """A timed-out query is dropped; survivors still produce an aggregated
    answer and sources."""
    calls: list[str] = []

    async def _search(*, query: str, kb_name: str) -> dict[str, Any]:  # noqa: ARG001
        calls.append(query)
        if query == "q-dead":
            raise TimeoutError("retrieval timed out")
        return {"content": "PASSAGE", "query": query, "provider": "p"}

    async def _fake_complete(*args, **kwargs) -> str:  # noqa: ARG001
        return "SYNTH"

    monkeypatch.setattr(llm_module, "complete", _fake_complete, raising=True)

    retriever = SmartRetriever(_search)
    out = await retriever.retrieve(context="ctx", kb_name="kb", query_hints=["q-dead", "q-ok"])

    assert sorted(calls) == ["q-dead", "q-ok"]  # every query was attempted
    assert out["answer"] == "SYNTH"
    assert out["sources"] == [{"query": "q-ok", "provider": "p"}]


@pytest.mark.asyncio
async def test_retrieve_returns_empty_when_every_query_times_out(monkeypatch) -> None:
    """All queries failing (e.g. timeouts) degrades to an empty answer, and
    the aggregation LLM is never invoked."""

    async def _search(*, query: str, kb_name: str) -> dict[str, Any]:  # noqa: ARG001
        raise TimeoutError("retrieval timed out")

    async def _must_not_be_called(*args, **kwargs):  # noqa: ARG001
        raise AssertionError("aggregation must not run without passages")

    monkeypatch.setattr(llm_module, "complete", _must_not_be_called, raising=True)

    retriever = SmartRetriever(_search)
    out = await retriever.retrieve(context="ctx", kb_name="kb", query_hints=["q1", "q2"])

    assert out == {"answer": "", "sources": []}


@pytest.mark.asyncio
async def test_generate_queries_falls_back_to_context_prefix_when_llm_fails(
    monkeypatch,
) -> None:
    context = "x" * 500

    async def _broken_complete(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(llm_module, "complete", _broken_complete, raising=True)

    queries = await SmartRetriever(lambda **k: None)._generate_queries(context, 3)  # noqa: ARG005

    assert queries == [context[:200]]


@pytest.mark.asyncio
async def test_generate_queries_falls_back_when_llm_returns_nothing(
    monkeypatch,
) -> None:
    context = "y" * 300

    async def _empty_complete(*args, **kwargs) -> str:  # noqa: ARG001
        return "  \n \n"

    monkeypatch.setattr(llm_module, "complete", _empty_complete, raising=True)

    queries = await SmartRetriever(lambda **k: None)._generate_queries(context, 3)  # noqa: ARG005

    assert queries == [context[:200]]


@pytest.mark.asyncio
async def test_generate_queries_parses_numbered_lines_and_caps_count(
    monkeypatch,
) -> None:
    async def _fake_complete(*args, **kwargs) -> str:  # noqa: ARG001
        return "1. first query\n2) second query\n3. third query\n4. fourth query"

    monkeypatch.setattr(llm_module, "complete", _fake_complete, raising=True)

    queries = await SmartRetriever(lambda **k: None)._generate_queries("ctx", 2)  # noqa: ARG005

    assert queries == ["first query", "second query"]


@pytest.mark.asyncio
async def test_aggregate_falls_back_to_joined_passages_when_llm_fails(
    monkeypatch,
) -> None:
    async def _broken_complete(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(llm_module, "complete", _broken_complete, raising=True)

    aggregated = await SmartRetriever(lambda **k: None)._aggregate(  # noqa: ARG005
        "ctx", ["p1", "p2"]
    )

    assert aggregated == "p1\n\np2"
