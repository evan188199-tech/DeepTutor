"""Focused page-level citation resolution for source visuals (#1610)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
import pymupdf

from deeptutor.services.parsing.types import ParsedDocument
from deeptutor.services.rag.source_visuals import (
    figure_labels,
    figure_references,
    retrieve_visual,
)
from deeptutor.services.rag.visual_assets import VisualAssetStore, collect_visual_assets


def _publish_kb(tmp_path: Path, name: str, *, pages: int, figure_page: int | None) -> Path:
    kb = tmp_path / "kb"
    (kb / "raw").mkdir(parents=True, exist_ok=True)
    images = tmp_path / "parse" / name.replace(".", "_")
    images.mkdir(parents=True, exist_ok=True)
    image = images / "figure.png"
    Image.new("RGB", (24, 16), color=(9, 60, 120)).save(image)
    source = kb / "raw" / name
    pdf = pymupdf.open()
    blocks = []
    for index in range(pages):
        page = pdf.new_page()
        page.insert_text((50, 50), f"Page {index + 1} narrative text")
        if figure_page == index + 1:
            page.insert_text((50, 70), "Figure 9.9: shared learning curve")
            page.insert_image(pymupdf.Rect(50, 90, 200, 180), filename=str(image))
            blocks.append(
                {
                    "type": "image",
                    "img_path": str(image),
                    "page_idx": index,
                    "image_caption": ["Figure 9.9"],
                    "section": "Chapter 9",
                    "text": "shared learning curve",
                }
            )
    pdf.save(source, deflate=True)
    pdf.close()
    if blocks:
        parsed = ParsedDocument(
            markdown="",
            blocks=blocks,
            asset_dir=images,
            parser_signature="synthetic-pages",
            engine="synthetic",
        )
        VisualAssetStore(kb).publish(collect_visual_assets(parsed, source, kb))
    return kb


def test_page_reference_in_query_renders_that_exact_page(tmp_path):
    kb = _publish_kb(tmp_path, "book.pdf", pages=3, figure_page=3)
    evidence = retrieve_visual(kb, "kb", query="请展示第 3 页")
    assert not evidence.error
    record, pixels = evidence.images[0]
    assert record["kind"] == "source_page"
    assert record["page_number"] == 3
    assert record["source_path"] == "book.pdf"
    assert record["source_locator"] == "page:3"
    assert "shared learning curve" in record["page_context"]
    assert evidence.sources[0]["page"] == 3
    assert evidence.sources[0]["url"].endswith("#page=3")
    parts = evidence.model_message()["content"]
    assert [part["type"] for part in parts] == ["text", "image_url"]
    assert parts[0]["text"].startswith("Source evidence: page:3")
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_page_reference_without_source_path_requires_unambiguous_document(tmp_path):
    kb = _publish_kb(tmp_path, "book.pdf", pages=3, figure_page=3)
    scoped = retrieve_visual(kb, "kb", query="explain page 3")
    assert not scoped.error
    assert scoped.images[0][0]["source_path"] == "book.pdf"
    _publish_kb(tmp_path, "other.pdf", pages=3, figure_page=3)
    ambiguous = retrieve_visual(kb, "kb", query="explain page 3")
    assert ambiguous.error == "ambiguous_source"
    assert not ambiguous.images


def test_out_of_range_page_numbers_fail_visibly(tmp_path):
    kb = _publish_kb(tmp_path, "book.pdf", pages=3, figure_page=3)
    for page in (0, 4):
        evidence = retrieve_visual(kb, "kb", source_path="book.pdf", page=page)
        assert evidence.error == "page_unavailable"
        assert not evidence.images
        assert "between 1 and 3" in evidence.content


def test_printed_label_on_two_pages_is_ambiguous_not_substituted(tmp_path):
    kb = tmp_path / "kb"
    (kb / "raw").mkdir(parents=True)
    source = kb / "raw" / "sparse.pdf"
    pdf = pymupdf.open()
    for index in range(3):
        page = pdf.new_page()
        if index in (0, 2):
            page.insert_text((60, 60), f"As Figure 9.9 shows, the curve rises on page {index + 1}.")
        else:
            page.insert_text((60, 60), "Plain narrative without figure references.")
    pdf.save(source, deflate=True)
    pdf.close()
    evidence = retrieve_visual(kb, "kb", source_path="sparse.pdf", figure="Figure 9.9")
    assert evidence.error == "ambiguous_page"
    assert not evidence.images
    assert "[1, 3]" in evidence.content


def test_bilingual_figure_references_dedupe_and_keep_their_kind():
    text = "Compare Fig. 3 with Figure 3 and 表4 / Table 4"
    assert figure_labels(text) == ["3", "4"]
    assert figure_references(text) == ["figure:3", "table:4"]


def test_multiple_explicit_labels_ask_for_separate_calls(tmp_path):
    kb = _publish_kb(tmp_path, "book.pdf", pages=3, figure_page=3)
    evidence = retrieve_visual(kb, "kb", source_path="book.pdf", figure="Figure 9.9 图2")
    assert evidence.error == "multiple_references"
    assert not evidence.images
