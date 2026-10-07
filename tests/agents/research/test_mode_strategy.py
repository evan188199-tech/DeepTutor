"""Table-driven tests for the research mode strategy registry.

``deeptutor.agents.research.mode_strategy`` is the single source of truth
that ``request_config._build_mode_policy`` delegates to. These tests pin
the registry contract: per-mode configuration, depth-table boundaries,
default-value fallbacks for unknown inputs (no exceptions), and the
lightweight ``validate_output`` drift checks. Everything runs offline.
"""

from __future__ import annotations

import pytest

from deeptutor.agents.research import mode_strategy
from deeptutor.agents.research.mode_strategy import (
    STRATEGIES,
    ModeStrategy,
    get_strategy,
)

ALL_MODES = ["notes", "report", "comparison", "learning_path"]
ALL_DEPTHS = ["quick", "standard", "deep", "manual"]

# (mode, style, decompose_mode, single_pass_threshold, min_section_length)
REGISTRY_CASES = [
    ("notes", "study_notes", "manual", 99, 260),
    ("report", "report", "auto", 2, 650),
    ("comparison", "comparison", "manual", 2, 520),
    ("learning_path", "learning_path", "auto", 99, 420),
]

# (mode, depth, expected iterations) — comparison is the only mode that
# escalates deep runs to 2 iterations.
REPHRASE_CASES = [
    ("notes", "quick", 1),
    ("notes", "standard", 1),
    ("notes", "deep", 1),
    ("notes", "manual", 1),
    ("report", "deep", 1),
    ("comparison", "standard", 1),
    ("comparison", "deep", 2),
    ("learning_path", "manual", 1),
]

# (decompose_mode, depth, expected subtopic count)
SUBTOPIC_CASES = [
    ("auto", "quick", 2),
    ("auto", "standard", 4),
    ("auto", "deep", 6),
    ("manual", "quick", 2),
    ("manual", "standard", 3),
    ("manual", "deep", 4),
]

# (mode, depth, expected initial_subtopics, expected auto_max_subtopics)
POLICY_CASES = [
    ("report", "quick", None, 2),
    ("report", "standard", None, 4),
    ("report", "deep", None, 6),
    ("learning_path", "quick", None, 2),
    ("notes", "quick", 2, None),
    ("notes", "standard", 3, None),
    ("notes", "deep", 4, None),
    ("comparison", "deep", 4, None),
]


@pytest.mark.parametrize(
    ("mode", "style", "decompose_mode", "single_pass_threshold", "min_section_length"),
    REGISTRY_CASES,
)
def test_registry_pins_per_mode_configuration(
    mode: str,
    style: str,
    decompose_mode: str,
    single_pass_threshold: int,
    min_section_length: int,
) -> None:
    strategy = get_strategy(mode)

    assert strategy.name == mode
    assert strategy.style == style
    assert strategy.decompose_mode == decompose_mode
    assert strategy.single_pass_threshold == single_pass_threshold
    assert strategy.min_section_length == min_section_length
    assert strategy.rephrase_enabled is True


def test_registry_covers_exactly_the_documented_modes() -> None:
    assert sorted(STRATEGIES) == sorted(ALL_MODES)


@pytest.mark.parametrize(("mode", "depth", "expected"), REPHRASE_CASES)
def test_rephrase_iterations_follows_depth_table(mode: str, depth: str, expected: int) -> None:
    assert get_strategy(mode).rephrase_iterations(depth) == expected


@pytest.mark.parametrize(("decompose_mode", "depth", "expected"), SUBTOPIC_CASES)
def test_subtopic_count_follows_decompose_mode_table(
    decompose_mode: str, depth: str, expected: int
) -> None:
    strategy = ModeStrategy(
        name="notes",
        style="study_notes",
        rephrase_enabled=True,
        decompose_mode=decompose_mode,
        single_pass_threshold=2,
        min_section_length=1,
    )

    assert strategy.subtopic_count(depth) == expected


