"""Tests for the question request-config helper (pure logic).

``deeptutor.agents.question.request_config`` builds the
``runtime_config`` payload consumed by ``QuestionPipeline``. The helper
is intentionally tolerant: every knob falls back to its documented
default (8 iterations / summarizer enabled / 800 tokens) whenever the
``capabilities.deep_question.exploring`` section is missing, malformed,
or carries values of the wrong type. These tests pin that contract:
defaults, invalid-value rejection at every nesting level, and the
base-config passthrough behaviour.
"""

from __future__ import annotations

import copy

import pytest

from deeptutor.agents.question.request_config import build_question_runtime_config

DEFAULTS = {
    "max_iterations": 8,
    "tool_summarizer": {
        "enabled": True,
        "max_tokens": 800,
    },
}


def _wrapped(exploring: object) -> dict:
    return {
        "capabilities": {"deep_question": {"exploring": exploring}},
    }


def test_defaults_when_base_config_is_none_or_empty() -> None:
    for base in (None, {}):
        rc = build_question_runtime_config(base_config=base)
        assert rc["exploring"] == DEFAULTS


def test_valid_overrides_are_read_from_capabilities_section() -> None:
    rc = build_question_runtime_config(
        base_config=_wrapped(
            {
                "max_iterations": 3,
                "tool_summarizer": {"enabled": False, "max_tokens": 64},
            }
        )
    )
    assert rc["exploring"] == {
        "max_iterations": 3,
        "tool_summarizer": {"enabled": False, "max_tokens": 64},
    }


def test_partial_override_keeps_defaults_for_missing_knobs() -> None:
    rc = build_question_runtime_config(base_config=_wrapped({"max_iterations": 15}))
    assert rc["exploring"]["max_iterations"] == 15
    assert rc["exploring"]["tool_summarizer"] == DEFAULTS["tool_summarizer"]


@pytest.mark.parametrize("bad", ["12", 0, -4, 2.5, None, [8], {"n": 8}])
def test_non_positive_or_mistyped_max_iterations_falls_back(bad: object) -> None:
    rc = build_question_runtime_config(base_config=_wrapped({"max_iterations": bad}))
    assert rc["exploring"]["max_iterations"] == 8


@pytest.mark.parametrize("bad", ["100", 0, -1, 1.5, None, ["x"], {"t": 1}])
def test_non_positive_or_mistyped_max_tokens_falls_back(bad: object) -> None:
    exploring = {"tool_summarizer": {"max_tokens": bad}}
    rc = build_question_runtime_config(base_config=_wrapped(exploring))
    assert rc["exploring"]["tool_summarizer"]["max_tokens"] == 800


@pytest.mark.parametrize("bad", [1, 0, "true", "false", None, [], {}])
def test_mistyped_summarizer_enabled_falls_back_to_on(bad: object) -> None:
    exploring = {"tool_summarizer": {"enabled": bad}}
    rc = build_question_runtime_config(base_config=_wrapped(exploring))
    assert rc["exploring"]["tool_summarizer"]["enabled"] is True


def test_explicit_bool_off_is_honored_but_non_positive_int_is_rejected() -> None:
    rc = build_question_runtime_config(
        base_config=_wrapped(
            {
                "max_iterations": False,
                "tool_summarizer": {"enabled": False},
            }
        )
    )
    assert rc["exploring"]["max_iterations"] == 8
    assert rc["exploring"]["tool_summarizer"]["enabled"] is False


@pytest.mark.parametrize(
    "base",
    [
        {"capabilities": None},
        {"capabilities": []},
        {"capabilities": {"deep_question": "yes"}},
        {"capabilities": {"deep_question": {"exploring": 5}}},
        {"capabilities": {"deep_question": {"exploring": {"tool_summarizer": None}}}},
    ],
)
def test_malformed_sections_at_any_level_collapse_to_defaults(base: dict) -> None:
    rc = build_question_runtime_config(base_config=base)
    assert rc["exploring"] == DEFAULTS


@pytest.mark.parametrize("base", [None, 42, "main.yaml", [1, 2], {"a": 1}])
def test_non_dict_base_config_yields_defaults_only(base: object) -> None:
    rc = build_question_runtime_config(base_config=base)  # type: ignore[arg-type]
    assert rc["exploring"] == DEFAULTS


def test_runtime_config_preserves_base_keys_and_overrides_existing_exploring() -> None:
    base = {
        "llm": {"provider": "test"},
        "exploring": {"max_iterations": 999, "tool_summarizer": {"enabled": False}},
    }
    rc = build_question_runtime_config(base_config=base)
    assert rc["llm"] == {"provider": "test"}
    assert rc["exploring"] == DEFAULTS
    # The builder must never mutate the caller's base config in place.
    assert "exploring" not in base or base["exploring"]["max_iterations"] == 999


def test_builder_does_not_mutate_the_passed_base_config() -> None:
    base = _wrapped({"max_iterations": 5})
    snapshot = copy.deepcopy(base)
    rc = build_question_runtime_config(base_config=base)
    assert base == snapshot
    assert rc["exploring"]["max_iterations"] == 5


def test_module_exports_only_the_public_helper() -> None:
    import deeptutor.agents.question.request_config as mod

    assert mod.__all__ == ["build_question_runtime_config"]
