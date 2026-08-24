"""Engine tests for explicit bilingual EPUB pairing."""

from __future__ import annotations

import base64
import io
from pathlib import Path
import zipfile

from deeptutor.reading.epub_bilingual import (
    _inject_chapter,
    build_bilingual_epub,
    create_epub_pairing,
    delete_epub_pairing,
    list_epub_pairings,
    recommend_epub_candidates,
)
from deeptutor.reading.store import ReadingStore

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def _write_epub(
    path: Path,
    *,
    language: str,
    chapter: str,
    paragraph: str,
    include_image: bool = False,
) -> Path:
    image_manifest = (
        "<item id='picture' href='picture.png' media-type='image/png'/>" if include_image else ""
    )
    image_body = (
        "<img src='picture.png' alt='source illustration' width='240' height='80'/>"
        if include_image
        else ""
    )
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
            "<metadata><dc:identifier>urn:uuid:bilingual-test</dc:identifier>"
            f"<dc:title>Bilingual test</dc:title><dc:language>{language}</dc:language>"
            "<dc:creator>Fixture Author</dc:creator></metadata>"
            f"<manifest><item id='one' href='one.xhtml' media-type='application/xhtml+xml'/>{image_manifest}</manifest>"
            "<spine><itemref idref='one'/></spine></package>",
        )
        archive.writestr(
            "OPS/one.xhtml",
            "<html xmlns='http://www.w3.org/1999/xhtml'><head><title>"
            f"{chapter}</title></head><body><h1>{chapter}</h1>"
            f"<p>{paragraph}</p>{image_body}</body></html>",
        )
        if include_image:
            archive.writestr("OPS/picture.png", PNG_BYTES)
    return path


def test_candidates_rank_a_different_language_edition_without_auto_pairing(
    tmp_path: Path,
) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    english = store.ingest(
        _write_epub(
            tmp_path / "english.epub",
            language="en",
            chapter="Illustrated chapter",
            paragraph="English source paragraph.",
            include_image=True,
        )
    )
    chinese = store.ingest(
        _write_epub(
            tmp_path / "chinese.epub",
            language="zh-CN",
            chapter="插图章节",
            paragraph="中文来源段落。",
        )
    )

    candidates = recommend_epub_candidates(store, english.material_id)

    assert candidates[0]["material_id"] == chinese.material_id
    assert candidates[0]["reasons"]["identifier"] is True
    assert candidates[0]["reasons"]["different_language"] is True
    assert list_epub_pairings(store) == []


def test_bilingual_revision_preserves_english_resources_and_collapses_chinese(
    tmp_path: Path,
) -> None:
    english = _write_epub(
        tmp_path / "english.epub",
        language="en",
        chapter="Illustrated chapter",
        paragraph="English source paragraph.",
        include_image=True,
    )
    chinese = _write_epub(
        tmp_path / "chinese.epub",
        language="zh",
        chapter="插图章节",
        paragraph="中文翻译段落。",
    )

    result = zipfile.ZipFile(io.BytesIO(build_bilingual_epub(english, chinese)))
    document = result.read("OPS/one.xhtml").decode("utf-8")

    assert result.read("OPS/picture.png") == PNG_BYTES
    assert 'data-deeptutor-bilingual="true"' in document
    assert '<details class="dt-bilingual-zh"' in document
    assert '<details class="dt-bilingual-zh" open=' not in document
    assert "中文翻译段落。" in document


def test_fewer_translations_than_blocks_are_marked_low_confidence() -> None:
    source = "<html><body><p>First</p><p>Second</p></body></html>"

    result, inserted = _inject_chapter(source, ["第一段"])

    assert inserted == 1
    assert 'data-low-confidence="true"' in result


def test_explicit_pairing_creates_and_preserves_a_derived_epub(tmp_path: Path) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    english = store.ingest(
        _write_epub(
            tmp_path / "english.epub",
            language="en",
            chapter="Illustrated chapter",
            paragraph="English source paragraph.",
            include_image=True,
        )
    )
    chinese = store.ingest(
        _write_epub(
            tmp_path / "chinese.epub",
            language="zh",
            chapter="插图章节",
            paragraph="中文来源段落。",
        )
    )

    pairing, derived = create_epub_pairing(store, english.material_id, chinese.material_id)

    assert derived.render_mode == "epub"
    assert store.raw_path(derived.material_id) is not None
    assert pairing["material_id"] == derived.material_id
    assert list_epub_pairings(store) == [pairing]

    assert delete_epub_pairing(store, pairing["pairing_id"]) is True
    assert list_epub_pairings(store) == []
    assert store.exists(derived.material_id)
