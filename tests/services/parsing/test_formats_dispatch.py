"""Dispatch tests for the aggregate parser-format table.

``deeptutor.services.parsing.engines.formats`` is the single lightweight
aggregate every upload/routing path consults: it must attribute each known
suffix to the engines that accept it, reject unknown suffixes, and stay
importable without pulling any optional parsing runtime. These tests cover
that module directly; per-adapter format tables are owned by
``tests/services/parsing/test_engines.py``.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from deeptutor.services.parsing.engines.docling.formats import (
    docling_supported_formats,
)
from deeptutor.services.parsing.engines.formats import known_parser_formats
from deeptutor.services.parsing.engines.liteparse.formats import (
    LITEPARSE_2_14_2_FORMATS,
)
from deeptutor.services.parsing.engines.markitdown.formats import (
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


def _engine_format_tables() -> dict[str, frozenset[str]]:
    return {
        "docling": docling_supported_formats(),
        "liteparse": LITEPARSE_2_14_2_FORMATS,
        "markitdown": markitdown_supported_formats(),
        "mineru": MINERU_SUPPORTED_FORMATS,
        "pymupdf4llm": PYMUPDF4LLM_1_28_2_FORMATS,
        "tika": TIKA_4_0_0_KNOWN_FORMATS,
    }


def _accepting_engines(suffix: str) -> tuple[str, ...]:
    return tuple(
        sorted(engine for engine, formats in _engine_format_tables().items() if suffix in formats)
    )


DISPATCH_TABLE: tuple[tuple[str, tuple[str, ...]], ...] = (
    (".pdf", ("docling", "liteparse", "markitdown", "mineru", "pymupdf4llm", "tika")),
    (".docx", ("docling", "liteparse", "markitdown", "mineru", "tika")),
    (".xlsx", ("docling", "liteparse", "markitdown", "mineru", "tika")),
    (".epub", ("docling", "markitdown", "pymupdf4llm", "tika")),
    (".md", ("docling", "markitdown", "pymupdf4llm", "tika")),
    (".html", ("docling", "markitdown", "tika")),
    (".dclg.xml", ("docling",)),
    (".boxnote", ("docling",)),
    (".ipynb", ("markitdown",)),
    (".tar.gz", ("docling", "tika")),
    (".numbers", ("liteparse", "tika")),
    (".key", ("liteparse", "tika")),
    (".jp2", ("mineru", "pymupdf4llm")),
    (".fb2", ("pymupdf4llm", "tika")),
    (".cbz", ("pymupdf4llm",)),
    (".hwp", ("tika",)),
    (".vsdx", ("tika",)),
    (".sqlite3", ("tika",)),
)


@pytest.mark.parametrize(("suffix", "expected_engines"), DISPATCH_TABLE)
def test_known_suffixes_dispatch_to_expected_engines(
    suffix: str, expected_engines: tuple[str, ...]
) -> None:
    known = known_parser_formats()
    assert suffix in known, f"{suffix} must stay dispatchable"
    assert _accepting_engines(suffix) == expected_engines


UNKNOWN_SUFFIXES: tuple[str, ...] = (
    "",
    ".xyz",
    ".pdf.exe",
    ".pdf7",
    ".docxx",
    " .pdf",
    ".pdf ",
    ".parquet",
    ".kdbx",
    ".blend",
)


@pytest.mark.parametrize("suffix", UNKNOWN_SUFFIXES)
def test_unknown_suffixes_default_to_not_dispatchable(suffix: str) -> None:
    assert suffix not in known_parser_formats()
    assert _accepting_engines(suffix) == ()


@pytest.mark.parametrize("suffix", [".pdf", ".docx", ".epub", ".ipynb", ".dclg.xml"])
def test_suffix_queries_are_case_sensitive_on_the_normalized_aggregate(
    suffix: str,
) -> None:
    known = known_parser_formats()
    assert suffix in known
    assert suffix.upper() not in known


def test_aggregate_public_surface_is_the_single_dispatch_callable() -> None:
    import deeptutor.services.parsing.engines.formats as formats_module

    assert formats_module.__all__ == ["known_parser_formats"]
    assert callable(known_parser_formats)
    known = known_parser_formats()
    assert isinstance(known, frozenset)
    assert known
    assert all(isinstance(suffix, str) for suffix in known)


def test_importing_the_aggregate_avoids_optional_parsing_runtimes() -> None:
    probe = (
        "import json, sys\n"
        "import deeptutor.services.parsing.engines.formats as formats_module\n"
        "known = formats_module.known_parser_formats()\n"
        "runtime_modules = sorted(\n"
        "    name for name in sys.modules\n"
        "    if name.split('.')[0] in\n"
        "    {'docling', 'torch', 'transformers', 'fitz', 'pymupdf', 'tika', 'liteparse'}\n"
        ")\n"
        "print(json.dumps({'known_size': len(known),\n"
        "                  'runtime_modules': runtime_modules,\n"
        "                  'has_pdf': '.pdf' in known}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["runtime_modules"] == []
    assert payload["has_pdf"] is True
    assert payload["known_size"] > 0
