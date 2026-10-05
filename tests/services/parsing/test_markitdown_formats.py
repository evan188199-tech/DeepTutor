"""Regression contract for the markitdown converter-format probe.

``deeptutor/services/parsing/engines/markitdown/formats.py`` discovers the
extensions ``markitdown.converters`` advertises by importing every converter
module. Both probe failures are currently swallowed (the package-level
``except Exception: pass`` around the ``markitdown.converters`` import and the
per-module ``except Exception: continue``), so
``markitdown_supported_formats()`` can advertise formats whose converter
cannot even be imported and can hide a broken installation.

Locked contract — tests 1 and 2 are expected to FAIL until the fix lands:

1. Unprobed engine advertises nothing: if ``markitdown.converters`` cannot be
   imported, the returned set is empty instead of the 0.1.7 floor.
2. A converter module that fails to import is recorded, not silently
   skipped: ``markitdown_probe_failures()`` lists the failing module after a
   partial failure and is empty after a clean probe.
3. With every converter module importable, extensions discovered from the
   converter modules join the 0.1.7 floor (positive control).
"""

from __future__ import annotations

import importlib
import sys

import pytest

from deeptutor.services.parsing.engines.markitdown.formats import (
    MARKITDOWN_0_1_7_FORMATS,
    markitdown_supported_formats,
)


def _purge_markitdown_modules() -> None:
    for name in [
        name for name in sys.modules if name == "markitdown" or name.startswith("markitdown.")
    ]:
        del sys.modules[name]


@pytest.fixture(autouse=True)
def _fresh_probe_cache():
    markitdown_supported_formats.cache_clear()
    yield
    markitdown_supported_formats.cache_clear()


def _block_markitdown_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import_module = importlib.import_module

    def fake_import_module(name: str, *args: object, **kwargs: object):
        if name == "markitdown" or name.startswith("markitdown."):
            raise ModuleNotFoundError(
                f"No module named {name!r} (blocked by markitdown probe test)",
                name=name,
            )
        return real_import_module(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(importlib, "import_module", fake_import_module)


STUB_CONVERTER_SOURCE = 'DOCX_EXTENSIONS = (".docx",)\n'
DISCOVERY_CONVERTER_SOURCE = 'FAKE_EXTENSIONS = (".rst", "wpd")\nOLD_EXTENSIONS = None\n'
BROKEN_CONVERTER_SOURCE = "raise ImportError('converter module unavailable (test fixture)')\n"


@pytest.fixture
def fake_markitdown_package(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Install a fake ``markitdown`` package with real on-disk converters.

    The probe walks ``markitdown.converters.__path__`` with
    ``pkgutil.iter_modules`` and imports each submodule by name, so the fake
    package uses real files: import machinery resolves the submodule names
    through the pre-seeded parent's ``__path__``. Yields the converters dir;
    pass a per-test writer by mutating the returned path before the first
    probe, or use the prebuilt variants below.
    """
    pkg_root = tmp_path / "fake-md-pkg"
    converters_dir = pkg_root / "markitdown" / "converters"
    converters_dir.mkdir(parents=True)
    (pkg_root / "markitdown" / "__init__.py").write_text("", encoding="utf-8")
    (converters_dir / "__init__.py").write_text("", encoding="utf-8")

    _purge_markitdown_modules()
    monkeypatch.syspath_prepend(str(pkg_root))
    import markitdown  # noqa: PLC0415 - fixture resolves the fake package

    assert markitdown.__file__ is not None
    assert markitdown.__file__.startswith(str(pkg_root))
    yield converters_dir
    _purge_markitdown_modules()


def test_missing_converters_package_advertises_no_formats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contract 1: an unprobed engine must not claim the 0.1.7 floor.

    With ``markitdown.converters`` unimportable, every advertised extension
    is a lie — the engine cannot convert anything, yet the swallowed probe
    still returns the 28 built-in floor formats.
    """
    _block_markitdown_imports(monkeypatch)

    result = markitdown_supported_formats()

    assert result == frozenset(), (
        "markitdown_supported_formats() must advertise no format when the "
        f"converters package cannot be imported; got {sorted(result)}"
    )
    assert ".pdf" not in result
    assert ".docx" not in result


def test_broken_converter_module_is_recorded_not_swallowed(
    fake_markitdown_package,
) -> None:
    """Contract 2: a failing converter module must be observable.

    One converter raises on import while a sibling converter works. The
    silent ``continue`` hides the broken installation; the fix must expose
    the failing module via ``markitdown_probe_failures()`` while keeping the
    formats contributed by working modules and the 0.1.7 floor.
    """
    (fake_markitdown_package / "stub_converter.py").write_text(
        STUB_CONVERTER_SOURCE, encoding="utf-8"
    )
    (fake_markitdown_package / "broken_converter.py").write_text(
        BROKEN_CONVERTER_SOURCE, encoding="utf-8"
    )
    from deeptutor.services.parsing.engines.markitdown.formats import (
        markitdown_probe_failures,
    )

    result = markitdown_supported_formats()

    assert markitdown_probe_failures() == ("markitdown.converters.broken_converter",)
    assert ".docx" in result
    assert MARKITDOWN_0_1_7_FORMATS <= result


def test_probe_failures_reset_after_clean_probe(fake_markitdown_package) -> None:
    """Contract 2 (continued): probe failures reflect the latest probe."""
    from deeptutor.services.parsing.engines.markitdown.formats import (
        markitdown_probe_failures,
    )

    (fake_markitdown_package / "broken_converter.py").write_text(
        BROKEN_CONVERTER_SOURCE, encoding="utf-8"
    )
    markitdown_supported_formats()
    assert markitdown_probe_failures() == ("markitdown.converters.broken_converter",)

    (fake_markitdown_package / "broken_converter.py").unlink()
    markitdown_supported_formats.cache_clear()
    markitdown_supported_formats()

    assert markitdown_probe_failures() == ()


def test_full_install_discovers_converter_extensions(fake_markitdown_package) -> None:
    """Contract 3: a healthy probe joins discovered extensions to the floor."""
    (fake_markitdown_package / "scanner_converter.py").write_text(
        DISCOVERY_CONVERTER_SOURCE, encoding="utf-8"
    )

    result = markitdown_supported_formats()

    assert isinstance(result, frozenset)
    assert ".rst" in result
    assert ".wpd" in result
    assert MARKITDOWN_0_1_7_FORMATS <= result


def test_normalize_extensions_rejects_non_collection_values() -> None:
    """Non-collection EXTENSION constants contribute nothing to discovery."""
    from deeptutor.services.parsing.engines.markitdown.formats import (
        _normalize_extensions,
    )

    assert _normalize_extensions(None) == set()
    assert _normalize_extensions(42) == set()
    assert _normalize_extensions(["PDF", " md ", ".csv"]) == {".pdf", ".md", ".csv"}
