"""Tests for canonical workspace ownership upgrade on chat sessions."""

from __future__ import annotations

from deeptutor.services.session.workspace_preferences import (
    WORKSPACE_MODE_MASTERY,
    WORKSPACE_MODE_READING,
    WORKSPACE_MODES,
    upgrade_workspace_preferences,
)


class TestNonDictInputs:
    def test_none_becomes_empty_preferences(self) -> None:
        assert upgrade_workspace_preferences(None) == {}

    def test_list_becomes_empty_preferences(self) -> None:
        assert upgrade_workspace_preferences(["capability"]) == {}

    def test_string_becomes_empty_preferences(self) -> None:
        assert upgrade_workspace_preferences("mastery_path") == {}


class TestExplicitModeShortCircuit:
    def test_existing_mode_is_kept_verbatim(self) -> None:
        value = {"workspace_mode": "custom_surface", "capability": "chat"}
        assert upgrade_workspace_preferences(value) == value

    def test_empty_explicit_mode_is_not_reconstructed(self) -> None:
        value = {
            "workspace_mode": "",
            "capability": WORKSPACE_MODE_MASTERY,
            "mastery_path_id": "mp-1",
        }
        assert upgrade_workspace_preferences(value)["workspace_mode"] == ""

    def test_input_dict_is_copied_not_mutated(self) -> None:
        value: dict = {"workspace_mode": WORKSPACE_MODE_READING}
        result = upgrade_workspace_preferences(value)
        assert result == value
        assert result is not value
        value["workspace_mode"] = "changed"
        assert result["workspace_mode"] == WORKSPACE_MODE_READING


class TestMasteryUpgrade:
    def test_mastery_capability_with_path_id_upgrades(self) -> None:
        result = upgrade_workspace_preferences(
            {"capability": WORKSPACE_MODE_MASTERY, "mastery_path_id": "mp-7"}
        )
        assert result["workspace_mode"] == WORKSPACE_MODE_MASTERY

    def test_mastery_capability_without_path_id_does_not_upgrade(self) -> None:
        result = upgrade_workspace_preferences({"capability": WORKSPACE_MODE_MASTERY})
        assert "workspace_mode" not in result

    def test_path_id_with_other_capability_does_not_upgrade(self) -> None:
        result = upgrade_workspace_preferences(
            {"capability": "chat", "mastery_path_id": "mp-7"}
        )
        assert "workspace_mode" not in result

    def test_whitespace_path_id_is_rejected(self) -> None:
        result = upgrade_workspace_preferences(
            {"capability": WORKSPACE_MODE_MASTERY, "mastery_path_id": "   "}
        )
        assert "workspace_mode" not in result

    def test_non_string_capability_values_are_coerced(self) -> None:
        result = upgrade_workspace_preferences(
            {"capability": None, "mastery_path_id": "mp-7"}
        )
        assert "workspace_mode" not in result


class TestReadingUpgrade:
    def test_reading_capability_with_workspace_id_upgrades(self) -> None:
        result = upgrade_workspace_preferences(
            {
                "capability": WORKSPACE_MODE_READING,
                "reading_workspace_id": "rw-1",
            }
        )
        assert result["workspace_mode"] == WORKSPACE_MODE_READING

    def test_reading_session_kind_with_workspace_id_upgrades(self) -> None:
        result = upgrade_workspace_preferences(
            {
                "session_kind": WORKSPACE_MODE_READING,
                "reading_workspace_id": "rw-2",
            }
        )
        assert result["workspace_mode"] == WORKSPACE_MODE_READING

    def test_workspace_id_alone_does_not_upgrade(self) -> None:
        result = upgrade_workspace_preferences({"reading_workspace_id": "rw-3"})
        assert "workspace_mode" not in result

    def test_whitespace_kind_with_workspace_id_does_not_upgrade(self) -> None:
        result = upgrade_workspace_preferences(
            {"session_kind": "  ", "reading_workspace_id": "rw-3"}
        )
        assert "workspace_mode" not in result


class TestModeConstants:
    def test_mode_constants_are_canonical_values(self) -> None:
        assert WORKSPACE_MODE_READING == "immersive_reading"
        assert WORKSPACE_MODE_MASTERY == "mastery_path"

    def test_modes_frozenset_holds_exactly_both_modes(self) -> None:
        assert isinstance(WORKSPACE_MODES, frozenset)
        assert WORKSPACE_MODES == {WORKSPACE_MODE_READING, WORKSPACE_MODE_MASTERY}
