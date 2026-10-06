from __future__ import annotations

import importlib.metadata

import pytest

from deeptutor.services.parsing.engines import _versions
from deeptutor.services.parsing.engines._versions import package_version, version_at_least


@pytest.fixture(autouse=True)
def _fresh_package_version_cache():
    package_version.cache_clear()
    yield
    package_version.cache_clear()


@pytest.mark.parametrize(
    ("version", "minimum", "expected"),
    [
        ("1.2.3", "1.2.3", True),
        ("1.2.4", "1.2.3", True),
        ("1.2.2", "1.2.3", False),
        ("1.2", "1.2.0", True),
        ("1.2", "1.2.1", False),
        ("1.2.0", "1.2", True),
        ("2.0", "1.99.99", True),
        ("1.10.0", "1.9.0", True),
        ("1.9.0", "1.10.0", False),
        ("  1.2.3  ", "1.2.3", True),
        ("1.2.3rc1", "1.2.3", True),
        ("1.2.3.post1", "1.2.3", True),
        ("0", "0", True),
        (None, "1.0.0", False),
        ("", "1.0.0", False),
        ("unknown", "1.0.0", False),
        ("1.2.3", "", False),
        ("1.2.3", None, False),
        ("1.2.3", "unknown", False),
    ],
)
def test_version_at_least_comparison_table(
    version: str | None, minimum: str, expected: bool
) -> None:
    assert version_at_least(version, minimum) is expected


def test_package_version_reads_installed_metadata(monkeypatch) -> None:
    monkeypatch.setattr(_versions.importlib.metadata, "version", lambda _name: "9.9.9")
    assert package_version("some-engine") == "9.9.9"


def test_package_version_falls_back_to_empty_when_distribution_missing(
    monkeypatch,
) -> None:
    def _missing(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError("some-engine")

    monkeypatch.setattr(_versions.importlib.metadata, "version", _missing)
    assert package_version("some-engine") == ""


def test_package_version_falls_back_to_empty_on_unexpected_error(monkeypatch) -> None:
    def _explode(_name: str) -> str:
        raise RuntimeError("resolver exploded")

    monkeypatch.setattr(_versions.importlib.metadata, "version", _explode)
    assert package_version("some-engine") == ""


def test_package_version_result_is_cached_per_name(monkeypatch) -> None:
    calls: list[str] = []

    def _fake(name: str) -> str:
        calls.append(name)
        return "3.2.1"

    monkeypatch.setattr(_versions.importlib.metadata, "version", _fake)
    assert package_version("engine-a") == "3.2.1"
    assert package_version("engine-a") == "3.2.1"
    assert calls == ["engine-a"]
    assert package_version("engine-b") == "3.2.1"
    assert calls == ["engine-a", "engine-b"]


def test_real_installed_distribution_resolves() -> None:
    version = package_version("pytest")
    assert version
    assert version_at_least(version, "0.0.1")
