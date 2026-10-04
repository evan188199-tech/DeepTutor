"""Shared bilingual session over a confirmed EPUB pairing (#860 slices 2+4)."""

from __future__ import annotations

from pathlib import Path
import zipfile

import pytest

from deeptutor.reading.epub_bilingual import create_epub_pairing
from deeptutor.reading.epub_pair_session import (
    aligned_excerpt,
    map_locator,
    mirror_pair_position,
    pairing_for_material,
)
from deeptutor.reading.models import ReadingPosition
from deeptutor.reading.store import ReadingStore

EN_TWO = [
    ("Water", ["Water flows downhill.", "Rivers carve the valley."]),
    ("Stone", ["Stone remembers nothing.", "Quarries keep their silence."]),
]
ZH_TWO = [
    ("水", ["水往低处流。", "河流刻出山谷。"]),
    ("石", ["石头什么都不记得。", "采石场保持沉默。"]),
]


def _write_epub(path: Path, *, language: str, chapters: list[tuple[str, list[str]]]) -> Path:
    items = "".join(
        f"<item id='c{index}' href='c{index}.xhtml' media-type='application/xhtml+xml'/>"
        for index in range(1, len(chapters) + 1)
    )
    spine = "".join(f"<itemref idref='c{index}'/>" for index in range(1, len(chapters) + 1))
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            "<container xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>"
            "<rootfiles><rootfile full-path='OPS/book.opf'/></rootfiles></container>",
        )
        archive.writestr(
            "OPS/book.opf",
            "<package xmlns='http://www.idpf.org/2007/opf' "
            "xmlns:dc='http://purl.org/dc/elements/1.1/' version='3.0'>"
            "<metadata><dc:identifier>urn:uuid:pair-session</dc:identifier>"
            "<dc:title>Pair session book</dc:title>"
            f"<dc:language>{language}</dc:language>"
            "<dc:creator>Fixture Author</dc:creator></metadata>"
            f"<manifest>{items}</manifest><spine>{spine}</spine></package>",
        )
        for index, (title, paragraphs) in enumerate(chapters, start=1):
            body = "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)
            archive.writestr(
                f"OPS/c{index}.xhtml",
                "<html xmlns='http://www.w3.org/1999/xhtml'><head><title>"
                f"{title}</title></head><body><h1>{title}</h1>{body}</body></html>",
            )
    return path


def _paired_store(tmp_path: Path, *, english=EN_TWO, chinese=ZH_TWO):
    store = ReadingStore(root=tmp_path / "materials")
    en = store.ingest(_write_epub(tmp_path / "en.epub", language="en", chapters=english))
    zh = store.ingest(_write_epub(tmp_path / "zh.epub", language="zh", chapters=chinese))
    create_epub_pairing(store, en.material_id, zh.material_id)
    return store, en, zh


def test_pairing_lookup_finds_the_confirmed_pair(tmp_path: Path) -> None:
    store, en, zh = _paired_store(tmp_path)
    pairing = pairing_for_material(store, en.material_id)
    assert pairing is not None and pairing["chinese_material_id"] == zh.material_id
    assert pairing_for_material(store, zh.material_id)["english_material_id"] == en.material_id  # type: ignore[index]


def test_mirror_shares_section_and_scroll_across_both_editions(tmp_path: Path) -> None:
    store, en, zh = _paired_store(tmp_path)
    result = mirror_pair_position(
        store, en.material_id, ReadingPosition(locator=2, percentage=0.42)
    )
    assert result is not None and result["mirrored"] is True
    shared = store.position(zh.material_id)
    assert shared.locator == 2
    assert shared.percentage == pytest.approx(0.42)
    # The reader's own edition keeps its own saved viewport.
    assert store.position(en.material_id).locator == 1


def test_mirror_maps_sections_proportionally_when_lengths_differ(tmp_path: Path) -> None:
    english_four = [(f"Part {index}", [f"English line {index}."]) for index in range(1, 5)]
    chinese_two = [("一", ["第一段。"]), ("二", ["第二段。"])]
    store, en, zh = _paired_store(tmp_path, english=english_four, chinese=chinese_two)
    assert map_locator(store, en.material_id, zh.material_id, 1) == 1
    assert map_locator(store, en.material_id, zh.material_id, 3) == 2
    assert map_locator(store, en.material_id, zh.material_id, 4) == 2
    assert map_locator(store, en.material_id, zh.material_id, 99) is None
    result = mirror_pair_position(store, en.material_id, ReadingPosition(locator=4, percentage=0.9))
    assert result is not None and result["mirrored"] is True
    assert store.position(zh.material_id).locator == 2


def test_mirror_without_a_confirmed_pairing_is_a_noop(tmp_path: Path) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    en = store.ingest(_write_epub(tmp_path / "en.epub", language="en", chapters=EN_TWO))
    assert mirror_pair_position(store, en.material_id, ReadingPosition(locator=1)) is None


def test_aligned_excerpt_returns_the_opposite_paragraph_without_a_model(tmp_path: Path) -> None:
    store, en, _zh = _paired_store(tmp_path)
    result = aligned_excerpt(store, en.material_id, locator=2, quote="Quarries keep their silence.")
    assert result["status"] == "aligned"
    assert result["granularity"] == "paragraph"
    assert result["degraded"] is False
    assert result["excerpt"] == "采石场保持沉默。"
    assert result["opposite_locator"] == 2


def test_sentence_selection_degrades_to_the_aligned_paragraph(tmp_path: Path) -> None:
    store, en, _zh = _paired_store(tmp_path)
    result = aligned_excerpt(store, en.material_id, locator=1, quote="flows downhill")
    assert result["status"] == "aligned"
    assert result["degraded"] is True
    assert result["granularity"] == "paragraph"
    assert result["excerpt"] == "水往低处流。"


def test_alignment_failure_never_returns_unrelated_text(tmp_path: Path) -> None:
    mismatched = [
        ("水", ["两个句子合并成了一段。水往低处流，河流刻出山谷。"]),
        ("石", ["石头什么都不记得。"]),
    ]
    store, en, _zh = _paired_store(tmp_path, chinese=mismatched)
    result = aligned_excerpt(store, en.material_id, locator=1, quote="Rivers carve the valley.")
    assert result["status"] == "paragraph_unaligned"
    assert result["excerpt"] == ""

    unknown = aligned_excerpt(store, en.material_id, locator=1, quote="Not in this book.")
    assert unknown["status"] == "quote_not_found"
    assert unknown["excerpt"] == ""


def test_aligned_excerpt_requires_a_confirmed_pairing(tmp_path: Path) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    en = store.ingest(_write_epub(tmp_path / "en.epub", language="en", chapters=EN_TWO))
    result = aligned_excerpt(store, en.material_id, locator=1, quote="Water flows downhill.")
    assert result["status"] == "unpaired"
    assert result["excerpt"] == ""


def test_aligned_excerpt_truncates_oversized_paragraphs(tmp_path: Path) -> None:
    long_zh = [
        ("水", ["水往低处流。" * 400, "河流刻出山谷。"]),
        ("石", ["石头什么都不记得。", "采石场保持沉默。"]),
    ]
    store, en, _zh = _paired_store(tmp_path, chinese=long_zh)
    result = aligned_excerpt(
        store, en.material_id, locator=1, quote="Water flows downhill.", max_chars=120
    )
    assert result["status"] == "aligned"
    assert result["excerpt_truncated"] is True
    assert len(result["excerpt"]) == 120
