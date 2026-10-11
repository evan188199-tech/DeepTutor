from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from deeptutor.services.config.settings_presets import (
    SETTINGS_PRESETS_SCHEMA_VERSION,
    SettingsPreset,
    get_settings_preset,
    list_settings_presets,
)


def test_the_settings_preset_catalog_is_stable_and_value_free() -> None:
    presets = list_settings_presets()

    assert [preset["id"] for preset in presets] == [
        "basic_text",
        "local_multimodal",
        "university_study",
        "full_generation",
    ]
    forbidden = ("api_key", "base_url", "password", "secret", "localhost")
    for preset in presets:
        rendered = repr(preset).lower()
        assert not any(value in rendered for value in forbidden)
    assert all(preset["parser"] for preset in presets)


def test_a_preset_has_the_draft_payloads_the_apply_flow_already_writes() -> None:
    preset = get_settings_preset("university_study")
    assert preset is not None

    draft = preset.draft_extensions()

    assert draft["document-parsing"] == {"engine": "markitdown", "engines": {}}
    assert draft["tools"] == {
        "enabled_tools": ["brainstorm", "web_search", "paper_search", "reason"]
    }


def test_unknown_presets_are_rejected_without_inventing_a_default() -> None:
    assert get_settings_preset("do-everything") is None
    assert SETTINGS_PRESETS_SCHEMA_VERSION == "deeptutor.settings-presets/v1"


def test_every_catalog_id_resolves_to_its_own_preset() -> None:
    preset_ids = [preset["id"] for preset in list_settings_presets()]

    assert len(preset_ids) == len(set(preset_ids))
    for preset_id in preset_ids:
        preset = get_settings_preset(preset_id)
        assert preset is not None
        assert preset.id == preset_id


def test_lookup_rejects_blank_and_mismatched_case_ids() -> None:
    assert get_settings_preset("") is None
    assert get_settings_preset("BASIC_TEXT") is None
    assert get_settings_preset("basic-text") is None


def test_public_dict_exposes_only_the_reviewable_wire_shape() -> None:
    for preset in list_settings_presets():
        assert list(preset) == [
            "id",
            "label",
            "description",
            "parser",
            "resource_cost",
            "credentials",
            "prerequisites",
            "unlocked_features",
        ]
        for list_field in ("credentials", "prerequisites", "unlocked_features"):
            assert isinstance(preset[list_field], list)
        assert "tools" not in preset


def test_catalog_fields_stay_within_the_declared_vocabulary() -> None:
    for preset in list_settings_presets():
        assert preset["label"].startswith("settings.presets.")
        assert preset["description"].startswith("settings.presets.")
        assert preset["resource_cost"] in {"low", "medium", "high"}
        assert preset["credentials"] and preset["prerequisites"]
        assert preset["unlocked_features"]


def test_draft_extensions_cover_every_preset_with_the_canonical_keys() -> None:
    for public in list_settings_presets():
        preset = get_settings_preset(public["id"])
        assert isinstance(preset, SettingsPreset)

        draft = preset.draft_extensions()

        assert set(draft) == {"document-parsing", "tools"}
        assert draft["document-parsing"]["engine"] == public["parser"]
        assert draft["tools"]["enabled_tools"] == list(preset.tools)
        assert draft["tools"]["enabled_tools"]


def test_repeated_reads_return_fresh_payloads_without_shared_state() -> None:
    first_catalog = list_settings_presets()
    first_catalog[0]["credentials"].append("mutated")
    preset = get_settings_preset("basic_text")
    assert preset is not None
    first_draft = preset.draft_extensions()
    first_draft["tools"]["enabled_tools"].append("mutated")

    second_catalog = list_settings_presets()
    second_draft = preset.draft_extensions()

    assert second_catalog[0]["credentials"] == ["llm"]
    assert second_draft["tools"]["enabled_tools"] == ["brainstorm", "reason"]


def test_preset_records_reject_mutation() -> None:
    preset = get_settings_preset("full_generation")
    assert preset is not None

    with pytest.raises(FrozenInstanceError):
        preset.id = "renamed"
