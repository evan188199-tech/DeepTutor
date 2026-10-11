"""Branch tests for the GraphRAG Pandas/Arrow compatibility shim.

Complements ``test_graphrag_pandas_compat.py`` — which exercises the real
pandas/pyarrow repair inside a subprocess — with dependency-free in-process
coverage of the import fallbacks, error classification, and unregister loop
via mock imports.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from types import ModuleType

import pytest

from deeptutor.services.rag.pipelines.graphrag import pandas_compat

_ARROW_MODULE = pandas_compat._PANDAS_ARROW_EXTENSION_MODULE
_ARROW_EXTENSION_NAMES = list(pandas_compat._PANDAS_ARROW_EXTENSION_NAMES)


class _FakeArrowKeyError(Exception):
    """Stands in for ``pyarrow.lib.ArrowKeyError`` without pyarrow installed."""


def _duplicate_registration_message(name: str) -> str:
    return f"A type extension with name {name} already defined"


def _install_fake_pyarrow(
    monkeypatch: pytest.MonkeyPatch,
    *,
    unregistered: frozenset[str] = frozenset(),
) -> list[str]:
    """Register a fake ``pyarrow`` module and return its unregister call log."""
    unregister_calls: list[str] = []

    class _FakePyArrow(ModuleType):
        def unregister_extension_type(self, name: str) -> None:
            unregister_calls.append(name)
            if name in unregistered:
                raise _FakeArrowKeyError(f"extension type {name!r} is not registered")

    fake_pyarrow = _FakePyArrow("pyarrow")
    fake_lib = ModuleType("pyarrow.lib")
    fake_lib.ArrowKeyError = _FakeArrowKeyError
    fake_pyarrow.lib = fake_lib
    monkeypatch.setitem(sys.modules, "pyarrow", fake_pyarrow)
    monkeypatch.setitem(sys.modules, "pyarrow.lib", fake_lib)
    return unregister_calls


def _make_importer(
    outcomes: list[ModuleType | BaseException],
) -> tuple[list[str], Callable[[str], ModuleType]]:
    """Build an ``import_module`` replacement replaying scripted outcomes."""
    calls: list[str] = []

    def import_module(name: str) -> ModuleType:
        assert outcomes, f"unexpected import of {name!r}"
        calls.append(name)
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return calls, import_module


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (_duplicate_registration_message("pandas.period"), True),
        (_duplicate_registration_message("pandas.interval"), True),
        ("A type extension with name pandas.decimal already defined", False),
        ("pandas.period already defined", False),
        ("A type extension with name pandas.period", False),
        ("unrelated pyarrow registry failure", False),
    ],
)
def test_duplicate_registration_error_classification(
    message: str, expected: bool
) -> None:
    assert (
        pandas_compat._is_duplicate_registration_error(Exception(message)) is expected
    )


def test_unregister_stale_extension_types_skips_unregistered_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unregister_calls = _install_fake_pyarrow(
        monkeypatch, unregistered=frozenset({"pandas.period"})
    )

    pandas_compat._unregister_stale_extension_types(
        sys.modules["pyarrow"], _FakeArrowKeyError
    )

    assert unregister_calls == _ARROW_EXTENSION_NAMES


def test_unregister_stale_extension_types_propagates_unexpected_errors() -> None:
    class _BrokenPyArrow:
        def unregister_extension_type(self, name: str) -> None:
            raise ValueError(name)

    with pytest.raises(ValueError):
        pandas_compat._unregister_stale_extension_types(
            _BrokenPyArrow(), _FakeArrowKeyError
        )


def test_prepare_is_noop_without_pyarrow(monkeypatch: pytest.MonkeyPatch) -> None:
    calls, import_module = _make_importer([])
    monkeypatch.setattr(importlib, "import_module", import_module)
    monkeypatch.setitem(sys.modules, "pyarrow", None)

    assert pandas_compat.prepare_pandas_arrow_extensions() is None
    assert calls == []


def test_prepare_is_noop_without_pandas(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_pyarrow(monkeypatch)
    calls, import_module = _make_importer(
        [ModuleNotFoundError("No module named 'pandas'", name="pandas")]
    )
    monkeypatch.setattr(importlib, "import_module", import_module)

    assert pandas_compat.prepare_pandas_arrow_extensions() is None
    assert calls == [_ARROW_MODULE]


def test_prepare_reraises_missing_module_for_unrelated_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_pyarrow(monkeypatch)
    calls, import_module = _make_importer(
        [
            ModuleNotFoundError(
                "No module named 'other.dependency'", name="other.dependency"
            )
        ]
    )
    monkeypatch.setattr(importlib, "import_module", import_module)

    with pytest.raises(ModuleNotFoundError, match="other.dependency"):
        pandas_compat.prepare_pandas_arrow_extensions()
    assert calls == [_ARROW_MODULE]


def test_prepare_imports_extensions_once_when_registry_is_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_pyarrow(monkeypatch)
    calls, import_module = _make_importer([ModuleType(_ARROW_MODULE)])
    monkeypatch.setattr(importlib, "import_module", import_module)

    assert pandas_compat.prepare_pandas_arrow_extensions() is None
    assert calls == [_ARROW_MODULE]


def test_prepare_repairs_stale_registration_and_reimports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unregister_calls = _install_fake_pyarrow(monkeypatch)
    calls, import_module = _make_importer(
        [
            _FakeArrowKeyError(_duplicate_registration_message("pandas.period")),
            ModuleType(_ARROW_MODULE),
        ]
    )
    monkeypatch.setattr(importlib, "import_module", import_module)

    assert pandas_compat.prepare_pandas_arrow_extensions() is None
    assert unregister_calls == _ARROW_EXTENSION_NAMES
    assert calls == [_ARROW_MODULE, _ARROW_MODULE]


def test_prepare_propagates_persistent_duplicate_registration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_pyarrow(monkeypatch)
    duplicate_error = _FakeArrowKeyError(
        _duplicate_registration_message("pandas.interval")
    )
    calls, import_module = _make_importer([duplicate_error, duplicate_error])
    monkeypatch.setattr(importlib, "import_module", import_module)

    with pytest.raises(_FakeArrowKeyError):
        pandas_compat.prepare_pandas_arrow_extensions()
    assert calls == [_ARROW_MODULE, _ARROW_MODULE]
