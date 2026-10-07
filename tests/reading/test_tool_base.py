"""Contract tests for the shared reading tool base (`_tool_base`).

Three axes: registration plumbing (every mounted reading tool subclasses the
base, and the ``tools`` re-exports stay identical), server-side material
validation (``_material_id`` binding precedence and the permission gate), and
degradation (``_guard`` turning engine errors into readable tool failures
instead of turn deaths).

Dedup: extension routing is covered by ``test_extension_router.py`` and prompt
hint composition by ``test_reading_hints.py`` — neither is retested here.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.capabilities.reading import _tool_base
from deeptutor.capabilities.reading._tool_base import (
    BINDING_KWARG,
    MATERIAL_KWARG,
    _NoMaterial,
    _ReadingToolBase,
)
from deeptutor.capabilities.reading.tools import READING_TOOL_NAMES
from deeptutor.core.tool_protocol import ToolDefinition, ToolPromptHints, ToolResult
from deeptutor.reading import ReadingError
from deeptutor.tools.builtin_specs import BUILTIN_TOOL_SPECS

READING_SPECS = tuple(
    spec
    for spec in BUILTIN_TOOL_SPECS
    if spec.class_path.startswith("deeptutor.capabilities.reading.")
)

NO_MATERIAL_FAILURE = "No reading material is open. Ask the user to open a document in the reader."
UNEXPECTED_FAILURE = "The reader could not complete that request."


class _ProbeTool(_ReadingToolBase):
    """Concrete tool exercising only the base's plumbing, with faked deps."""

    name = "probe_tool"

    def __init__(self, outcome: Any = None) -> None:
        self.outcome = outcome
        self.seen_kwargs: dict[str, Any] | None = None

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="probe_tool",
            description="Probe for reading tool base plumbing.",
            parameters=[],
        )

    @_tool_base._guard
    async def execute(self, **kwargs: Any) -> ToolResult:
        self.seen_kwargs = dict(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        if callable(self.outcome):
            return self.outcome(**kwargs)
        return ToolResult(content="probe-ok")


@pytest.fixture
def permission(monkeypatch: pytest.MonkeyPatch):
    """Fake the multi-user gate ``_material_id`` calls after resolving the id."""
    state = {"calls": [], "deny": None}

    def fake_assert(material_id: str, *, upload: bool = False) -> None:
        state["calls"].append(material_id)
        if state["deny"] is not None:
            raise PermissionError(state["deny"])

    monkeypatch.setattr(
        "deeptutor.multi_user.learning_access.assert_learning_material", fake_assert
    )
    return state


def _resolve_material(**kwargs: Any) -> str:
    return _ReadingToolBase._material_id(kwargs)


# -- registration ---------------------------------------------------------


@pytest.mark.parametrize("spec", READING_SPECS, ids=[spec.name for spec in READING_SPECS])
def test_registered_reading_tool_subclasses_base(spec) -> None:
    tool_type = spec.load_class()
    assert issubclass(tool_type, _ReadingToolBase)
    assert tool_type().name == spec.name


def test_mount_policy_matches_registered_reading_tools() -> None:
    assert {spec.name for spec in READING_SPECS} == set(READING_TOOL_NAMES)


@pytest.mark.parametrize(
    ("public", "private"),
    [
        ("_ReadingToolBase", "_ReadingToolBase"),
        ("_guard", "_guard"),
        ("MATERIAL_KWARG", "MATERIAL_KWARG"),
        ("WORKSPACE_KWARG", "WORKSPACE_KWARG"),
        ("BINDING_KWARG", "BINDING_KWARG"),
    ],
)
def test_tools_module_reexports_base_names_unchanged(public: str, private: str) -> None:
    from deeptutor.capabilities.reading import tools as tools_module

    assert getattr(tools_module, public) is getattr(_tool_base, private)


@pytest.mark.parametrize("language", ["en", "zh-CN"], ids=["english", "chinese"])
def test_get_prompt_hints_delegates_by_tool_name(
    monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    seen: list[tuple[str, str]] = []
    sentinel = ToolPromptHints(short_description="fake hint")

    def fake_load(tool_name: str, language: str = "en") -> ToolPromptHints:
        seen.append((tool_name, language))
        return sentinel

    monkeypatch.setattr(_tool_base, "load_prompt_hints", fake_load)

    assert _ProbeTool().get_prompt_hints(language) is sentinel
    assert seen == [("probe_tool", language)]


# -- validation -----------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({BINDING_KWARG: {"material_id": "m-bound"}, MATERIAL_KWARG: "m-kwarg"}, "m-bound"),
        ({BINDING_KWARG: {"material_id": ""}, MATERIAL_KWARG: "m-kwarg"}, "m-kwarg"),
        ({BINDING_KWARG: {"material_id": None}, MATERIAL_KWARG: "m-kwarg"}, "m-kwarg"),
        ({BINDING_KWARG: "not-a-dict", MATERIAL_KWARG: "m-kwarg"}, "m-kwarg"),
        ({MATERIAL_KWARG: "  m-padded  "}, "m-padded"),
        ({BINDING_KWARG: {"material_id": 4}}, "4"),
    ],
    ids=[
        "binding-wins",
        "empty-binding-falls-back",
        "none-binding-falls-back",
        "non-dict-binding-falls-back",
        "stripped",
        "coerced-to-str",
    ],
)
def test_material_id_resolution_precedence(permission, kwargs: dict, expected: str) -> None:
    assert _resolve_material(**kwargs) == expected
    assert permission["calls"] == [expected]


