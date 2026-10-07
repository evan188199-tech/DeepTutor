"""``model_selection.llm`` — config defaults and invalid-value handling.

Degenerate catalogs, half-written models and wrong-typed values must degrade to
sane defaults (skipped options, redacted output) instead of raising. Pure
functions only: no catalog service, no registry I/O, no network.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.model_selection import (
    LLMSelection,
    apply_llm_selection_to_catalog,
    list_llm_options,
)


def _llm_service(profiles: Any, **extra: Any) -> dict[str, Any]:
    return {"services": {"llm": {"profiles": profiles, **extra}}}


class TestDegenerateCatalogDefaults:
    @pytest.mark.parametrize(
        "catalog",
        [
            {},
            {"services": None},
            {"services": "not-a-dict"},
            {"services": {"llm": {"profiles": None}}},
            {"services": {"llm": {"profiles": "not-a-list"}}},
            {"services": {"llm": {"profiles": [None, "junk", 42]}}},
        ],
    )
    def test_empty_or_malformed_catalogs_yield_no_options(self, catalog: Any) -> None:
        payload = list_llm_options(catalog)

        assert payload == {"active": None, "options": []}

    def test_partially_active_ids_do_not_mark_a_default(self) -> None:
        catalog = _llm_service(
            [{"id": "p1", "models": [{"id": "m1", "model": "gpt-5"}]}],
            active_profile_id="p1",
        )

        payload = list_llm_options(catalog)

        assert payload["active"] is None
        assert payload["options"][0]["is_active_default"] is False

    def test_models_missing_an_id_or_model_value_are_skipped(self) -> None:
        catalog = _llm_service(
            [
                {
                    "id": "p1",
                    "models": [
                        {"model": "gpt-5"},
                        {"id": "m2"},
                        {"id": "", "model": "gpt-5"},
                        {"id": "m4", "model": "  "},
                        {"id": "m5", "model": "gpt-5"},
                    ],
                }
            ]
        )

        assert [o["model_id"] for o in list_llm_options(catalog)["options"]] == ["m5"]

    def test_profile_without_an_id_is_skipped(self) -> None:
        catalog = _llm_service([{"name": "no id", "models": [{"id": "m1", "model": "gpt-5"}]}])

        assert list_llm_options(catalog)["options"] == []


class TestInvalidValuesDegrade:
    def test_invalid_context_windows_are_dropped_not_raised(self) -> None:
        catalog = _llm_service(
            [
                {
                    "id": "p1",
                    "models": [
                        {"id": "m-bad", "model": "a", "context_window": "not-a-number"},
                        {"id": "m-negative", "model": "b", "context_window": "-5"},
                        {"id": "m-zero", "model": "c", "context_window": 0},
                    ],
                }
            ]
        )

        assert all("context_window" not in o for o in list_llm_options(catalog)["options"])

    def test_context_window_falls_back_to_the_tokens_alias(self) -> None:
        catalog = _llm_service(
            [{"id": "p1", "models": [{"id": "m1", "model": "a", "context_window_tokens": "8192"}]}]
        )

        assert list_llm_options(catalog)["options"][0]["context_window"] == 8192

    def test_unknown_binding_falls_back_to_the_raw_key_as_label(self) -> None:
        catalog = _llm_service(
            [{"id": "p1", "binding": "no-such-binding", "models": [{"id": "m1", "model": "a"}]}]
        )

        option = list_llm_options(catalog)["options"][0]
        assert option["provider"] == "no-such-binding"
        assert option["provider_label"] == "no-such-binding"

    def test_non_bool_capabilities_are_not_declared(self) -> None:
        catalog = _llm_service(
            [
                {
                    "id": "p1",
                    "models": [
                        {
                            "id": "m1",
                            "model": "a",
                            "capabilities": {
                                "reasoning": "yes",
                                "vision": True,
                                "tools": False,
                            },
                        }
                    ],
                }
            ]
        )

        option = list_llm_options(catalog)["options"][0]
        assert option["declared_vision"] is True
        assert "declared_reasoning" not in option
        assert "declared_tools" not in option

    def test_non_list_reasoning_levels_are_omitted_and_entries_normalized(self) -> None:
        catalog = _llm_service(
            [
                {
                    "id": "p1",
                    "models": [
                        {
                            "id": "m1",
                            "model": "a",
                            "codex_supported_reasoning_levels": "low",
                        }
                    ],
                },
                {
                    "id": "p2",
                    "models": [
                        {
                            "id": "m2",
                            "model": "b",
                            "codex_supported_reasoning_levels": [" HIGH ", "   ", ""],
                        }
                    ],
                },
            ]
        )

        options = list_llm_options(catalog)["options"]
        assert "supported_reasoning_efforts" not in options[0]
        assert options[1]["supported_reasoning_efforts"] == ["high"]


class TestSelectionPayloadEdges:
    def test_none_and_empty_payloads_mean_no_selection(self) -> None:
        assert LLMSelection.from_payload(None) is None
        assert LLMSelection.from_payload({}) is None
        assert apply_llm_selection_to_catalog(_llm_service([]), None) == {
            "services": {"llm": {"profiles": []}}
        }

    def test_non_dict_payload_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="expected an object"):
            LLMSelection.from_payload("profile=p1")

    def test_half_written_payload_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="required"):
            LLMSelection.from_payload({"profile_id": "p1", "model_id": ""})
        with pytest.raises(ValueError, match="required"):
            LLMSelection.from_payload({"profile_id": None, "model_id": "m1"})

    def test_falsy_id_values_coerce_and_strip(self) -> None:
        selection = LLMSelection.from_payload({"profile_id": 123, "model_id": " m1 "})

        assert selection == LLMSelection(profile_id="123", model_id="m1")

    def test_apply_none_returns_an_untouched_copy(self) -> None:
        catalog = _llm_service(
            [{"id": "p1", "models": [{"id": "m1", "model": "gpt-5"}]}],
            active_profile_id="p1",
            active_model_id="m1",
        )

        result = apply_llm_selection_to_catalog(catalog, None)

        assert result == catalog
        assert result is not catalog
