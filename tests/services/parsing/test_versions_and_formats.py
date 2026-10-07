"""Boundary tests for parser version negotiation and aggregate format registration."""

from __future__ import annotations

import importlib.metadata

from deeptutor.services.parsing.engines._versions import (
    package_version,
    version_at_least,
)
from deeptutor.services.parsing.engines.docling.formats import (
    docling_supported_formats,
)
from deeptutor.services.parsing.engines.formats import known_parser_formats
from deeptutor.services.parsing.engines.liteparse.formats import (
    LITEPARSE_2_14_2_FORMATS,
)
from deeptutor.services.parsing.engines.markitdown.formats import (
    MARKITDOWN_0_1_7_FORMATS,
    markitdown_supported_formats,
)
from deeptutor.services.parsing.engines.mineru.formats import (
    MINERU_SUPPORTED_FORMATS,
)
from deeptutor.services.parsing.engines.pymupdf4llm.formats import (
    PYMUPDF4LLM_1_28_2_FORMATS,
)
from deeptutor.services.parsing.engines.tika.formats import (
    TIKA_4_0_0_KNOWN_FORMATS,
)


def test_package_version_reads_installed_distribution() -> None:
    assert package_version("pytest") == importlib.metadata.version("pytest")


def test_package_version_unknown_package_returns_empty() -> None:
    assert package_version("definitely-not-an-installed-dt-package") == ""


def test_version_at_least_pads_missing_release_components() -> None:
    assert version_at_least("1.2", "1.2") is True
    assert version_at_least("1.2", "1.2.0") is True
    assert version_at_least("1.2.0", "1.2") is True
    assert version_at_least("1.2", "1.2.1") is False
    assert version_at_least("1.2", "1.1.9") is True
    assert version_at_least("2", "1.99.99") is True
    assert version_at_least("1.0.0.0", "1.0") is True


def test_version_at_least_compares_numerically_not_lexically() -> None:
    assert version_at_least("1.10.0", "1.9.0") is True
    assert version_at_least("0.9", "0.10") is False
    assert version_at_least("10", "9") is True


def test_version_at_least_rejects_malformed_versions() -> None:
    assert version_at_least(None, "1.0") is False
    assert version_at_least("", "1.0") is False
    assert version_at_least("abc", "1.0") is False
    assert version_at_least("not a version", "0") is False
    assert version_at_least("1.0", "") is False
    assert version_at_least("1.0", None) is False
    assert version_at_least("v1.2.3", "1.2.3") is False


def test_version_at_least_ignores_non_numeric_suffixes() -> None:
    assert version_at_least("1.2.3-beta", "1.2.3") is True
    assert version_at_least("1.2.3rc1", "1.2.3") is True
    assert version_at_least("3.4.5  (build 7)", "3.4.5") is True
    assert version_at_least("1.2.3-beta", "1.2.4") is False


def test_known_parser_formats_unions_every_registered_engine() -> None:
    engine_sets = (
        docling_supported_formats(),
        markitdown_supported_formats(),
        MINERU_SUPPORTED_FORMATS,
        LITEPARSE_2_14_2_FORMATS,
        PYMUPDF4LLM_1_28_2_FORMATS,
        TIKA_4_0_0_KNOWN_FORMATS,
    )
    known = known_parser_formats()
    assert isinstance(known, frozenset)
    assert known == frozenset().union(*engine_sets)
    for engine_set in engine_sets:
        assert engine_set <= known
    assert MARKITDOWN_0_1_7_FORMATS <= known


def test_known_parser_formats_registration_hygiene() -> None:
    known = known_parser_formats()
    assert known
    for suffix in known:
        assert suffix.startswith(".")
        assert suffix == suffix.lower()
        assert suffix.strip() == suffix
        assert " " not in suffix
    assert ".pdf" in known
    assert ".docx" in known
    assert ".md" in known
    assert ".dclg.xml" in known
    assert ".tar.gz" in known
