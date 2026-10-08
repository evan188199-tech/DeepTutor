"""Contract tests for the ``deeptutor.tools.mastery_tool`` compat layer.

The mastery loop capability owns the real implementation under
``deeptutor.capabilities.mastery.tools``; ``deeptutor.tools.mastery_tool``
only re-exports it so the historical import path keeps working for the
built-in tool registry, capability manifests, and external users.

These tests pin that contract: the historical path keeps importing, every
exported name is the *same object* the implementation defines (no accidental
re-wraps), the ``__all__`` surfaces stay in lock-step so a refactor on the
implementation side cannot silently drop or rename a public export, and the
registry tuples (names ↔ types) remain aligned.
"""

from __future__ import annotations

import importlib

from deeptutor.core.tool_protocol import BaseTool

COMPAT_PATH = "deeptutor.tools.mastery_tool"
IMPL_PATH = "deeptutor.capabilities.mastery.tools"


def _compat():
    return importlib.import_module(COMPAT_PATH)


def _impl():
    return importlib.import_module(IMPL_PATH)


def _tool_types(module) -> list[type]:
    return [value for value in vars(module).values()
            if isinstance(value, type) and issubclass(value, BaseTool)
            and value is not BaseTool]


def test_historical_import_path_still_resolves_every_export() -> None:
    """The old import path keeps working for registry, manifests, and users."""
    compat = _compat()
    for name in compat.__all__:
        assert hasattr(compat, name), (
            f"{COMPAT_PATH} declares {name!r} in __all__ but does not bind it"
        )


def test_exports_are_the_implementation_objects_not_rewraps() -> None:
    """Every compat export IS the implementation's object, not a copy."""
    compat, impl = _compat(), _impl()
    for name in compat.__all__:
        assert hasattr(impl, name), (
            f"{IMPL_PATH} no longer defines {name!r}; the compat layer "
            "would serve a stale object"
        )
        assert getattr(compat, name) is getattr(impl, name), (
            f"{COMPAT_PATH}.{name} is not the object {IMPL_PATH} defines"
        )


def test_compat_all_matches_the_implementation_all() -> None:
    """A refactor cannot silently add, drop, or rename a public export."""
    compat, impl = _compat(), _impl()
    assert sorted(compat.__all__) == sorted(impl.__all__), (
        f"{COMPAT_PATH}.__all__ drifted from {IMPL_PATH}.__all__"
    )


def test_import_star_surface_equals_all_and_binds_every_name() -> None:
    """``import *`` yields exactly ``__all__`` — a typo in it must raise."""
    namespace: dict[str, object] = {}
    exec(f"from {COMPAT_PATH} import *", namespace)  # noqa: S102 - test scope
    exported = {name for name in namespace if not name.startswith("__")}
    compat = _compat()
    assert exported == set(compat.__all__)
    public_attrs = {name for name in vars(compat) if not name.startswith("_")}
    assert public_attrs == set(compat.__all__), (
        f"{COMPAT_PATH} exposes names outside __all__: "
        f"{sorted(public_attrs - set(compat.__all__))}"
    )


def test_every_tool_export_is_a_base_tool_subclass() -> None:
    """The re-exported Mastery* classes stay real tools, not stubs."""
    compat = _compat()
    tool_exports = [name for name in compat.__all__
                    if isinstance(getattr(compat, name), type)]
    assert tool_exports, "the compat layer lost every tool class"
    for name in tool_exports:
        assert issubclass(getattr(compat, name), BaseTool), name


def test_registry_names_and_types_stay_aligned() -> None:
    """Each registry name is the registered type's own definition name."""
    compat = _compat()
    names = compat.MASTERY_TOOL_NAMES
    types = compat.MASTERY_TOOL_TYPES
    assert len(names) == len(types), (
        "MASTERY_TOOL_NAMES and MASTERY_TOOL_TYPES grew out of step"
    )
    assert len(set(names)) == len(names)
    assert len(set(types)) == len(types)
    for name, tool_type in zip(names, types):
        assert tool_type().name == name, (
            f"registry name {name!r} does not match {tool_type.__name__}"
        )
    # The re-exported classes are exactly the registered ones — nothing is
    # dropped from the registry while still being importable (or vice versa).
    assert set(types) == set(_tool_types(compat))
    assert set(types) == set(_tool_types(_impl()))
