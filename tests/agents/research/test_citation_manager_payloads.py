"""Payload fault-tolerance tests for the research citation manager.

Targets the branches flagged in DT-21 Top-15 #4: ragged RAG payloads
(``_rag_source_payload``), contiguous non-duplicated reference numbering
(``build_ref_number_map``), and degraded paths that must not raise when
sources are missing.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from deeptutor.agents.research.utils.citation_manager import (
    CitationManager,
    _rag_source_info,
    _rag_source_payload,
)


def _trace(query: str = "What is RAG?") -> SimpleNamespace:
    return SimpleNamespace(query=query, summary="Retrieved sources", timestamp="now")


# ---------------------------------------------------------------------------
# _rag_source_payload: empty / ragged answer_data must degrade, not crash
# ---------------------------------------------------------------------------


def test_rag_source_payload_accepts_none_scalar_and_text_payloads() -> None:
    """Anything that is neither a list nor a dict yields no sources."""
    for payload in (None, 42, 3.14, True, "plain text answer"):
        sources, kb_name = _rag_source_payload(payload)
        assert sources == []
        assert kb_name == ""


def test_rag_source_payload_dict_without_known_source_fields() -> None:
    sources, kb_name = _rag_source_payload({"answer": "nothing retrieved here"})
    assert sources == []
    assert kb_name == ""


def test_rag_source_payload_normalizes_missing_and_ragged_kb_name() -> None:
    """A missing or non-string ``kb_name`` never leaks ``None`` into metadata."""
    assert _rag_source_payload({})[1] == ""
    assert _rag_source_payload({"kb_name": None})[1] == ""
    assert _rag_source_payload({"kb_name": 7})[1] == "7"


def test_rag_source_payload_skips_non_list_source_fields() -> None:
    """Ragged fields (string/int/None where a list is expected) are ignored."""
    ragged = {
        "kb_name": "kb",
        "chunks": "one big string",
        "documents": 3,
        "sources": None,
        "context": {"not": "a list"},
        "retrieved_docs": True,
    }
    sources, kb_name = _rag_source_payload(ragged)
    assert sources == []
    assert kb_name == "kb"


def test_rag_source_payload_picks_the_first_list_shaped_field() -> None:
    payload = {
        "kb_name": "course-notes",
        "chunks": "ragged",
        "documents": [{"title": "Doc"}],
    }
    sources, kb_name = _rag_source_payload(payload)
    assert kb_name == "course-notes"
    assert sources == [{"title": "Doc"}]


def test_rag_source_payload_list_passthrough() -> None:
    documents = [{"title": "A"}, "raw text entry", 42]
    sources, kb_name = _rag_source_payload(documents)
    assert sources is documents
    assert kb_name == ""


def test_rag_source_info_drops_scalar_junk_entries() -> None:
    assert _rag_source_info(42, 0) == {}
    assert _rag_source_info("raw text entry", 1) == {"content_preview": "raw text entry"[:200]}


# ---------------------------------------------------------------------------
# Reference numbering: contiguous 1..N, unique per distinct source
# ---------------------------------------------------------------------------


def test_ref_number_map_is_contiguous_and_unique_across_tool_types(tmp_path) -> None:
    manager = CitationManager("numbering", cache_dir=tmp_path)

    plan_sources = {"sources": [{"title": "Plan doc", "content": "content"}]}
    assert manager.add_citation("PLAN-01", "rag", _trace(), "answer", plan_sources)
    rag_sources = {"sources": [{"title": "RAG doc", "content": "content"}]}
    assert manager.add_citation("CIT-1-01", "rag", _trace(), "answer", rag_sources)

    web_meta = {"citations": [{"title": "Web", "url": "https://example.com"}]}
    assert manager.add_citation("CIT-2-01", "web_search", _trace(), "answer", web_meta)

    papers = {
        "papers": [
            {"title": "Paper A", "authors": ["Alpha"], "year": "2024", "url": "u1"},
            {"title": "Paper B", "authors": ["Beta"], "year": "2025", "url": "u2"},
        ]
    }
    assert manager.add_citation("CIT-3-01", "paper_search", _trace(), "answer", papers)

    ref_map = manager.build_ref_number_map()

    numbers = sorted(set(ref_map.values()))
    assert numbers == list(range(1, len(numbers) + 1))
    assert ref_map["PLAN-01"] == 1
    assert ref_map["CIT-1-01"] == 2
    assert ref_map["CIT-2-01"] == 3
    assert ref_map["CIT-3-01"] == 4
    assert ref_map["CIT-3-01-2"] == 5
    assert manager.get_ref_number("CIT-3-01-2") == 5


def test_ref_number_map_dedupes_identical_papers_but_keeps_others_unique(tmp_path) -> None:
    manager = CitationManager("dedup", cache_dir=tmp_path)

    papers_a = {"papers": [{"title": "Same Paper", "authors": ["One"], "url": "u"}]}
    papers_b = {"papers": [{"title": "Same Paper", "authors": ["One"], "url": "u"}]}
    assert manager.add_citation("CIT-1-01", "paper_search", _trace(), "answer", papers_a)
    assert manager.add_citation("CIT-2-01", "paper_search", _trace(), "answer", papers_b)
    assert manager.add_citation(
        "CIT-2-02", "rag", _trace(), "answer", {"sources": [{"title": "T", "content": "C"}]}
    )

    ref_map = manager.build_ref_number_map()

    assert ref_map["CIT-1-01"] == ref_map["CIT-2-01"]
    assert ref_map["CIT-1-01-1"] == ref_map["CIT-1-01"]
    assert ref_map["CIT-2-01-1"] == ref_map["CIT-1-01"]
    assert ref_map["CIT-2-02"] != ref_map["CIT-1-01"]
    numbers = sorted(set(ref_map.values()))
    assert numbers == list(range(1, len(numbers) + 1))


def test_ref_number_map_empty_and_missing_ids_degrade(tmp_path) -> None:
    manager = CitationManager("empty", cache_dir=tmp_path)
    assert manager.build_ref_number_map() == {}
    assert manager.get_ref_number("CIT-1-01") == 0
    assert manager.get_ref_number_map() == {}


# ---------------------------------------------------------------------------
# Missing sources degrade without raising
# ---------------------------------------------------------------------------


def test_rag_citation_without_metadata_or_json_degrades_gracefully(tmp_path) -> None:
    """A prose answer with no structured payload still stores a usable citation."""
    manager = CitationManager("degraded", cache_dir=tmp_path)

    citation = manager._extract_rag_citation("CIT-9-01", "rag", "Prose answer, no JSON", _trace())

    assert citation["citation_id"] == "CIT-9-01"
    assert citation["sources"] == []
    assert citation["total_sources"] == 0
    assert citation["kb_name"] == ""
    assert manager.add_citation("CIT-9-01", "rag", _trace(), "Prose answer, no JSON", None) is True
    stored = manager.get_citation("CIT-9-01")
    assert stored is not None
    assert stored["total_sources"] == 0


def test_rag_citation_falls_back_to_answer_when_metadata_sources_are_ragged(tmp_path) -> None:
    manager = CitationManager("ragged-meta", cache_dir=tmp_path)
    raw_answer = json.dumps(
        {"kb_name": "answer-kb", "chunks": [{"text": "chunk text", "id": "c1"}]}
    )

    citation = manager._extract_rag_citation(
        "CIT-9-02", "rag", raw_answer, _trace(), {"kb_name": "meta-kb", "sources": "ragged"}
    )

    assert citation["kb_name"] == "meta-kb"
    assert citation["total_sources"] == 1
    assert citation["sources"][0]["content_preview"] == "chunk text"


def test_add_citation_swallows_broken_tool_trace(tmp_path, capsys) -> None:
    """A tool trace missing expected attributes is reported, never raised."""
    manager = CitationManager("broken-trace", cache_dir=tmp_path)

    assert manager.add_citation("CIT-9-03", "rag", object(), "answer", None) is False
    assert "Failed to add citation" in capsys.readouterr().out
    assert manager.get_citation("CIT-9-03") is None


def test_add_citation_unknown_tool_type_uses_generic_entry(tmp_path) -> None:
    manager = CitationManager("generic", cache_dir=tmp_path)

    assert manager.add_citation("CIT-9-04", "mystery_tool", _trace(), "answer", None) is True
    stored = manager.get_citation("CIT-9-04")
    assert stored is not None
    assert stored["tool_type"] == "mystery_tool"
    assert "sources" not in stored
