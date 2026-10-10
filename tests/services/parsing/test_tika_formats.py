"""Boundary tests for the Tika version floor and input-format routing hints."""

from __future__ import annotations

import pytest

from deeptutor.services.parsing.engines.formats import known_parser_formats
from deeptutor.services.parsing.engines.tika import formats as tika_formats
from deeptutor.services.parsing.engines.tika.formats import (
    MIN_TIKA_VERSION,
    TIKA_4_0_0_KNOWN_FORMATS,
    tika_version_is_current,
)


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        pytest.param("4.0.0", True, id="floor-equality-bare"),
        pytest.param("Apache Tika 4.0.0", True, id="floor-equality-banner"),
        pytest.param("4.0.0.0", True, id="padded-equality"),
        pytest.param("4.0.1", True, id="patch-above-floor"),
        pytest.param("4.1", True, id="minor-above-floor-shorter-prefix"),
        pytest.param("5.0.0", True, id="major-above-floor"),
        pytest.param("4.0.10", True, id="numeric-component-not-lexical"),
        pytest.param("04.0.0", True, id="leading-zeros-normalized"),
        pytest.param("  4.0.0  ", True, id="surrounding-whitespace-stripped"),
        pytest.param("v4.0.0", True, id="leading-v-prefix-searched-through"),
        pytest.param("4.0.0-SNAPSHOT", True, id="snapshot-suffix-at-floor"),
        pytest.param("4.0.0-dev", True, id="dev-suffix-at-floor"),
        pytest.param("4.0.0 or later", True, id="floor-match-then-prose"),
        pytest.param("3.9.9", False, id="one-patch-below-floor"),
        pytest.param("3.9.9-rc1", False, id="pre-release-suffix-below-floor"),
        pytest.param("3.10", False, id="numeric-compare-not-lexical"),
        pytest.param("1.99.99", False, id="older-major"),
        pytest.param("1.9.9 and then 4.0.0", False, id="first-version-extract-wins"),
        pytest.param("Tika 3.2.3 (compat 4.0.0)", False, id="parenthetical-later-version-ignored"),
    ],
)
def test_tika_version_is_current_boundary(version: str | None, expected: bool) -> None:
    assert tika_version_is_current(version) is expected


@pytest.mark.parametrize(
    "version",
    [
        pytest.param(None, id="none-version"),
        pytest.param("", id="empty-string"),
        pytest.param("   ", id="whitespace-only"),
        pytest.param("Apache Tika", id="banner-without-digits"),
        pytest.param("no digits here", id="prose-without-digits"),
        pytest.param("4", id="bare-major-needs-a-dot-to-extract"),
        pytest.param("version unknown", id="unknown-placeholder"),
        pytest.param("x.y.z", id="dotted-non-numeric"),
    ],
)
def test_tika_version_is_current_malformed_degrades_to_false(version: str | None) -> None:
    assert tika_version_is_current(version) is False


def test_min_version_constant_is_self_satisfying() -> None:
    assert MIN_TIKA_VERSION == "4.0.0"
    assert tika_version_is_current(MIN_TIKA_VERSION) is True


def test_format_table_hygiene() -> None:
    assert isinstance(TIKA_4_0_0_KNOWN_FORMATS, frozenset)
    assert len(TIKA_4_0_0_KNOWN_FORMATS) == 179
    for suffix in TIKA_4_0_0_KNOWN_FORMATS:
        assert suffix.startswith(".")
        assert suffix == suffix.lower()
        assert suffix.strip() == suffix
        assert " " not in suffix
        assert not suffix.endswith(".")


def test_tar_gz_is_the_only_compound_suffix() -> None:
    compound = {suffix for suffix in TIKA_4_0_0_KNOWN_FORMATS if suffix.count(".") > 1}
    assert compound == {".tar.gz"}


@pytest.mark.parametrize(
    "suffix",
    [
        pytest.param(".pdf", id="document-portable"),
        pytest.param(".epub", id="document-ebook"),
        pytest.param(".docx", id="office-word"),
        pytest.param(".xlsx", id="office-excel"),
        pytest.param(".pptx", id="office-powerpoint"),
        pytest.param(".odt", id="opendocument-text"),
        pytest.param(".pages", id="iwork-pages"),
        pytest.param(".hwp", id="hwp"),
        pytest.param(".html", id="web-html"),
        pytest.param(".md", id="web-markdown"),
        pytest.param(".eml", id="mail-eml"),
        pytest.param(".msg", id="mail-msg"),
        pytest.param(".mbox", id="mail-mbox"),
        pytest.param(".zip", id="archive-zip"),
        pytest.param(".tar.gz", id="archive-compound-tar-gz"),
        pytest.param(".7z", id="archive-seven-zip"),
        pytest.param(".jpeg", id="image-jpeg"),
        pytest.param(".png", id="image-png"),
        pytest.param(".heic", id="image-heic"),
        pytest.param(".mp3", id="audio-mp3"),
        pytest.param(".flac", id="audio-flac"),
        pytest.param(".mp4", id="video-mp4"),
        pytest.param(".mkv", id="video-mkv"),
        pytest.param(".dwg", id="cad-dwg"),
        pytest.param(".h5", id="science-hdf5"),
        pytest.param(".sqlite3", id="database-sqlite"),
        pytest.param(".ttf", id="font-ttf"),
        pytest.param(".p12", id="crypto-pkcs12"),
        pytest.param(".exe", id="executable-pe"),
    ],
)
def test_declared_routing_hint_covers_every_category(suffix: str) -> None:
    assert suffix in TIKA_4_0_0_KNOWN_FORMATS


def test_hint_table_is_upload_hint_not_engine_advertised_formats() -> None:
    """ParseService sees a server-authoritative empty set, not the local hint."""

    from deeptutor.services.parsing.engines import factory

    assert factory.get_parser("tika").supported_formats() == frozenset()
    assert TIKA_4_0_0_KNOWN_FORMATS != frozenset()
    assert TIKA_4_0_0_KNOWN_FORMATS <= known_parser_formats()


def test_public_surface_is_pinned() -> None:
    assert set(tika_formats.__all__) == {
        "MIN_TIKA_VERSION",
        "TIKA_4_0_0_KNOWN_FORMATS",
        "tika_version_is_current",
    }
