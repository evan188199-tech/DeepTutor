"""Tests for the bilingual EPUB merge/generation module."""

from pathlib import Path
import zipfile

import pytest

from deeptutor.immersive_reading.bilingual.merge_epub import build_bilingual_epub
from tests.immersive_reading.bilingual._fixtures import make_minimal_epub


@pytest.fixture
def en_epub(tmp_path: Path) -> Path:
    path = tmp_path / "english.epub"
    make_minimal_epub(
        path,
        "Test Book",
        [
            ("Chapter One", ["The cat sat on the mat. It was nice.", "The dog ran fast."]),
            ("Chapter Two", ["Birds fly high in the sky above."]),
        ],
    )
    return path


@pytest.fixture
def zh_epub(tmp_path: Path) -> Path:
    path = tmp_path / "chinese.epub"
    make_minimal_epub(
        path,
        "測試書",
        [
            ("第一章", ["貓坐在墊子上。很好。", "狗跑得快。"]),
            ("第二章", ["鳥在天空中高飛。"]),
        ],
    )
    return path


def test_build_bilingual_epub_creates_valid_epub(en_epub: Path, zh_epub: Path, tmp_path: Path):
    output = tmp_path / "output.epub"
    chapter_map = [
        ["ch0", "chapter0.xhtml", "chapter0.xhtml"],
        ["ch1", "chapter1.xhtml", "chapter1.xhtml"],
    ]
    stats = build_bilingual_epub(en_epub, zh_epub, chapter_map, output)
    assert output.exists()
    assert output.stat().st_size > 0
    assert len(stats) == 2


def test_bilingual_epub_has_details_blocks(en_epub: Path, zh_epub: Path, tmp_path: Path):
    output = tmp_path / "output.epub"
    chapter_map = [["ch0", "chapter0.xhtml", "chapter0.xhtml"]]
    build_bilingual_epub(en_epub, zh_epub, chapter_map, output)

    with zipfile.ZipFile(output) as zf:
        ch0 = zf.read("chapter0.xhtml").decode("utf-8")
        assert 'class="zh-details"' in ch0
        assert "<summary" in ch0
        # English content preserved
        assert "cat" in ch0


def test_alternating_export_replaces_details_with_translation_blocks(
    en_epub: Path, zh_epub: Path, tmp_path: Path
):
    output = tmp_path / "output.epub"
    build_bilingual_epub(
        en_epub,
        zh_epub,
        [["ch0", "chapter0.xhtml", "chapter0.xhtml"]],
        output,
        style="alternating",
    )

    with zipfile.ZipFile(output) as archive:
        chapter = archive.read("chapter0.xhtml").decode("utf-8")

    assert 'class="zh-alternate"' in chapter
    assert "<details" not in chapter


def test_two_column_export_wraps_each_aligned_pair(en_epub: Path, zh_epub: Path, tmp_path: Path):
    output = tmp_path / "output.epub"
    build_bilingual_epub(
        en_epub,
        zh_epub,
        [["ch0", "chapter0.xhtml", "chapter0.xhtml"]],
        output,
        style="two_column",
    )

    with zipfile.ZipFile(output) as archive:
        chapter = archive.read("chapter0.xhtml").decode("utf-8")

    assert 'class="bilingual-row"' in chapter
    assert 'class="en-column"' in chapter
    assert 'class="zh-column"' in chapter


def test_translation_override_replaces_official_translation_in_export(
    en_epub: Path, zh_epub: Path, tmp_path: Path
):
    output = tmp_path / "output.epub"
    build_bilingual_epub(
        en_epub,
        zh_epub,
        [["ch0", "chapter0.xhtml", "chapter0.xhtml"]],
        output,
        translation_overrides={"ch0": ["任务译文"]},
    )

    with zipfile.ZipFile(output) as archive:
        chapter = archive.read("chapter0.xhtml").decode("utf-8")

    assert "任务译文" in chapter


def test_mimetype_is_first_and_uncompressed(en_epub: Path, zh_epub: Path, tmp_path: Path):
    output = tmp_path / "output.epub"
    build_bilingual_epub(en_epub, zh_epub, [["ch0", "chapter0.xhtml", "chapter0.xhtml"]], output)

    with zipfile.ZipFile(output) as zf:
        info = zf.infolist()[0]
        assert info.filename == "mimetype"
        assert info.compress_type == zipfile.ZIP_STORED


def test_opf_has_target_language(en_epub: Path, zh_epub: Path, tmp_path: Path):
    output = tmp_path / "output.epub"
    build_bilingual_epub(
        en_epub,
        zh_epub,
        [["ch0", "chapter0.xhtml", "chapter0.xhtml"]],
        output,
        target_lang="zh-Hant",
    )

    with zipfile.ZipFile(output) as zf:
        opf = zf.read("content.opf").decode("utf-8")
        assert "zh-Hant" in opf


def test_css_injected(en_epub: Path, zh_epub: Path, tmp_path: Path):
    output = tmp_path / "output.epub"
    build_bilingual_epub(en_epub, zh_epub, [["ch0", "chapter0.xhtml", "chapter0.xhtml"]], output)

    with zipfile.ZipFile(output) as zf:
        ch0 = zf.read("chapter0.xhtml").decode("utf-8")
        # CSS is injected either inline or into a linked stylesheet.
        # Since our minimal EPUB has no CSS, it should be inline.
        assert "zh-details" in ch0


def test_export_font_and_custom_css_are_sanitized(en_epub: Path, zh_epub: Path, tmp_path: Path):
    output = tmp_path / "output.epub"
    build_bilingual_epub(
        en_epub,
        zh_epub,
        [["ch0", "chapter0.xhtml", "chapter0.xhtml"]],
        output,
        font_family="Safe Font",
        custom_css="body { color: #123456; } </style><script>alert(1)</script>",
    )

    with zipfile.ZipFile(output) as archive:
        chapter = archive.read("chapter0.xhtml").decode("utf-8")

    assert '--dt-bilingual-font-family: "Safe Font",' in chapter
    assert "body { color: #123456; }" in chapter
    assert chapter.count("</style>") == 1