@pytest.mark.parametrize(("mode", "depth", "initial", "auto_max"), POLICY_CASES)
def test_build_policy_routes_decompose_mode_to_exactly_one_knob(
    mode: str, depth: str, initial: int | None, auto_max: int | None
) -> None:
    policy = get_strategy(mode).build_policy(depth)

    assert policy["decompose_mode"] == get_strategy(mode).decompose_mode
    assert policy["initial_subtopics"] == initial
    assert policy["auto_max_subtopics"] == auto_max
    assert policy["style"] == get_strategy(mode).style
    assert set(policy) == {
        "rephrase_enabled",
        "rephrase_iterations",
        "decompose_mode",
        "initial_subtopics",
        "auto_max_subtopics",
        "min_section_length",
        "report_single_pass_threshold",
        "enable_citation_list",
        "enable_inline_citations",
        "deduplicate_enabled",
        "style",
    }


def test_comparison_policy_keeps_initial_subtopics_at_floor() -> None:
    # The manual table never dips below 2; the explicit max() floor is a
    # guard for future table edits. Pin it with a deliberately low table.
    original = mode_strategy._MANUAL_SUBTOPICS
    mode_strategy._MANUAL_SUBTOPICS = {"quick": 1, "standard": 1, "deep": 1}
    try:
        comparison = get_strategy("comparison")
        notes = get_strategy("notes")
        assert comparison.build_policy("quick")["initial_subtopics"] == 2
        assert notes.build_policy("quick")["initial_subtopics"] == 1
    finally:
        mode_strategy._MANUAL_SUBTOPICS = original


@pytest.mark.parametrize("mode", ALL_MODES)
@pytest.mark.parametrize("depth", ["", "unknown", "QUICK", "ultra-deep"])
def test_unknown_depth_falls_back_to_defaults_without_raising(mode: str, depth: str) -> None:
    strategy = get_strategy(mode)

    assert strategy.rephrase_iterations(depth) == 1
    assert strategy.subtopic_count(depth) == 3
    policy = strategy.build_policy(depth)
    if strategy.decompose_mode == "auto":
        assert policy["initial_subtopics"] is None
        assert policy["auto_max_subtopics"] == 4
    else:
        assert policy["initial_subtopics"] == 3
        assert policy["auto_max_subtopics"] is None


@pytest.mark.parametrize("depth", ALL_DEPTHS)
def test_default_strategy_flags_are_inherited_from_dataclass_defaults(depth: str) -> None:
    strategy = ModeStrategy(
        name="notes",
        style="study_notes",
        rephrase_enabled=True,
        decompose_mode="manual",
        single_pass_threshold=2,
        min_section_length=1,
    )

    assert strategy.enable_citation_list is True
    assert strategy.enable_inline_citations is True
    assert strategy.deduplicate_enabled is False
    assert strategy.rephrase_iterations(depth) == 1


def test_get_strategy_rejects_unknown_mode_with_key_error() -> None:
    with pytest.raises(KeyError):
        get_strategy("essay")


@pytest.mark.parametrize("report", ["", "   \n\t  ", None])
@pytest.mark.parametrize("mode", ALL_MODES)
def test_validate_output_flags_blank_reports_for_every_mode(mode: str, report: str | None) -> None:
    assert get_strategy(mode).validate_output(report) == ["Report is empty."]


VALID_REPORT_CASES = [
    ("notes", "## Topic\n> **Definition — photosynthesis**: process\n\n**Key Takeaway**: review"),
    ("notes", ">  **Definition — X**: y\n\nkey takeaway: z"),
    ("comparison", "| a | b |\n| --- | --- |\n| 1 | 2 |"),
    ("learning_path", "Step 1: read\n\nCheckpoint 1: quiz yourself"),
    ("learning_path", "plan with CHECKPOINT marker"),
    ("report", "A plain report section long enough to be non-empty."),
]


@pytest.mark.parametrize(("mode", "report"), VALID_REPORT_CASES)
def test_validate_output_accepts_reports_matching_mode_contract(mode: str, report: str) -> None:
    assert get_strategy(mode).validate_output(report) == []


INVALID_REPORT_CASES = [
    ("notes", "free-form text with no definition box or takeaway"),
    ("notes", "> **Definition — X**: y"),  # has definition, misses takeaway
    ("notes", "Key Takeaway: only takeaway, no definition box"),
    ("comparison", "bullet list\n- no pipes here"),
    ("learning_path", "a plan with no completion markers"),
]


@pytest.mark.parametrize(("mode", "report"), INVALID_REPORT_CASES)
def test_validate_output_warns_on_mode_drift(mode: str, report: str) -> None:
    warnings = get_strategy(mode).validate_output(report)

    assert warnings, "expected at least one drift warning"
    assert all(isinstance(w, str) and w for w in warnings)