@pytest.mark.parametrize(
    "kwargs",
    [{}, {MATERIAL_KWARG: ""}, {MATERIAL_KWARG: "   "}, {BINDING_KWARG: {}}],
    ids=["absent", "empty", "whitespace", "empty-binding"],
)
def test_material_id_requires_an_open_material(permission, kwargs: dict) -> None:
    with pytest.raises(_NoMaterial):
        _resolve_material(**kwargs)
    assert permission["calls"] == []


def test_material_id_propagates_permission_denial(permission) -> None:
    permission["deny"] = "This reading material is not assigned to this learning account."

    with pytest.raises(PermissionError):
        _resolve_material(**{MATERIAL_KWARG: "m-denied"})
    assert permission["calls"] == ["m-denied"]


def test_store_and_catalog_build_fresh_instances_per_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.reading as reading_pkg

    built: list[str] = []

    class FakeStore:
        def __init__(self) -> None:
            built.append("store")

    class FakeCatalog:
        def __init__(self) -> None:
            built.append("catalog")

    monkeypatch.setattr(reading_pkg, "ReadingStore", FakeStore)
    monkeypatch.setattr(reading_pkg, "ReadingCatalogStore", FakeCatalog)

    assert _ReadingToolBase._store() is not _ReadingToolBase._store()
    assert _ReadingToolBase._catalog() is not _ReadingToolBase._catalog()
    assert built == ["store", "store", "catalog", "catalog"]


# -- degradation ----------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "expected_content", "expected_success"),
    [
        (None, "probe-ok", True),
        (_NoMaterial(), NO_MATERIAL_FAILURE, False),
        (
            PermissionError("This reading material is not assigned."),
            "This reading material is not assigned.",
            False,
        ),
        (ReadingError("locator out of range"), "locator out of range", False),
        (RuntimeError("engine exploded"), UNEXPECTED_FAILURE, False),
        (KeyError("missing"), UNEXPECTED_FAILURE, False),
    ],
    ids=[
        "passthrough",
        "no-material",
        "permission-error",
        "reading-error",
        "unexpected-error",
        "unexpected-key-error",
    ],
)
async def test_guard_maps_failures_to_tool_results(
    outcome: Any, expected_content: str, expected_success: bool
) -> None:
    tool = _ProbeTool(outcome)
    result = await tool.execute(query="q")
    assert result.success is expected_success
    assert result.content == expected_content
    assert tool.seen_kwargs == {"query": "q"}


async def _probe_material(**kwargs: Any) -> ToolResult:
    tool = _ProbeTool(outcome=lambda **kw: ToolResult(content=_resolve_material(**kw)))
    return await tool.execute(**kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "expected_content"),
    [
        ({}, NO_MATERIAL_FAILURE),
        ({MATERIAL_KWARG: "m-denied"}, "not assigned to this learner"),
    ],
    ids=["no-open-material", "denied-material"],
)
async def test_material_validation_degrades_to_failure(
    permission, kwargs: dict, expected_content: str
) -> None:
    permission["deny"] = "not assigned to this learner"

    result = await _probe_material(**kwargs)

    assert result.success is False
    assert result.content == expected_content


@pytest.mark.asyncio
async def test_bound_material_flows_through_guard(permission) -> None:
    result = await _probe_material(
        **{BINDING_KWARG: {"material_id": "m-bound"}, MATERIAL_KWARG: "m-kwarg"}
    )

    assert result.success is True
    assert result.content == "m-bound"
    assert permission["calls"] == ["m-bound"]
