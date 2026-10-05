"""``knowledge_frontier`` module — query parsing, KB aggregation, tolerance, output shape.

Focused unit coverage for :mod:`deeptutor.tools.knowledge_frontier` (the
wrapper tool is covered by ``test_knowledge_frontier_tool.py``). Knowledge-base
directories are faked under ``tmp_path`` and every model/network dependency is
stubbed, so no test reaches arXiv or a reasoning backend.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.knowledge.manifest import UNAVAILABLE_MISSING, build_manifest
from deeptutor.tools import knowledge_frontier as kf
from deeptutor.tools.knowledge_frontier import (
    DEFAULT_MAX_PAPERS,
    DEFAULT_YEARS_LIMIT,
    MAX_PAPERS_LIMIT,
    MAX_YEARS_LIMIT,
    MAX_SEARCH_QUERIES,
    _clamped_int,
    _deduplicate,
    _fallback_queries,
    _one_line,
    _parse_queries,
    discover_frontier,
)

_PAPER_A = {
    "title": "Adaptive Tutoring Frontiers",
    "authors": ["Ada Lovelace"],
    "year": 2026,
    "abstract": "Recent direction one.",
    "url": "https://arxiv.org/abs/2601.0001",
    "arxiv_id": "2601.0001",
}
_PAPER_B = {
    "title": "Curriculum Graphs",
    "authors": ["Grace Hopper", "Alan Turing"],
    "year": 2025,
    "abstract": "Recent direction two.",
    "url": "https://arxiv.org/abs/2501.0002",
    "arxiv_id": "2501.0002",
}


class _FakeArxiv:
    """Stands in for ``ArxivSearchTool``; results keyed by query text."""

    def __init__(
        self,
        results_by_query: dict[str, list[dict[str, Any]]] | None = None,
        error_queries: tuple[str, ...] = (),
    ) -> None:
        self.results_by_query = results_by_query or {}
        self.error_queries = set(error_queries)
        self.calls: list[dict[str, Any]] = []

    async def search_papers(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(kwargs)
        if kwargs["query"] in self.error_queries:
            raise RuntimeError("arxiv unavailable")
        return [dict(paper) for paper in self.results_by_query.get(kwargs["query"], [])]


def _stub_discovery(
    monkeypatch: pytest.MonkeyPatch,
    arxiv: _FakeArxiv,
    *,
    rag_answer: str = "The KB covers attention basics.",
    rag_sources: list[Any] | None = None,
    reason_answer: str = '["graph tutoring", "curriculum models"]',
    reason_error: Exception | None = None,
) -> dict[str, Any]:
    """Stub ``rag_search`` / ``reason`` / ``ArxivSearchTool``; records reason kwargs."""

    captured: dict[str, Any] = {}

    async def fake_rag_search(query: str, kb_name: str) -> dict[str, Any]:
        return {"answer": rag_answer, "sources": [] if rag_sources is None else rag_sources}

    async def fake_reason(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        if reason_error:
            raise reason_error
        return {"answer": reason_answer, "model": "test-model"}

    import deeptutor.tools.reason as reason_module

    monkeypatch.setattr("deeptutor.tools.rag_tool.rag_search", fake_rag_search)
    monkeypatch.setattr(reason_module, "reason", fake_reason)
    monkeypatch.setattr(kf, "ArxivSearchTool", lambda: arxiv)
    return captured


def _kb_manifest(tmp_path: Path, *, raw_entries: list[str] | None = None) -> Any:
    """Build a real ``KbManifest`` from a fake KB directory under ``tmp_path``."""
    kb_dir = tmp_path / "Course"
    raw = kb_dir / "raw"
    raw.mkdir(parents=True)
    for rel in raw_entries or []:
        path = raw / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stub document body", encoding="utf-8")
    return build_manifest(name="Course", kb_dir=kb_dir)


class TestQueryParsing:
    def test_parses_list_wrapped_in_prose(self) -> None:
        answer = 'Sure! Here are my queries: ["alpha beta", "gamma delta"] hope that helps'
        assert _parse_queries(answer) == ["alpha beta", "gamma delta"]

    def test_parses_bare_json_list(self) -> None:
        assert _parse_queries('["one two", "three four"]') == ["one two", "three four"]

    def test_invalid_json_yields_no_queries(self) -> None:
        assert _parse_queries('["alpha beta", "gamma delta') == []

    def test_answer_without_parseable_list_yields_no_queries(self) -> None:
        assert _parse_queries("no json here at all") == []

    def test_filters_non_strings_short_and_duplicate_queries(self) -> None:
        answer = (
            '["alpha beta", "ALPHA BETA", "solo", 42, null, '
            '"gamma delta", "epsilon zeta", "eta theta", "iota kappa"]'
        )
        assert _parse_queries(answer) == ["alpha beta", "gamma delta", "epsilon zeta"]
        assert len(_parse_queries(answer)) == MAX_SEARCH_QUERIES


class TestInputNormalisation:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("abc", 7),
            (None, 7),
            (object(), 7),
            (0, 1),
            (-5, 1),
            (99, 10),
            ("4", 4),
        ],
    )
    def test_clamped_int_falls_back_or_bounds(self, value: Any, expected: int) -> None:
        assert _clamped_int(value, 7, 1, 10) == expected

    def test_one_line_collapses_whitespace_and_truncates(self) -> None:
        assert _one_line("  a\n\n b \t c  ", limit=100) == "a b c"
        assert _one_line("x" * 300, limit=240) == "x" * 240
        assert _one_line(None, limit=10) == ""
        assert _one_line(False, limit=10) == ""

    def test_module_limits_stay_consistent(self) -> None:
        assert DEFAULT_MAX_PAPERS == 5
        assert MAX_PAPERS_LIMIT == 10
        assert DEFAULT_YEARS_LIMIT == 3
        assert MAX_YEARS_LIMIT == 10


class TestFallbackQueries:
    def test_focus_seeds_three_distinct_queries(self) -> None:
        queries = _fallback_queries(focus="graph  tutoring", document_names=[])
        assert queries == [
            "graph tutoring",
            "recent advances graph tutoring",
            "open challenges graph tutoring",
        ]

    def test_first_document_name_seeds_when_no_focus(self) -> None:
        queries = _fallback_queries(
            focus="", document_names=["reports/attention-basics.pdf", "other.md"]
        )
        assert queries[0] == "attention basics"
        assert queries[1] == "recent advances attention basics"
        assert queries[2] == "open challenges attention basics"

    def test_no_seed_at_all_falls_back_to_generic_query(self) -> None:
        assert _fallback_queries(focus="   ", document_names=[]) == [
            "recent research frontiers"
        ]


class TestDeduplicate:
    def test_dedupes_case_insensitively_and_skips_non_dicts(self) -> None:
        papers: list[Any] = [
            {"arxiv_id": "2601.0001", "title": "Adaptive Tutoring"},
            "not-a-dict",
            42,
            {"arxiv_id": " 2601.0001 ", "title": "adaptive tutoring"},
            {"arxiv_id": "", "title": ""},
            {"arxiv_id": "", "title": ""},
            {"arxiv_id": "2501.0002", "title": "Curriculum Graphs"},
        ]
        deduped = _deduplicate(papers)
        assert len(deduped) == 3
        assert [paper["title"] for paper in deduped] == [
            "Adaptive Tutoring",
            "",
            "Curriculum Graphs",
        ]


class TestKbAggregation:
    def test_manifest_aggregates_documents_from_fake_kb_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manifest = _kb_manifest(
            tmp_path,
            raw_entries=["attention-basics.pdf", "notes/curriculum.md", ".DS_Store"],
        )
        assert manifest.total == 2
        arxiv = _FakeArxiv({"graph tutoring": [_PAPER_A]})
        _stub_discovery(monkeypatch, arxiv)

        result = _run(
            discover_frontier(
                kb_name="Course",
                manifest=manifest,
                focus="  graph\n tutoring ",
            )
        )

        assert result["metadata"]["kb_name"] == "Course"
        assert result["metadata"]["kb_documents"] == 2
        assert "Grounded in 2 document(s)." in result["content"]
        assert any(call["query"] == "graph tutoring" for call in arxiv.calls)

    def test_empty_kb_falls_back_to_generic_query_and_reports_no_papers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manifest = _kb_manifest(tmp_path, raw_entries=[])
        assert manifest.total == 0
        arxiv = _FakeArxiv()
        _stub_discovery(
            monkeypatch,
            arxiv,
            rag_answer="   ",
            reason_answer="the model replied with prose, no list",
        )

        result = _run(discover_frontier(kb_name="Course", manifest=manifest))

        assert result["metadata"]["status"] == "papers_not_found"
        assert result["metadata"]["queries"] == ["recent research frontiers"]
        assert result["metadata"]["query_plan"]["source"] == "fallback"
        assert result["metadata"]["kb_summary"] == ""
        assert "No recent arXiv preprints" in result["content"]
        assert "Existing material summary:" not in result["content"]

    def test_missing_raw_directory_is_tolerated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kb_dir = tmp_path / "Course"
        kb_dir.mkdir()
        manifest = build_manifest(name="Course", kb_dir=kb_dir)
        assert manifest.unavailable == UNAVAILABLE_MISSING
        arxiv = _FakeArxiv({"attention": [_PAPER_A]})
        _stub_discovery(monkeypatch, arxiv, reason_error=RuntimeError("LLM unavailable"))

        result = _run(
            discover_frontier(kb_name="Course", manifest=manifest, focus="attention")
        )

        assert result["metadata"]["kb_documents"] == 0
        assert result["metadata"]["status"] == "papers_found"
        assert result["metadata"]["queries"][0] == "attention"
        assert result["metadata"]["papers"][0]["title"] == _PAPER_A["title"]

    def test_raw_path_which_is_a_file_is_tolerated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kb_dir = tmp_path / "Course"
        kb_dir.mkdir()
        (kb_dir / "raw").write_text("not a directory", encoding="utf-8")
        manifest = build_manifest(name="Course", kb_dir=kb_dir)
        assert manifest.unavailable == UNAVAILABLE_MISSING
        arxiv = _FakeArxiv()
        _stub_discovery(monkeypatch, arxiv, reason_error=RuntimeError("LLM unavailable"))

        result = _run(discover_frontier(kb_name="Course", manifest=manifest, focus=""))

        assert result["metadata"]["kb_documents"] == 0
        assert result["metadata"]["queries"] == ["recent research frontiers"]
        assert result["metadata"]["status"] == "papers_not_found"

    def test_malformed_manifest_document_entries_are_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manifest = SimpleNamespace(
            name="Broken",
            total=3,
            documents=(
                SimpleNamespace(),
                SimpleNamespace(name="   "),
                "plain-string-entry",
            ),
        )
        arxiv = _FakeArxiv()
        _stub_discovery(monkeypatch, arxiv, reason_error=RuntimeError("LLM unavailable"))

        result = _run(discover_frontier(kb_name="Broken", manifest=manifest))

        assert result["metadata"]["kb_documents"] == 3
        assert result["metadata"]["kb_name"] == "Broken"
        assert result["metadata"]["queries"] == ["recent research frontiers"]

    def test_manifest_without_any_attributes_uses_safe_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        arxiv = _FakeArxiv({"graph tutoring": [_PAPER_A]})
        _stub_discovery(monkeypatch, arxiv)

        result = _run(
            discover_frontier(kb_name="Course", manifest=SimpleNamespace())
        )

        assert result["metadata"]["kb_name"] == "Course"
        assert result["metadata"]["kb_documents"] == 0
        assert result["metadata"]["status"] == "papers_found"


class TestOutputStructure:
    def test_result_carries_exactly_the_three_documented_sections(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        arxiv = _FakeArxiv(
            {
                "graph tutoring": [_PAPER_A],
                "curriculum models": [_PAPER_B],
            }
        )
        _stub_discovery(
            monkeypatch,
            arxiv,
            rag_sources=[{"title": "Attention notes", "content": "..."}],
        )

        result = _run(
            discover_frontier(
                kb_name="Course",
                manifest=SimpleNamespace(
                    name="Course",
                    total=2,
                    documents=(
                        SimpleNamespace(name="attention-basics.pdf"),
                        SimpleNamespace(name="curriculum.md"),
                    ),
                ),
                focus="curriculum design",
                years_limit=None,
            )
        )

        assert set(result) == {"content", "metadata", "kb_sources"}
        assert set(result["metadata"]) == {
            "kb_name",
            "kb_documents",
            "focus",
            "status",
            "kb_summary",
            "queries",
            "query_errors",
            "papers",
            "query_plan",
            "years_limit",
        }
        assert result["metadata"]["years_limit"] is None
        assert result["metadata"]["query_plan"]["source"] == "llm"
        assert all(call["years_limit"] is None for call in arxiv.calls)
        assert result["kb_sources"] == [
            {"type": "rag", "kb_name": "Course", "title": "Attention notes", "content": "..."}
        ]
        assert "Focus: curriculum design" in result["content"]

    def test_limit_arguments_are_clamped_before_search(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        arxiv = _FakeArxiv({"graph tutoring": [_PAPER_A]})
        _stub_discovery(monkeypatch, arxiv)

        result = _run(
            discover_frontier(
                kb_name="Course",
                manifest=SimpleNamespace(name="Course", total=0, documents=()),
                max_papers=99,
                years_limit=-3,
            )
        )

        assert arxiv.calls[0]["max_results"] == MAX_PAPERS_LIMIT
        assert arxiv.calls[0]["years_limit"] == 0
        assert result["metadata"]["years_limit"] == 0

    def test_query_errors_are_reported_but_remaining_queries_still_searched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        arxiv = _FakeArxiv(
            {"curriculum models": [_PAPER_B]}, error_queries=("graph tutoring",)
        )
        _stub_discovery(monkeypatch, arxiv)

        result = _run(
            discover_frontier(
                kb_name="Course",
                manifest=SimpleNamespace(name="Course", total=1, documents=()),
            )
        )

        assert len(arxiv.calls) == 2
        assert result["metadata"]["query_errors"] == ["graph tutoring: arxiv unavailable"]
        assert result["metadata"]["status"] == "papers_found"
        assert [paper["title"] for paper in result["metadata"]["papers"]] == [
            _PAPER_B["title"]
        ]
        assert "Query errors:" in result["content"]
        assert "- graph tutoring: arxiv unavailable" in result["content"]

    def test_papers_are_deduplicated_across_queries_and_capped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repeated = {**_PAPER_A, "arxiv_id": " 2601.0001", "title": " adaptive tutoring frontiers "}
        arxiv = _FakeArxiv(
            {
                "graph tutoring": [_PAPER_A, _PAPER_B],
                "curriculum models": [repeated, _PAPER_A],
            }
        )
        _stub_discovery(monkeypatch, arxiv)

        result = _run(
            discover_frontier(
                kb_name="Course",
                manifest=SimpleNamespace(name="Course", total=0, documents=()),
                max_papers=2,
            )
        )

        titles = [paper["title"] for paper in result["metadata"]["papers"]]
        assert titles == [_PAPER_A["title"], _PAPER_B["title"]]
        assert result["metadata"]["papers"][0]["source_query"] == "graph tutoring"
        keys = {
            (str(p["arxiv_id"]).strip().lower(), str(p["title"]).strip().lower())
            for p in result["metadata"]["papers"]
        }
        assert len(keys) == 2

    def test_kb_sources_fall_back_to_a_generic_rag_entry_without_sources(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        arxiv = _FakeArxiv()
        _stub_discovery(monkeypatch, arxiv, rag_sources=["junk", 42, None])

        result = _run(
            discover_frontier(
                kb_name="Course",
                manifest=SimpleNamespace(name="Course", total=0, documents=()),
                focus="",
            )
        )

        assert result["kb_sources"] == [
            {"type": "rag", "query": "knowledge frontier", "kb_name": "Course"}
        ]

    def test_reason_receives_llm_kwargs_and_summary_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        arxiv = _FakeArxiv()
        captured = _stub_discovery(
            monkeypatch, arxiv, rag_answer="KB summary text", rag_sources=[]
        )

        _run(
            discover_frontier(
                kb_name="Course",
                manifest=SimpleNamespace(name="Course", total=1, documents=()),
                focus="graph tutoring",
                api_key="secret-key",
                model="test-model",
            )
        )

        assert captured["model"] == "test-model"
        assert captured["api_key"] == "secret-key"
        assert "Knowledge base: Course" in captured["context"]
        assert "Learner focus: graph tutoring" in captured["context"]
        assert "KB summary text" in captured["context"]


def _run(awaitable: Any) -> Any:
    import asyncio

    return asyncio.run(awaitable)
