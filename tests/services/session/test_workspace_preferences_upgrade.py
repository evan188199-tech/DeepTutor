from __future__ import annotations

import pytest

from deeptutor.services.session.workspace_preferences import (
    WORKSPACE_MODE_MASTERY,
    WORKSPACE_MODE_READING,
    upgrade_workspace_preferences,
)


@pytest.mark.parametrize("value", [None, [], "legacy", 7, ("a", "b"), {1, 2}])
def test_non_dict_input_degrades_to_empty_dict(value) -> None:
    result = upgrade_workspace_preferences(value)

    assert result == {}
    result["workspace_mode"] = WORKSPACE_MODE_READING
    assert result["workspace_mode"] == WORKSPACE_MODE_READING


def test_existing_workspace_mode_short_circuits_upgrade() -> None:
    legacy = {
        "workspace_mode": WORKSPACE_MODE_READING,
        "capability": "mastery_path",
        "mastery_path_id": "mp-1",
        "reading_workspace_id": "rw-1",
    }

    assert upgrade_workspace_preferences(legacy) == {
        "workspace_mode": WORKSPACE_MODE_READING,
        "capability": "mastery_path",
        "mastery_path_id": "mp-1",
        "reading_workspace_id": "rw-1",
    }


def test_explicit_empty_workspace_mode_is_never_reconstructed() -> None:
    left_workspace = {
        "workspace_mode": "",
        "capability": "mastery_path",
        "mastery_path_id": "mp-stale",
        "reading_workspace_id": "rw-stale",
        "session_kind": "immersive_reading",
    }

    assert upgrade_workspace_preferences(left_workspace)["workspace_mode"] == ""


def test_workspace_mode_none_is_preserved_without_upgrade() -> None:
    record = {"workspace_mode": None, "capability": "mastery_path", "mastery_path_id": "mp-1"}

    assert upgrade_workspace_preferences(record) == record


def test_unknown_workspace_mode_value_is_left_untouched() -> None:
    record = {"workspace_mode": "future_mode", "reading_workspace_id": "rw-1"}

    assert upgrade_workspace_preferences(record) == record


def test_mastery_capability_with_path_id_upgrades_to_mastery() -> None:
    legacy = {"capability": "mastery_path", "mastery_path_id": "mp-42"}

    assert upgrade_workspace_preferences(legacy) == {
        "capability": "mastery_path",
        "mastery_path_id": "mp-42",
        "workspace_mode": WORKSPACE_MODE_MASTERY,
    }


def test_mastery_capability_without_path_id_does_not_upgrade() -> None:
    legacy = {"capability": "mastery_path", "mastery_path_id": ""}

    assert "workspace_mode" not in upgrade_workspace_preferences(legacy)


def test_mastery_path_id_alone_does_not_upgrade() -> None:
    legacy = {"mastery_path_id": "mp-42"}

    assert "workspace_mode" not in upgrade_workspace_preferences(legacy)


def test_reading_capability_with_workspace_id_upgrades_to_reading() -> None:
    legacy = {"capability": "immersive_reading", "reading_workspace_id": "rw-9"}

    assert upgrade_workspace_preferences(legacy) == {
        "capability": "immersive_reading",
        "reading_workspace_id": "rw-9",
        "workspace_mode": WORKSPACE_MODE_READING,
    }


def test_reading_session_kind_with_workspace_id_upgrades_to_reading() -> None:
    legacy = {
        "session_kind": "immersive_reading",
        "reading_workspace_id": "rw-9",
        "capability": "chat",
    }

    assert upgrade_workspace_preferences(legacy)["workspace_mode"] == WORKSPACE_MODE_READING


def test_reading_workspace_id_alone_does_not_upgrade() -> None:
    legacy = {"reading_workspace_id": "rw-9", "capability": "chat", "session_kind": "standard"}

    assert "workspace_mode" not in upgrade_workspace_preferences(legacy)


def test_mastery_takes_precedence_over_reading_signals() -> None:
    legacy = {
        "capability": "mastery_path",
        "mastery_path_id": "mp-1",
        "reading_workspace_id": "rw-2",
        "session_kind": "immersive_reading",
    }

    assert upgrade_workspace_preferences(legacy)["workspace_mode"] == WORKSPACE_MODE_MASTERY


def test_whitespace_only_fields_do_not_upgrade() -> None:
    legacy = {"capability": "   ", "mastery_path_id": "   ", "reading_workspace_id": "  "}

    assert "workspace_mode" not in upgrade_workspace_preferences(legacy)


def test_whitespace_around_values_is_trimmed_before_matching() -> None:
    mastery = upgrade_workspace_preferences(
        {"capability": "  mastery_path ", "mastery_path_id": " mp-7 "}
    )
    reading = upgrade_workspace_preferences(
        {"capability": " immersive_reading", "reading_workspace_id": "rw-3\t"}
    )

    assert mastery["workspace_mode"] == WORKSPACE_MODE_MASTERY
    assert reading["workspace_mode"] == WORKSPACE_MODE_READING


def test_input_record_is_never_mutated() -> None:
    legacy = {"capability": "mastery_path", "mastery_path_id": "mp-1"}

    result = upgrade_workspace_preferences(legacy)

    assert result is not legacy
    assert legacy == {"capability": "mastery_path", "mastery_path_id": "mp-1"}
    assert result["workspace_mode"] == WORKSPACE_MODE_MASTERY


def test_upgrade_is_idempotent() -> None:
    legacy = {"capability": "mastery_path", "mastery_path_id": "mp-1"}

    once = upgrade_workspace_preferences(legacy)
    twice = upgrade_workspace_preferences(once)

    assert twice == once


def test_non_string_storage_values_follow_falsy_coercion() -> None:
    numeric_id = upgrade_workspace_preferences(
        {"capability": "mastery_path", "mastery_path_id": 42}
    )
    none_capability = upgrade_workspace_preferences(
        {"capability": None, "mastery_path_id": "mp-1", "reading_workspace_id": "rw-1"}
    )

    assert numeric_id["workspace_mode"] == WORKSPACE_MODE_MASTERY
    assert "workspace_mode" not in none_capability


def test_unrelated_keys_are_preserved() -> None:
    legacy = {
        "capability": "immersive_reading",
        "reading_workspace_id": "rw-9",
        "kb_name": "physics",
        "enable_rag": True,
    }

    assert upgrade_workspace_preferences(legacy) == {
        "capability": "immersive_reading",
        "reading_workspace_id": "rw-9",
        "kb_name": "physics",
        "enable_rag": True,
        "workspace_mode": WORKSPACE_MODE_READING,
    }


def test_empty_record_degrades_without_workspace_mode() -> None:
    assert upgrade_workspace_preferences({}) == {}
