"""``list_llm_options`` candidate filtering and ``apply_llm_selection_to_catalog`` edges."""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.model_selection import (
    LLMSelection,
    apply_llm_selection_to_catalog,
    list_llm_options,
)


def _catalog(models: list[Any], profiles: list[Any] | None = None, **llm: Any) -> dict[str, Any]:
    if profiles is None:
        profiles = [
            {
                "id": "p1",
                "name": "OpenRouter",
                "binding": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "secret",
                "models": models,
            }
        ]
    return {
        "version": 1,
        "services": {"llm": {"active_profile_id": None, "active_model_id": None, **llm,
                             "profiles": profiles}},
    }


def test_options_skip_malformed_profiles_and_models():
    valid_profile = {
        "id": "p1",
        "name": "OpenRouter",
        "binding": "openrouter",
        "models": [
            "not-a-dict",
            {"name": "NoId", "model": "m/a"},
            {"id": "", "name": "BlankId", "model": "m/b"},
            {"id": "m1", "name": "NoModelValue"},
            {"id": "m1", "name": "Gemini Flash", "model": "google/gemini-3-flash-preview"},
        ],
    }
    catalog = _catalog(
        models=[],
        profiles=[
            "not-a-dict",
            {"name": "NoId", "binding": "openai", "models": []},
            {"id": "", "binding": "openai", "models": []},
            valid_profile,
        ],
    )

    payload = list_llm_options(catalog)

    assert [o["model_id"] for o in payload["options"]] == ["m1"]
    assert payload["options"][0]["model"] == "google/gemini-3-flash-preview"


def test_context_window_falls_back_to_the_token_field_then_drops_garbage():
    catalog = _catalog(
        models=[
            {"id": "a", "model": "m/a", "context_window": "abc", "context_window_tokens": "8192"},
            {"id": "b", "model": "m/b", "context_window": "0"},
            {"id": "c", "model": "m/c", "context_window": "200000"},
        ]
    )

    by_id = {o["model_id"]: o for o in list_llm_options(catalog)["options"]}

    assert by_id["a"]["context_window"] == 8192
    assert "context_window" not in by_id["b"]
    assert by_id["c"]["context_window"] == 200000


def test_active_default_requires_both_ids_to_match():
    catalog = _catalog(models=[{"id": "m1", "model": "m/1"}, {"id": "m2", "model": "m/2"}])

    payload = list_llm_options(catalog)
    assert all(o["is_active_default"] is False for o in payload["options"])
    assert payload["active"] is None

    matched = list_llm_options(
        _catalog(
            models=[{"id": "m1", "model": "m/1"}],
            active_profile_id="p1",
            active_model_id="m1",
        )
    )
    assert matched["active"] == {"profile_id": "p1", "model_id": "m1"}
    assert matched["options"][0]["is_active_default"] is True


def test_apply_with_no_selection_returns_an_unchanged_copy():
    catalog = _catalog(
        models=[{"id": "m1", "model": "m/1"}],
        active_profile_id="p1",
        active_model_id="m1",
    )

    for empty in (None, {}, {"profile_id": "", "model_id": ""}):
        result = apply_llm_selection_to_catalog(catalog, empty)
        assert result is not catalog
        assert result["services"]["llm"]["active_profile_id"] == "p1"
        assert result["services"]["llm"]["active_model_id"] == "m1"
    assert catalog["services"]["llm"]["active_profile_id"] == "p1"


def test_apply_accepts_a_raw_payload_dict():
    catalog = _catalog(models=[{"id": "m1", "model": "m/1"}])

    selected = apply_llm_selection_to_catalog(
        catalog, {"profile_id": "p1", "model_id": "m1", "reasoning_effort": "HIGH"}
    )

    assert selected["services"]["llm"]["active_profile_id"] == "p1"
    assert selected["services"]["llm"]["active_model_id"] == "m1"


def test_apply_rejects_an_unknown_profile():
    with pytest.raises(ValueError, match="was not found"):
        apply_llm_selection_to_catalog(
            _catalog(models=[{"id": "m1", "model": "m/1"}]),
            LLMSelection(profile_id="ghost", model_id="m1"),
        )


def test_from_payload_rejects_non_object_payloads():
    for bad in (["p1", "m1"], "p1", 42):
        with pytest.raises(ValueError, match="expected an object"):
            LLMSelection.from_payload(bad)


def test_from_payload_rejects_half_an_id_pair():
    with pytest.raises(ValueError, match="profile_id and model_id are required"):
        LLMSelection.from_payload({"profile_id": "p1"})
    with pytest.raises(ValueError, match="profile_id and model_id are required"):
        LLMSelection.from_payload({"model_id": "m1"})


def test_from_payload_reads_an_empty_selection_as_none():
    assert LLMSelection.from_payload(None) is None
    assert LLMSelection.from_payload({}) is None
    assert LLMSelection.from_payload({"profile_id": "  ", "model_id": ""}) is None


def test_from_payload_strips_surrounding_whitespace():
    selection = LLMSelection.from_payload(
        {"profile_id": " p1 ", "model_id": " m1 ", "reasoning_effort": "  LOW  "}
    )

    assert selection == LLMSelection(profile_id="p1", model_id="m1", reasoning_effort="low")


def test_from_payload_passes_an_existing_selection_through():
    selection = LLMSelection(profile_id="p1", model_id="m1")

    assert LLMSelection.from_payload(selection) is selection
