from __future__ import annotations

import builtins
import sys

import pytest

from deeptutor.services.parsing.engines.docling import formats

EXPECTED_DOCLING_2_123_1_EXTENSIONS = frozenset(
    {
        ".aac",
        ".adoc",
        ".asc",
        ".asciidoc",
        ".avi",
        ".bmp",
        ".boxnote",
        ".csv",
        ".dclg",
        ".dclg.xml",
        ".dclx",
        ".doc",
        ".docm",
        ".docx",
        ".dot",
        ".dotm",
        ".dotx",
        ".ebc",
        ".ebcdic",
        ".eml",
        ".epub",
        ".flac",
        ".htm",
        ".html",
        ".jpeg",
        ".jpg",
        ".json",
        ".latex",
        ".m4a",
        ".md",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".msg",
        ".nxml",
        ".odp",
        ".ods",
        ".odt",
        ".ogg",
        ".otp",
        ".ots",
        ".ott",
        ".pages",
        ".pdf",
        ".png",
        ".pot",
        ".potm",
        ".potx",
        ".pps",
        ".ppsm",
        ".ppsx",
        ".ppt",
        ".pptm",
        ".pptx",
        ".qmd",
        ".rmd",
        ".tar.gz",
        ".tex",
        ".text",
        ".tif",
        ".tiff",
        ".txt",
        ".vtt",
        ".wav",
        ".webm",
        ".webp",
        ".xbrl",
        ".xhtml",
        ".xls",
        ".xlsm",
        ".xlsx",
        ".xlt",
        ".xml",
    }
)


def test_public_surface() -> None:
    assert set(formats.__all__) == {
        "DOCLING_2_123_1_FORMATS",
        "MIN_DOCLING_VERSION",
        "docling_supported_formats",
        "docling_version_is_current",
        "installed_docling_version",
    }
    for name in formats.__all__:
        assert getattr(formats, name) is not None


def test_supported_formats_returns_the_static_table() -> None:
    snapshot = formats.docling_supported_formats()
    assert isinstance(snapshot, frozenset)
    assert snapshot is formats.DOCLING_2_123_1_FORMATS
    assert formats.docling_supported_formats() is snapshot


def test_format_table_matches_the_docling_floor_contract() -> None:
    assert formats.MIN_DOCLING_VERSION == "2.123.1"
    assert formats.DOCLING_2_123_1_FORMATS == EXPECTED_DOCLING_2_123_1_EXTENSIONS
    assert len(formats.DOCLING_2_123_1_FORMATS) == 74


@pytest.mark.parametrize(
    "entry",
    [
        ".pdf",
        ".docx",
        ".md",
        ".txt",
        ".text",
        ".html",
        ".epub",
        ".csv",
        ".json",
        ".tex",
        ".png",
        ".jpg",
        ".webp",
        ".tiff",
        ".mp3",
        ".wav",
        ".flac",
        ".m4a",
        ".mp4",
        ".mov",
        ".webm",
        ".mkv",
        ".pptx",
        ".xlsx",
        ".ods",
        ".odt",
        ".vtt",
        ".eml",
        ".xml",
        ".nxml",
        ".xhtml",
    ],
)
def test_format_table_covers_every_routed_media_category(entry: str) -> None:
    assert entry in formats.DOCLING_2_123_1_FORMATS


def test_format_table_includes_compound_suffixes() -> None:
    assert {".dclg", ".dclg.xml", ".dclx", ".tar.gz"} <= formats.DOCLING_2_123_1_FORMATS


def test_format_table_entries_are_normalized_extensions() -> None:
    for entry in formats.DOCLING_2_123_1_FORMATS:
        assert entry.startswith(".")
        assert entry == entry.lower()
        assert not entry.strip().isspace()
        assert len(entry) >= 2


def test_minimum_floor_version_is_current() -> None:
    assert formats.docling_version_is_current(formats.MIN_DOCLING_VERSION) is True


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("2.123.1", True),
        ("2.123.2", True),
        ("2.124.0", True),
        ("2.124", True),
        ("3.0", True),
        ("3.0.0", True),
        ("2.123.1.0", True),
        (" 2.123.1 ", True),
        ("2.123.1rc1", True),
        ("2.123.1.dev5", True),
        ("2.123.0", False),
        ("2.12.9", False),
        ("1.99.99", False),
        ("2", False),
        ("0", False),
        ("", False),
        ("   ", False),
        ("unknown", False),
        ("v2.130.0", False),
    ],
)
def test_version_check_against_the_compatibility_floor(version: str, expected: bool) -> None:
    assert formats.docling_version_is_current(version) is expected


def test_version_check_defaults_to_the_installed_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(formats, "package_version", lambda name: "2.130.0")
    assert formats.docling_version_is_current() is True
    assert formats.docling_version_is_current(None) is True

    monkeypatch.setattr(formats, "package_version", lambda name: "2.0.0")
    assert formats.docling_version_is_current() is False
    assert formats.docling_version_is_current(None) is False


def test_missing_install_degrades_to_a_failed_version_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(formats, "package_version", lambda name: "")
    assert formats.installed_docling_version() == ""
    assert formats.docling_version_is_current() is False


def test_installed_docling_version_delegates_to_the_package_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, str] = {}

    def fake_package_version(name: str) -> str:
        seen["name"] = name
        return "2.131.0"

    monkeypatch.setattr(formats, "package_version", fake_package_version)
    assert formats.installed_docling_version() == "2.131.0"
    assert seen == {"name": "docling"}


def test_helpers_run_without_importing_the_docling_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def forbidden(name: str, *args: object, **kwargs: object) -> object:
        if name == "docling" or name.startswith("docling."):
            raise AssertionError(f"docling runtime import attempted: {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", forbidden)
    before = frozenset(sys.modules)

    assert formats.docling_supported_formats()
    monkeypatch.setattr(formats, "package_version", lambda name: "2.123.1")
    assert formats.docling_version_is_current() is True

    added = set(sys.modules) - before
    assert not [name for name in added if name == "docling" or name.startswith("docling.")]
