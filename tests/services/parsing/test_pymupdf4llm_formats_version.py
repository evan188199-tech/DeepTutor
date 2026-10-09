from __future__ import annotations

import pytest

from deeptutor.services.parsing.engines import _versions
from deeptutor.services.parsing.engines.pymupdf4llm import formats as pymupdf_formats
from deeptutor.services.parsing.engines.pymupdf4llm.formats import (
    MIN_PYMUPDF4LLM_VERSION,
    installed_pymupdf4llm_version,
    pymupdf4llm_version_is_current,
)


def _install_version(monkeypatch: pytest.MonkeyPatch, version: str) -> list[str]:
    seen: list[str] = []

    def fake_package_version(name: str) -> str:
        seen.append(name)
        return version

    monkeypatch.setattr(pymupdf_formats, "package_version", fake_package_version)
    return seen


def test_version_floor_admits_itself_and_above() -> None:
    assert pymupdf4llm_version_is_current(MIN_PYMUPDF4LLM_VERSION) is True
    assert pymupdf4llm_version_is_current("1.28.2.1") is True
    assert pymupdf4llm_version_is_current("1.29") is True
    assert pymupdf4llm_version_is_current("2.0") is True


def test_version_below_floor_is_rejected() -> None:
    assert pymupdf4llm_version_is_current("1.28.1") is False
    assert pymupdf4llm_version_is_current("1.28") is False
    assert pymupdf4llm_version_is_current("1") is False
    assert pymupdf4llm_version_is_current("0.99.9") is False


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("1.28.2.dev5", True),
        ("1.28.2rc1", True),
        (" 1.28.2 ", True),
        ("1.28.2.0", True),
        ("1.28.x", False),
        ("v1.28.2", False),
        ("-1.28.2", False),
        ("1.28.2 ", True),
    ],
)
def test_version_comparison_uses_numeric_release_prefix(version: str, expected: bool) -> None:
    assert pymupdf4llm_version_is_current(version) is expected


@pytest.mark.parametrize(
    "version",
    ["", "   ", "abc", "unknown", "not.a.version", "....."],
)
def test_unparseable_versions_are_not_current(version: str) -> None:
    assert pymupdf4llm_version_is_current(version) is False


def test_installed_version_resolves_distribution_name(monkeypatch) -> None:
    seen = _install_version(monkeypatch, "1.30.0")

    assert installed_pymupdf4llm_version() == "1.30.0"
    assert seen == ["pymupdf4llm"]


@pytest.mark.parametrize(
    ("installed", "expected"),
    [
        ("1.28.2", True),
        ("1.28.1", False),
        ("1.30.0", True),
        ("", False),
    ],
)
def test_none_version_falls_back_to_installed(monkeypatch, installed: str, expected: bool) -> None:
    _install_version(monkeypatch, installed)

    assert pymupdf4llm_version_is_current() is expected
    assert pymupdf4llm_version_is_current(None) is expected


def test_missing_package_degrades_to_not_current(monkeypatch) -> None:
    _install_version(monkeypatch, "")

    assert installed_pymupdf4llm_version() == ""
    assert pymupdf4llm_version_is_current() is False


def test_version_lookup_swallows_missing_distribution() -> None:
    try:
        assert _versions.package_version("definitely-missing-dist-agen1333") == ""
    finally:
        _versions.package_version.cache_clear()
