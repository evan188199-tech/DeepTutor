"""Boundary tests for deeptutor.tools.tex_chunker.

Complements tests/tools/test_tex_tools.py by locking the exact max_tokens
boundary of ``split_tex_into_chunks``, the section-splitting internals
(preamble preservation, all three marker levels, marker-free fallback), the
sentence-level fallback inside ``_split_by_paragraphs`` and the overlap-window
edge of ``_get_overlap_text``. Pure tokenizer/string work — no network, no
processes.
"""

from __future__ import annotations

import pytest

import deeptutor.tools.tex_chunker as chunker_module
from deeptutor.tools.tex_chunker import TexChunker


def _cl100k_chunker(monkeypatch: pytest.MonkeyPatch) -> TexChunker:
    """Chunker forced onto the cl100k_base fallback, independent of LLM config."""

    def _raise() -> None:
        raise RuntimeError("no llm config in tests")

    monkeypatch.setattr(chunker_module, "resolve_llm_runtime_config", _raise)
    return TexChunker()


def _section_doc(paragraphs_per_section: int = 4, sections: int = 6) -> str:
    parts = ["\\documentclass{article}\n\\begin{document}\n"]
    for section in range(sections):
        parts.append(f"\\section{{Chapter {section}}}\n")
        for paragraph in range(paragraphs_per_section):
            parts.append(
                f"Paragraph {paragraph} of section {section} explains idea {paragraph} "
                "with several plain words.\n\n"
            )
    parts.append("\\end{document}\n")
    return "".join(parts)


class TestSplitBoundary:
    def test_total_exactly_at_max_tokens_passes_through_untouched(
        self, monkeypatch: object
    ) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        doc = _section_doc()
        max_tokens = chunker.estimate_tokens(doc)
        assert max_tokens > 0
        assert chunker.split_tex_into_chunks(doc, max_tokens=max_tokens, overlap=0) == [doc]

    def test_one_token_past_boundary_starts_chunking(self, monkeypatch: pytest.MonkeyPatch) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        doc = _section_doc(paragraphs_per_section=6)
        max_tokens = chunker.estimate_tokens(doc) - 1
        chunks = chunker.split_tex_into_chunks(doc, max_tokens=max_tokens, overlap=0)
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunker.estimate_tokens(chunk) <= max_tokens


class TestSectionSplitting:
    def test_preamble_is_kept_as_its_own_leading_section(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        sections = chunker._split_by_sections(_section_doc())
        assert sections[0].startswith("\\documentclass")
        assert "\\begin{document}" in sections[0]
        section_bodies = [piece for piece in sections if piece.startswith("\\section{")]
        assert len(section_bodies) == 6

    def test_all_three_marker_levels_start_new_sections(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        doc = (
            "\\section{Top}\nintro text\n\n"
            "\\subsection{Mid}\nbody text\n\n"
            "\\subsubsection{Deep}\ndetail text\n"
        )
        sections = chunker._split_by_sections(doc)
        assert len(sections) == 3
        assert sections[0].startswith("\\section{Top}")
        assert sections[1].startswith("\\subsection{Mid}")
        assert sections[2].startswith("\\subsubsection{Deep}")
        assert "detail text" in sections[2]

    def test_marker_free_document_falls_back_to_paragraph_splitting(
        self, monkeypatch: object
    ) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        doc = "\n\n".join(f"Plain paragraph {index} with some words." for index in range(10))
        sections = chunker._split_by_sections(doc)
        assert len(sections) == 1
        assert "Plain paragraph 9" in sections[0]


class TestParagraphSentenceFallback:
    def test_single_oversized_paragraph_splits_by_sentences(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        paragraph = " ".join(
            f"Sentence number {index} states a plain fact with several ordinary words."
            for index in range(60)
        )
        max_tokens = 80
        chunks = chunker._split_by_paragraphs(paragraph, max_tokens=max_tokens, overlap=0)
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunker.estimate_tokens(chunk) <= max_tokens
        reconstructed = " ".join(chunk.strip() for chunk in chunks)
        assert "Sentence number 0 states" in reconstructed
        assert "Sentence number 59 states" in reconstructed


class TestOverlapWindowEdge:
    def test_overlap_equal_to_chunk_length_returns_whole_chunk(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        text = " ".join(f"word{index}" for index in range(50))
        token_count = len(chunker.encoder.encode(text))
        assert chunker._get_overlap_text(text, token_count) == text


class TestModelFallback:
    def test_falsy_model_string_uses_default_encoding(self) -> None:
        assert TexChunker(model="").encoder.name == "cl100k_base"
