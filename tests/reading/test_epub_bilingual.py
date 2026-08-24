"""Engine tests for explicit bilingual EPUB pairing."""

from __future__ import annotations

import base64
from pathlib import Path
import zipfile

from deeptutor.reading.epub_bilingual import (
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


def test_explicit_pairing_stores_metadata_without_deriving_material(tmp_path: Path) -> None:
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

    material_ids = {row.material_id for row in store.list_materials()}
    pairing = create_epub_pairing(store, english.material_id, chinese.material_id)

    assert pairing["english_material_id"] == english.material_id
    assert pairing["chinese_material_id"] == chinese.material_id
    assert pairing["english_language"] == "en"
    assert pairing["chinese_language"] == "zh"
    assert pairing["status"] == "confirmed"
    assert list_epub_pairings(store) == [pairing]
    assert {row.material_id for row in store.list_materials()} == material_ids

    assert delete_epub_pairing(store, pairing["pairing_id"]) is True
    assert list_epub_pairings(store) == []
    assert {row.material_id for row in store.list_materials()} == material_ids
