"""Registration-consistency tests for deeptutor.tools.builtin_specs.

Locks the import-cheap catalog contract: unique names derived in order, the
lookup map mirroring the spec tuple, alias and partner-name subsets, class
loading guards (BaseTool check, drift detection) and the lazy sequence
semantics. Also asserts the solve_tool compatibility shim still re-exports
the exact objects owned by the solve capability and that the catalog entries
for the solve tools point at that same module.
"""

from __future__ import annotations

import pytest

from deeptutor.capabilities.solve import tools as solve_capability_tools
from deeptutor.core.tool_protocol import BaseTool
from deeptutor.tools import builtin_specs, solve_tool
from deeptutor.tools.builtin_specs import (
    BUILTIN_TOOL_NAMES,
    BUILTIN_TOOL_SPEC_BY_NAME,
    BUILTIN_TOOL_SPECS,
    PARTNER_BUILTIN_TOOL_NAMES,
    TOOL_ALIASES,
    BuiltinToolSpec,
    LazyBuiltinToolTypes,
)


class TestCatalogConsistency:
    def test_names_are_unique_and_derived_in_order(self) -> None:
        assert len(set(BUILTIN_TOOL_NAMES)) == len(BUILTIN_TOOL_NAMES)
        assert BUILTIN_TOOL_NAMES == tuple(spec.name for spec in BUILTIN_TOOL_SPECS)

    def test_lookup_map_mirrors_the_spec_tuple(self) -> None:
        assert set(BUILTIN_TOOL_SPEC_BY_NAME) == set(BUILTIN_TOOL_NAMES)
        for spec in BUILTIN_TOOL_SPECS:
            assert BUILTIN_TOOL_SPEC_BY_NAME[spec.name] is spec

    def test_alias_targets_exist_in_the_catalog(self) -> None:
        for alias, (target, extra_kwargs) in TOOL_ALIASES.items():
            assert alias not in BUILTIN_TOOL_SPEC_BY_NAME, alias
            assert target in BUILTIN_TOOL_SPEC_BY_NAME, alias
            assert isinstance(extra_kwargs, dict)

    def test_partner_names_track_the_partner_memory_specs(self) -> None:
        partner_spec_names = {
            spec.name
            for spec in BUILTIN_TOOL_SPECS
            if spec.class_path.startswith("deeptutor.tools.partner_memory:")
        }
        assert set(PARTNER_BUILTIN_TOOL_NAMES) == partner_spec_names
        assert set(PARTNER_BUILTIN_TOOL_NAMES) <= set(BUILTIN_TOOL_NAMES)


class TestSpecLoading:
    def test_load_class_resolves_a_base_tool_subclass(self) -> None:
        spec = BUILTIN_TOOL_SPEC_BY_NAME["exec"]
        assert spec.class_path == "deeptutor.tools.exec_tool:ExecTool"
        loaded = spec.load_class()
        assert isinstance(loaded, type)
        assert issubclass(loaded, BaseTool)

    def test_load_class_rejects_non_base_tool_targets(self) -> None:
        spec = BuiltinToolSpec("bogus", "deeptutor.tools.builtin_specs:BuiltinToolSpec")
        with pytest.raises(TypeError, match="BaseTool"):
            spec.load_class()

    def test_create_detects_catalog_name_drift(self) -> None:
        drifted = BuiltinToolSpec("exec", "deeptutor.tools.workspace:WorkspaceListTool")
        with pytest.raises(RuntimeError, match="drift"):
            drifted.create()


class TestLazyBuiltinToolTypes:
    def test_len_indexing_and_iteration_load_classes(self) -> None:
        lazy = LazyBuiltinToolTypes(BUILTIN_TOOL_SPECS[:3])
        assert len(lazy) == 3
        first = lazy[0]
        assert issubclass(first, BaseTool)
        assert lazy[0] is first
        assert lazy[-1] is lazy[2]
        assert list(lazy) == [lazy[0], lazy[1], lazy[2]]

    def test_slice_returns_a_tuple_of_loaded_classes(self) -> None:
        lazy = LazyBuiltinToolTypes(BUILTIN_TOOL_SPECS[:4])
        window = lazy[1:3]
        assert isinstance(window, tuple)
        assert len(window) == 2
        for cls, spec in zip(window, BUILTIN_TOOL_SPECS[1:3]):
            assert cls is spec.load_class()

    def test_empty_spec_tuple_stays_empty(self) -> None:
        lazy = LazyBuiltinToolTypes(())
        assert len(lazy) == 0
        assert list(lazy) == []


class TestSolveToolShim:
    def test_reexports_are_the_capability_owned_objects(self) -> None:
        assert solve_tool.SOLVE_TOOL_NAMES is solve_capability_tools.SOLVE_TOOL_NAMES
        assert solve_tool.SOLVE_TOOL_TYPES is solve_capability_tools.SOLVE_TOOL_TYPES
        for attr in ("SolvePlanTool", "SolveFinishStepTool", "SolveReplanTool"):
            assert getattr(solve_tool, attr) is getattr(solve_capability_tools, attr)
        assert sorted(solve_tool.__all__) == sorted(
            [
                "SOLVE_TOOL_NAMES",
                "SOLVE_TOOL_TYPES",
                "SolveFinishStepTool",
                "SolvePlanTool",
                "SolveReplanTool",
            ]
        )

    def test_solve_names_align_with_catalog_specs(self) -> None:
        assert solve_tool.SOLVE_TOOL_NAMES == ("solve_plan", "solve_finish_step", "solve_replan")
        for name, tool_type in zip(solve_tool.SOLVE_TOOL_NAMES, solve_tool.SOLVE_TOOL_TYPES):
            spec = BUILTIN_TOOL_SPEC_BY_NAME[name]
            assert spec.class_path.startswith("deeptutor.capabilities.solve.tools:")
            assert spec.load_class() is tool_type
            assert spec.create().name == name
