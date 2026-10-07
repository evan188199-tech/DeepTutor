"""Draft-merge edits: only the addressed entity changes, and validation rejects."""

from __future__ import annotations

from copy import deepcopy

import pytest

from deeptutor.services.settings.provider_edit import merge_provider_edit
from deeptutor.services.settings.registry_edit import merge_registry_edit


def make_catalog() -> dict:
    def profile(profile_id: str, **extra) -> dict:
        return {
            "id": profile_id,
            "name": profile_id.title(),
            "binding": "custom",
            "api_key": "stored-key",
            "models": [
                {"id": f"{profile_id}-one", "model": "model-one"},
                {"id": f"{profile_id}-two", "model": "model-two"},
            ],
            **extra,
        }

    return {
        "connections": [],
        "services": {
            "llm": {
                "active_profile_id": "main",
                "active_model_id": "main-one",
                "profiles": [profile("main")],
            },
            "task": {
                "active_profile_id": "main",
                "active_model_id": "main-one",
                "profiles": [profile("main")],
            },
            "search": {
                "active_profile_id": "web",
                "profiles": [
                    {
                        "id": "web",
                        "name": "Web",
                        "binding": "tavily",
                        "provider": "tavily",
                        "models": [],
                    }
                ],
            },
        },
    }


# --- merge_provider_edit ------------------------------------------------------


def test_provider_id_is_required() -> None:
    for bad in ("", None, 7):
        with pytest.raises(ValueError, match="provider ID"):
            merge_provider_edit(make_catalog(), "llm", {"id": bad})


def test_new_provider_is_appended_without_touching_activation() -> None:
    current = make_catalog()
    new_profile = {"id": "spare", "name": "Spare", "binding": "custom", "models": []}

    result = merge_provider_edit(current, "llm", new_profile)

    assert [p["id"] for p in result["services"]["llm"]["profiles"]] == ["main", "spare"]
    assert result["services"]["llm"]["active_profile_id"] == "main"
    assert result["services"]["llm"]["active_model_id"] == "main-one"
    assert current["services"]["llm"]["profiles"] == [current["services"]["llm"]["profiles"][0]]


def test_activation_requires_a_real_model() -> None:
    current = make_catalog()
    profile = deepcopy(current["services"]["llm"]["profiles"][0])

    with pytest.raises(ValueError, match="Choose a model"):
        merge_provider_edit(current, "llm", profile, active_model_id="missing", activate=True)

    hollow = deepcopy(profile)
    hollow["models"] = [{"id": "main-one"}]
    with pytest.raises(ValueError, match="Choose a model"):
        merge_provider_edit(current, "llm", hollow, active_model_id="main-one", activate=True)


def test_activation_sets_ids_and_task_mode() -> None:
    current = make_catalog()

    llm_result = merge_provider_edit(
        current,
        "llm",
        current["services"]["llm"]["profiles"][0],
        active_model_id="main-two",
        activate=True,
    )
    assert llm_result["services"]["llm"]["active_profile_id"] == "main"
    assert llm_result["services"]["llm"]["active_model_id"] == "main-two"

    task_result = merge_provider_edit(
        current,
        "task",
        current["services"]["task"]["profiles"][0],
        active_model_id="main-one",
        activate=True,
    )
    assert task_result["services"]["task"]["mode"] == "profiles"
    assert task_result["services"]["task"]["active_model_id"] == "main-one"


# --- merge_registry_edit -------------------------------------------------------


def test_provider_rename_requires_a_name() -> None:
    edit = {
        "kind": "provider",
        "ref": {"connection_id": "main"},
        "fields": {"provider": "custom", "name": "   "},
    }
    catalog = make_catalog()
    catalog["connections"] = [{"id": "main", "provider": "custom", "name": "Main"}]

    with pytest.raises(ValueError, match="name is required"):
        merge_registry_edit(catalog, edit)


def test_managed_connection_cannot_be_deleted_from_the_registry() -> None:
    catalog = make_catalog()
    catalog["connections"] = [
        {"id": "main", "provider": "custom", "name": "Main", "managed_by": True}
    ]
    edit = {"kind": "provider", "ref": {"connection_id": "main"}, "delete": True}

    with pytest.raises(ValueError, match="authentication settings"):
        merge_registry_edit(catalog, edit)
    assert catalog["connections"] == [
        {"id": "main", "provider": "custom", "name": "Main", "managed_by": True}
    ]


def test_unknown_edit_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown registry edit"):
        merge_registry_edit(make_catalog(), {"kind": "teleport"})


def test_first_provider_edit_creates_a_named_connection() -> None:
    catalog = make_catalog()
    edit = {
        "kind": "provider",
        "ref": {"connection_id": "brand-new"},
        "fields": {"provider": "custom", "name": "Brand New", "base_url": "https://new.test/v1"},
    }

    created = merge_registry_edit(catalog, edit)

    assert [c["id"] for c in created["connections"]] == ["brand-new"]
    assert created["connections"][0]["name"] == "Brand New"

    updated = merge_registry_edit(
        created,
        {**edit, "fields": {"provider": "custom", "name": "Renamed", "base_url": ""}},
    )
    assert [c["id"] for c in updated["connections"]] == ["brand-new"]
    assert updated["connections"][0]["name"] == "Renamed"


def test_default_edit_promotes_profile_and_model() -> None:
    edit = {"kind": "default", "service": "llm", "profile_id": "main", "model_id": "main-two"}

    result = merge_registry_edit(make_catalog(), edit)

    bucket = result["services"]["llm"]
    assert bucket["active_profile_id"] == "main"
    assert bucket["active_model_id"] == "main-two"


def test_search_model_delete_removes_bound_profile_or_flags_provider_only() -> None:
    bound = make_catalog()
    bound["services"]["search"]["profiles"][0]["provider_ref"] = {
        "connection_id": "main",
        "binding": "custom",
    }
    result = merge_registry_edit(
        bound,
        {"kind": "model", "service": "search", "profile_id": "web", "delete": True},
    )
    assert result["services"]["search"]["profiles"] == []

    loose = make_catalog()
    flagged = merge_registry_edit(
        loose,
        {"kind": "model", "service": "search", "profile_id": "web", "delete": True},
    )
    assert len(flagged["services"]["search"]["profiles"]) == 1
    assert flagged["services"]["search"]["profiles"][0]["provider_only"] is True


def test_llm_model_delete_falls_back_to_remaining_profile_and_model() -> None:
    catalog = make_catalog()
    catalog["services"]["llm"]["profiles"].append(
        {
            "id": "spare",
            "name": "Spare",
            "binding": "custom",
            "models": [{"id": "spare-one", "model": "m"}],
        }
    )

    result = merge_registry_edit(
        catalog,
        {
            "kind": "model",
            "service": "llm",
            "profile_id": "spare",
            "model_id": "spare-one",
            "delete": True,
        },
    )

    bucket = result["services"]["llm"]
    # The emptied profile is only dropped when it holds a provider_ref; a
    # free-standing profile survives with no models and is simply never a
    # candidate for activation.
    assert [p["id"] for p in bucket["profiles"]] == ["main", "spare"]
    assert bucket["profiles"][1]["models"] == []
    assert bucket["active_profile_id"] == "main"
    assert bucket["active_model_id"] == "main-one"
