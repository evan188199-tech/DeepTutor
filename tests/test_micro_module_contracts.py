"""Contract tests for three single-purpose modules that ship no other tests.

Covered surfaces:
- ``deeptutor.__version__`` — the release version string and its export list
- ``deeptutor.book.errors`` — the Book runtime exception contract
- ``deeptutor.services.llm.provider_registry`` — the compatibility re-export
  of the shared provider registry
"""

from __future__ import annotations

import importlib
import re

import pytest

from deeptutor.__version__ import __version__ as VERSION
import deeptutor.book.errors as book_errors
import deeptutor.services.llm.provider_registry as llm_provider_registry

# ---------------------------------------------------------------------------
# deeptutor.__version__
# ---------------------------------------------------------------------------


def test_version_is_canonical_semver_triple_without_prefix() -> None:
    assert re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", VERSION) is not None


def test_version_round_trips_through_integer_tuple() -> None:
    parts = tuple(int(piece) for piece in VERSION.split("."))

    assert len(parts) == 3
    assert ".".join(str(part) for part in parts) == VERSION


def test_version_module_exports_only_the_version() -> None:
    module = importlib.import_module("deeptutor.__version__")

    assert module.__all__ == ("__version__",)
    assert isinstance(module.__all__, tuple)
    assert module.__version__ == VERSION


# ---------------------------------------------------------------------------
# deeptutor.book.errors
# ---------------------------------------------------------------------------


def test_book_paused_error_inherits_runtime_error() -> None:
    assert issubclass(book_errors.BookPausedError, RuntimeError)


def test_book_paused_error_constructs_with_message_and_is_catchable_as_runtime_error() -> None:
    error = book_errors.BookPausedError("book paused mid-compile")
    assert str(error) == "book paused mid-compile"

    with pytest.raises(RuntimeError, match="book paused mid-compile"):
        raise book_errors.BookPausedError("book paused mid-compile")


def test_book_errors_module_exports_only_book_paused_error() -> None:
    assert book_errors.__all__ == ["BookPausedError"]


def test_package_lazy_export_resolves_to_the_errors_module_class() -> None:
    package = importlib.import_module("deeptutor.book")

    assert package.BookPausedError is book_errors.BookPausedError


# ---------------------------------------------------------------------------
# deeptutor.services.llm.provider_registry (compatibility re-export)
# ---------------------------------------------------------------------------


def test_compat_module_reexports_the_full_shared_registry_surface() -> None:
    source = importlib.import_module("deeptutor.services.provider_registry")

    for name in source.__all__:
        assert getattr(llm_provider_registry, name, None) is getattr(source, name), name


def test_compat_module_lookup_resolves_canonical_providers_and_aliases() -> None:
    openai = llm_provider_registry.find_by_name("openai")
    azure = llm_provider_registry.find_by_name("azure")

    assert openai is not None and openai.name == "openai"
    assert azure is not None and azure.name == "azure_openai"


def test_compat_module_lookup_falls_back_to_none_for_unknown_or_missing_names() -> None:
    assert llm_provider_registry.find_by_name("no-such-provider") is None
    assert llm_provider_registry.find_by_name(None) is None
    assert llm_provider_registry.find_by_name("   ") is None


def test_compat_module_gateway_lookup_passes_gateway_through_and_falls_back_on_key_prefix() -> None:
    openrouter = llm_provider_registry.find_gateway(provider_name="openrouter")
    by_key = llm_provider_registry.find_gateway(api_key="sk-or-v1-test")
    direct_without_env = llm_provider_registry.find_gateway(provider_name="custom")

    assert openrouter is not None and openrouter.name == "openrouter"
    assert by_key is openrouter
    assert direct_without_env is None
