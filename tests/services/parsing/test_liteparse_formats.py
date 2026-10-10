"""Table-driven boundary tests for the LiteParse version floor and format table."""

from __future__ import annotations

import importlib.metadata

import pytest

from deeptutor.services.parsing.engines import _versions
from deeptutor.services.parsing.engines.formats import known_parser_formats
from deeptutor.services.parsing.engines.liteparse import formats as liteparse_formats
from deeptutor.services.parsing.engines.liteparse.formats import (
    LITEPARSE_2_14_2_FORMATS,
    MIN_LITEPARSE_VERSION,
    installed_liteparse_version,
    liteparse_version_is_current,
)


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        pytest.param("2.14.2", True, id="floor-equality"),
        pytest.param("2.14.2.0", True, id="padded-equality"),
        pytest.param("2.14.3", True, id="patch-above-floor"),
        pytest.param("2.15.0", True, id="minor-above-floor"),
        pytest.param("3.0", True, id="major-above-floor-shorter-prefix"),
        pytest.param("2.140.0", True, id="numeric-component-not-lexical"),
        pytest.param("02.14.02", True, id="leading-zeros-normalized"),
        pytest.param("  2.14.2  ", True, id="surrounding-whitespace-stripped"),
        pytest.param("2.14.2rc1", True, id="pre-release-suffix-at-floor"),
        pytest.param("2.14.2a1", True, id="alpha-suffix-at-floor"),
        pytest.param("2.14.2b3", True, id="beta-suffix-at-floor"),
        pytest.param("2.14.2.dev0", True, id="dev-suffix-at-floor"),
        pytest.param("2.14.2.post1", True, id="post-suffix-at-floor"),
        pytest.param("2.14.2-1", True, id="hyphen-build-suffix-at-floor"),
        pytest.param("2.14.1", False, id="one-patch-below-floor"),
        pytest.param("2.14.1.999", False, id="older-base-with-larger-tail"),
        pytest.param("2.14", False, id="missing-patch-component"),
        pytest.param("2", False, id="only-major-component"),
        pytest.param("2.9", False, id="numeric-compare-not-lexical"),
        pytest.param("1.99.99", False, id="older-major"),
        pytest.param("0", False, id="zero-major"),
        pytest.param("2.14.1rc1", False, id="pre-release-suffix-below-floor"),
    ],
)
def test_liteparse_version_is_current_boundary(version: str | None, expected: bool) -> None:
    assert liteparse_version_is_current(version) is expected


@pytest.mark.parametrize(
    "version",
    [
        pytest.param("", id="empty-string"),
        pytest.param("   ", id="whitespace-only"),
        pytest.param("abc", id="no-digits"),
        pytest.param("v2.14.2", id="leading-v-prefix"),
        pytest.param("liteparse 2.14.2", id="leading-words"),
        pytest.param("2.x", id="partial-numeric-parse-pads-to-zero"),
        pytest.param(".2.14.2", id="leading-dot"),
    ],
)
def test_liteparse_version_is_current_malformed_degrades_to_false(version: str) -> None:
    assert liteparse_version_is_current(version) is False


def test_min_version_constant_is_self_satisfying() -> None:
    assert MIN_LITEPARSE_VERSION == "2.14.2"
    assert liteparse_version_is_current(MIN_LITEPARSE_VERSION) is True


def test_installed_version_reads_package_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        liteparse_formats, "package_version", lambda name: "2.14.9" if name == "liteparse" else ""
    )
    assert installed_liteparse_version() == "2.14.9"


def test_missing_package_degrades_to_not_current(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    _versions.package_version.cache_clear()
    monkeypatch.setattr(importlib.metadata, "version", raise_missing)
    try:
        assert installed_liteparse_version() == ""
        assert liteparse_version_is_current() is False
    finally:
        _versions.package_version.cache_clear()


@pytest.mark.parametrize(
    ("installed", "expected"),
    [
        pytest.param("2.14.2", True, id="installed-at-floor"),
        pytest.param("2.15.1", True, id="installed-above-floor"),
        pytest.param("2.14.1", False, id="installed-below-floor"),
        pytest.param("", False, id="installed-version-empty"),
    ],
)
def test_current_without_argument_reads_installed_version(
    monkeypatch: pytest.MonkeyPatch, installed: str, expected: bool
) -> None:
    monkeypatch.setattr(liteparse_formats, "package_version", lambda name: installed)
    assert liteparse_version_is_current() is expected


def test_explicit_version_argument_bypasses_installed_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(name: str) -> str:
        raise AssertionError("installed lookup must be bypassed when a version is given")

    monkeypatch.setattr(liteparse_formats, "package_version", fail)
    assert liteparse_version_is_current("2.14.2") is True
    assert liteparse_version_is_current("2.14.1") is False


def test_format_table_hygiene() -> None:
    assert isinstance(LITEPARSE_2_14_2_FORMATS, frozenset)
    assert len(LITEPARSE_2_14_2_FORMATS) == 27
    for suffix in LITEPARSE_2_14_2_FORMATS:
        assert suffix.startswith(".")
        assert suffix == suffix.lower()
        assert suffix.strip() == suffix
        assert " " not in suffix


@pytest.mark.parametrize(
    "suffix",
    [
        pytest.param(".pdf", id="pdf-native"),
        pytest.param(".rtf", id="rtf"),
        pytest.param(".csv", id="csv"),
        pytest.param(".tsv", id="tsv"),
        pytest.param(".doc", id="doc-libreoffice"),
        pytest.param(".docx", id="docx"),
        pytest.param(".docm", id="docm"),
        pytest.param(".xls", id="xls-libreoffice"),
        pytest.param(".xlsx", id="xlsx"),
        pytest.param(".xlsm", id="xlsm"),
        pytest.param(".ppt", id="ppt-libreoffice"),
        pytest.param(".pptx", id="pptx"),
        pytest.param(".pptm", id="pptm"),
        pytest.param(".key", id="iwork-keynote"),
        pytest.param(".pages", id="iwork-pages"),
        pytest.param(".numbers", id="iwork-numbers"),
        pytest.param(".odt", id="opendocument-text"),
        pytest.param(".ods", id="opendocument-sheet"),
        pytest.param(".odp", id="opendocument-slides"),
        pytest.param(".png", id="image-png-native"),
        pytest.param(".jpeg", id="image-jpeg-native"),
        pytest.param(".jpg", id="image-jpg-native"),
        pytest.param(".gif", id="image-gif-native"),
        pytest.param(".bmp", id="image-bmp-native"),
        pytest.param(".tiff", id="image-tiff-native"),
        pytest.param(".svg", id="image-svg-native"),
        pytest.param(".webp", id="image-webp-native"),
    ],
)
def test_declared_format_is_registered(suffix: str) -> None:
    assert suffix in LITEPARSE_2_14_2_FORMATS
    assert suffix in known_parser_formats()
