"""Focused unit tests for the runtime capability catalog.

Covers the deterministic zero-coverage paths flagged by the coverage scan:
catalog construction, registration (normalization + duplicate rules), default
lookup/creation behavior, kind-filtered listing, and the global default
catalog accessors.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

import deeptutor.runtime.capability_catalog as capability_catalog_module
from deeptutor.runtime.capability_catalog import (
    CapabilityCatalog,
    CapabilityCatalogEntry,
    EmptyConfig,
    get_capability_catalog,
    set_capability_catalog,
)


class _SizedConfig(BaseModel):
    units: int = 1


def _sentinel_factory(tag: str) -> Any:
    def _factory() -> object:
        return {"tag": tag}

    return _factory


# ---------------------------------------------------------------------------
# Empty catalog: fresh instances report nothing and never fabricate entries.
# ---------------------------------------------------------------------------


def test_empty_catalog_reports_no_entries_and_misses_queries() -> None:
    catalog = CapabilityCatalog()

    assert catalog.entries() == ()
    assert catalog.entries("turn") == ()
    assert catalog.entries("loop_extension") == ()
    assert catalog.get("turn", "anything") is None
    assert catalog.create("turn", "anything") is None


def test_clear_on_empty_and_populated_catalog_leaves_no_entries() -> None:
    catalog = CapabilityCatalog()

    catalog.clear()
    assert catalog.entries() == ()

    catalog.register(name="cap", kind="turn", manifest=None, factory=_sentinel_factory("a"))
    catalog.register(name="ext", kind="loop_extension", manifest=None, factory=_sentinel_factory("b"))
    assert len(catalog.entries()) == 2

    catalog.clear()
    assert catalog.entries() == ()
    assert catalog.get("turn", "cap") is None


# ---------------------------------------------------------------------------
# Registration: normalization, defaults, and entry round-trip.
# ---------------------------------------------------------------------------


def test_register_normalizes_name_and_round_trips_entry_fields() -> None:
    catalog = CapabilityCatalog()
    manifest = object()
    factory = _sentinel_factory("round-trip")

    entry = catalog.register(
        name="  padded-name  ",
        kind="turn",
        manifest=manifest,
        factory=factory,
        config_model=_SizedConfig,
    )

    assert isinstance(entry, CapabilityCatalogEntry)
    assert entry.name == "padded-name"
    assert entry.kind == "turn"
    assert entry.manifest is manifest
    assert entry.factory is factory
    assert entry.config_model is _SizedConfig
    assert catalog.entries() == (entry,)


def test_entry_create_invokes_factory() -> None:
    entry = CapabilityCatalogEntry(
        name="cap",
        kind="turn",
        manifest=None,
        factory=_sentinel_factory("invoke"),
        config_model=EmptyConfig,
    )

    assert entry.create() == {"tag": "invoke"}


def test_register_defaults_config_model_to_empty_config() -> None:
    catalog = CapabilityCatalog()

    entry = catalog.register(name="cap", kind="turn", manifest=None, factory=_sentinel_factory("d"))

    assert entry.config_model is EmptyConfig


@pytest.mark.parametrize("blank_name", ["", "   ", "\t\n ", None])
def test_register_rejects_blank_names(blank_name: str | None) -> None:
    catalog = CapabilityCatalog()

    with pytest.raises(ValueError, match="Capability name must not be empty"):
        catalog.register(name=blank_name, kind="turn", manifest=None, factory=_sentinel_factory("x"))

    assert catalog.entries() == ()


# ---------------------------------------------------------------------------
# Duplicate registration: same (kind, name) key.
# ---------------------------------------------------------------------------


def test_register_duplicate_key_rejected_without_replace() -> None:
    catalog = CapabilityCatalog()
    first_factory = _sentinel_factory("first")
    catalog.register(name="cap", kind="turn", manifest=None, factory=first_factory)

    with pytest.raises(ValueError, match="Capability already registered: turn:cap"):
        catalog.register(
            name="cap",
            kind="turn",
            manifest=None,
            factory=_sentinel_factory("second"),
        )

    entries = catalog.entries()
    assert len(entries) == 1
    assert entries[0].factory is first_factory


def test_register_replace_overwrites_existing_entry() -> None:
    catalog = CapabilityCatalog()
    catalog.register(name="cap", kind="turn", manifest=None, factory=_sentinel_factory("first"))

    replaced = catalog.register(
        name="cap",
        kind="turn",
        manifest=None,
        factory=_sentinel_factory("second"),
        replace=True,
    )

    entries = catalog.entries()
    assert entries == (replaced,)
    assert catalog.create("turn", "cap") == {"tag": "second"}


def test_same_name_registered_under_different_kinds_stays_distinct() -> None:
    catalog = CapabilityCatalog()
    turn_entry = catalog.register(
        name="cap", kind="turn", manifest=None, factory=_sentinel_factory("turn")
    )
    ext_entry = catalog.register(
        name="cap", kind="loop_extension", manifest=None, factory=_sentinel_factory("ext")
    )

    assert catalog.get("turn", "cap") is turn_entry
    assert catalog.get("loop_extension", "cap") is ext_entry
    assert len(catalog.entries()) == 2


# ---------------------------------------------------------------------------
# Query and creation defaults: misses return None, hits normalize names.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "name"),
    [
        ("turn", "missing"),  # unknown name for a known kind
        ("loop_extension", "cap"),  # known name for the wrong kind
        ("turn", ""),  # blank name never matches
        ("turn", None),  # missing name never matches
    ],
)
def test_get_and_create_return_none_on_miss(kind: str, name: str | None) -> None:
    catalog = CapabilityCatalog()
    catalog.register(name="cap", kind="turn", manifest=None, factory=_sentinel_factory("hit"))

    assert catalog.get(kind, name) is None
    assert catalog.create(kind, name) is None


def test_get_and_create_lookup_normalizes_whitespace() -> None:
    catalog = CapabilityCatalog()
    entry = catalog.register(name="cap", kind="turn", manifest=None, factory=_sentinel_factory("hit"))

    assert catalog.get("turn", "  cap  ") is entry
    assert catalog.create("turn", "\tcap ") == {"tag": "hit"}


# ---------------------------------------------------------------------------
# Kind-filtered listing.
# ---------------------------------------------------------------------------


def test_entries_filters_by_kind_without_mutating_catalog() -> None:
    catalog = CapabilityCatalog()
    turn_entry = catalog.register(
        name="cap", kind="turn", manifest=None, factory=_sentinel_factory("turn")
    )
    ext_entry = catalog.register(
        name="ext", kind="loop_extension", manifest=None, factory=_sentinel_factory("ext")
    )

    assert catalog.entries("turn") == (turn_entry,)
    assert catalog.entries("loop_extension") == (ext_entry,)
    assert catalog.entries() == (turn_entry, ext_entry)
    assert len(catalog.entries()) == 2


# ---------------------------------------------------------------------------
# EmptyConfig default schema: explicit no-options contract.
# ---------------------------------------------------------------------------


def test_empty_config_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        EmptyConfig.model_validate({"units": 3})

    assert EmptyConfig.model_validate({}) == EmptyConfig()


# ---------------------------------------------------------------------------
# Global default catalog: singleton, swap, and reset behavior.
# ---------------------------------------------------------------------------


def test_default_catalog_singleton_swap_and_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capability_catalog_module, "_default_catalog", None)

    first = get_capability_catalog()
    assert get_capability_catalog() is first

    custom = CapabilityCatalog()
    set_capability_catalog(custom)
    assert get_capability_catalog() is custom

    set_capability_catalog(None)
    fresh = get_capability_catalog()
    assert isinstance(fresh, CapabilityCatalog)
    assert fresh is not custom
    assert fresh.entries() == ()
