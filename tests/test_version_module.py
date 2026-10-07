"""Tests for the single-source version module."""

from __future__ import annotations

from pathlib import Path
import re
import tomllib

import pytest

import deeptutor.__version__ as version_module

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DISTRIBUTIONS = (
    "pyproject.toml",
    "packaging/deeptutor-cli/pyproject.toml",
)


def test_version_is_a_release_version_string() -> None:
    assert isinstance(version_module.__version__, str)
    assert re.fullmatch(r"\d+\.\d+\.\d+", version_module.__version__)
    assert version_module.__version__


def test_public_surface_declares_only_the_version() -> None:
    assert version_module.__all__ == ("__version__",)


@pytest.mark.parametrize("relative", DISTRIBUTIONS)
def test_each_distribution_reads_its_version_from_this_module(relative: str) -> None:
    with (REPOSITORY_ROOT / relative).open("rb") as file:
        metadata = tomllib.load(file)

    assert metadata["project"]["dynamic"] == ["version"]
    assert metadata["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "deeptutor.__version__.__version__"
    }
