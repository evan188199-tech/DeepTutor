"""Validation, default merging, and persistence contracts for settings edits.

Failure-branch coverage for ``services.settings.registry_edit`` and
``services.settings.provider_edit`` on real catalog files: rejected edits,
defaults chosen for unconfigured services, and save/load round trips.
"""

from copy import deepcopy

import pytest

from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.settings.provider_edit import merge_provider_edit
from deeptutor.services.settings.registry_edit import merge_registry_edit


def make_store(tmp_path):
    store = ModelCatalogService(tmp_path / "catalog.json")
    return store, store.load()


def add_profile(catalog, service, profile_id, *, models=("one",), api_key=None):
    profile = {
        "id": profile_id,
        "name": profile_id,
        "binding": "custom",
        "provider": "custom",
        "base_url": "https://legacy.test/v1",
        "api_key": api_key if api_key is not None else "key-" + profile_id,
        "models": [
            {"id": f"{profile_id}-{name}", "model": f"model-{name}", "context_window": "4096"}
            for name in models
        ],
    }
    catalog["services"][service]["profiles"].append(profile)
    return profile


def with_connection(catalog, connection_id="conn", *, managed_by=False):
    catalog["connections"] = [
        {
            "id": connection_id,
            "provider": "custom",
            "name": connection_id,
            "api_key": "conn-key",
            **({"managed_by": True} if managed_by else {}),
        }
    ]
    return catalog


def model_edit(profile_id, model, *, service="llm", model_id=None, delete=False):
    edit = {"kind": "model", "service": service, "profile_id": profile_id, "model": model}
    if model_id is not None:
        edit["model_id"] = model_id
    if delete:
        edit["delete"] = True
    return edit


# ---------------------------------------------------------------------------
# merge_registry_edit — illegal input rejection
# ---------------------------------------------------------------------------


def test_unknown_edit_kind_rejected():
    with pytest.raises(ValueError, match="Unknown registry edit"):
        merge_registry_edit({}, {"kind": "teleport"})


def test_unknown_model_service_rejected():
    with pytest.raises(ValueError, match="Unknown model service"):
        merge_registry_edit({}, {"kind": "model", "service": "holodeck", "profile_id": "p"})


def test_missing_model_profile_id_rejected(tmp_path):
    _, catalog = make_store(tmp_path)
    with pytest.raises(ValueError, match="profile ID is required"):
        merge_registry_edit(catalog, {"kind": "model", "service": "llm", "model": {"id": "m"}})


@pytest.mark.parametrize(
    "ref",
    [{}, {"service": "llm", "profile_id": "ghost"}],
    ids=["no-ref", "unknown-legacy-profile"],
)
def test_provider_source_must_exist_or_be_creatable(ref):
    catalog = with_connection({})
    deleting = bool(ref)
    with pytest.raises(ValueError, match="existing provider"):
        merge_registry_edit(
            catalog, {"kind": "provider", "ref": ref, "fields": {}, "delete": deleting}
        )


def test_managed_connection_delete_points_to_auth_settings():
    catalog = with_connection({}, managed_by=True)
    with pytest.raises(ValueError, match="authentication settings"):
        merge_registry_edit(
            catalog,
            {"kind": "provider", "ref": {"connection_id": "conn"}, "delete": True},
        )


def test_provider_rename_requires_a_name(tmp_path):
    store, catalog = make_store(tmp_path)
    add_profile(catalog, "llm", "legacy")
    catalog = store.save(catalog)
    with pytest.raises(ValueError, match="name is required"):
        merge_registry_edit(
            catalog,
            {
                "kind": "provider",
                "ref": {"service": "llm", "profile_id": "legacy"},
                "fields": {"name": "   "},
            },
        )


def test_provider_edit_creates_named_connection_when_missing(tmp_path):
    store, catalog = make_store(tmp_path)
    catalog = store.save(catalog)
    merged = merge_registry_edit(
        catalog,
        {
            "kind": "provider",
            "ref": {"connection_id": "brand-new"},
            "fields": {"provider": "custom", "name": "New account", "api_key": "new-key"},
        },
    )
    assert [c["id"] for c in merged["connections"]] == ["brand-new"]
    saved = store.save(merged)
    assert store.load() == saved
    assert store.load()["connections"][0]["name"] == "New account"


@pytest.mark.parametrize(
    "edit",
    [
        {
            "kind": "model",
            "service": "llm",
            "profile_id": "ghost",
            "model": {"id": "m", "model": "m"},
        },
        {
            "kind": "model",
            "service": "llm",
            "profile_id": "legacy",
            "model": {"id": "m", "model": "m"},
        },
    ],
    ids=["missing-profile-no-ref", "legacy-profile-without-source"],
)
def test_new_model_requires_a_provider_reference(tmp_path, edit):
    _, catalog = make_store(tmp_path)
    add_profile(catalog, "llm", "legacy")
    with pytest.raises(ValueError, match="existing provider"):
        merge_registry_edit(catalog, edit)


def test_model_requires_an_id(tmp_path):
    store, catalog = make_store(tmp_path)
    add_profile(catalog, "llm", "legacy")
    catalog = store.save(catalog)
    with pytest.raises(ValueError, match="model ID is required"):
        merge_registry_edit(catalog, model_edit("legacy", {"id": "", "model": "  "}, model_id=""))


def test_default_on_missing_model_rejected(tmp_path):
    store, catalog = make_store(tmp_path)
    add_profile(catalog, "llm", "legacy")
    catalog = store.save(catalog)
    with pytest.raises(ValueError, match="no longer exists"):
        merge_registry_edit(
            catalog,
            {"kind": "default", "service": "llm", "profile_id": "legacy", "model_id": "gone"},
        )


def test_deleting_task_reference_model_rejected_then_sibling_deletes(tmp_path):
    store, catalog = make_store(tmp_path)
    add_profile(catalog, "llm", "p1", models=("a", "b"))
    catalog["services"]["task"].update(
        mode="reference", selection={"profile_id": "p1", "model_id": "p1-a"}
    )
    catalog = store.save(catalog)
    with pytest.raises(ValueError, match="background tasks"):
        merge_registry_edit(catalog, model_edit("p1", {"id": "p1-a"}, model_id="p1-a", delete=True))
    merged = merge_registry_edit(
        catalog, model_edit("p1", {"id": "p1-b"}, model_id="p1-b", delete=True)
    )
    assert [m["id"] for m in merged["services"]["llm"]["profiles"][0]["models"]] == ["p1-a"]


# ---------------------------------------------------------------------------
# merge_registry_edit — default merging for unconfigured services
# ---------------------------------------------------------------------------


def test_first_model_save_fills_empty_service_defaults(tmp_path):
    store, catalog = make_store(tmp_path)
    catalog = with_connection(catalog)
    catalog = store.save(catalog)
    merged = merge_registry_edit(
        catalog,
        model_edit(
            "np",
            {
                "id": "nm",
                "model": "m",
                "provider_ref": {"connection_id": "conn", "binding": "custom"},
            },
            model_id="nm",
        ),
    )
    bucket = merged["services"]["llm"]
    assert bucket["active_profile_id"] == "np"
    assert bucket["active_model_id"] == "nm"
    profile = bucket["profiles"][0]
    assert profile["name"] == "conn"
    assert "api_key" not in profile
    saved = store.save(merged)
    assert store.load() == saved


def test_task_model_save_switches_task_to_profiles_mode(tmp_path):
    store, catalog = make_store(tmp_path)
    catalog = with_connection(catalog)
    catalog = store.save(catalog)
    merged = merge_registry_edit(
        catalog,
        model_edit(
            "tp",
            {
                "id": "tm",
                "model": "m",
                "provider_ref": {"connection_id": "conn", "binding": "custom"},
            },
            service="task",
            model_id="tm",
        ),
    )
    assert merged["services"]["task"]["mode"] == "profiles"
    assert merged["services"]["task"]["active_profile_id"] == "tp"


def test_model_save_keeps_existing_active_choice(tmp_path):
    store, catalog = make_store(tmp_path)
    add_profile(catalog, "llm", "p1")
    catalog = with_connection(catalog)
    catalog["services"]["llm"]["active_profile_id"] = "p1"
    catalog["services"]["llm"]["active_model_id"] = "p1-one"
    catalog = store.save(catalog)
    merged = merge_registry_edit(
        catalog,
        model_edit(
            "np",
            {
                "id": "nm",
                "model": "m",
                "provider_ref": {"connection_id": "conn", "binding": "custom"},
            },
            model_id="nm",
        ),
    )
    assert merged["services"]["llm"]["active_profile_id"] == "p1"
    assert merged["services"]["llm"]["active_model_id"] == "p1-one"


# ---------------------------------------------------------------------------
# merge_registry_edit — deletion picks the remaining defaults
# ---------------------------------------------------------------------------


def test_delete_last_model_clears_active_selection(tmp_path):
    store, catalog = make_store(tmp_path)
    add_profile(catalog, "llm", "p1")
    catalog["services"]["llm"]["profiles"][0]["provider_ref"] = {"connection_id": "conn"}
    catalog = with_connection(catalog)
    catalog["services"]["llm"]["active_profile_id"] = "p1"
    catalog["services"]["llm"]["active_model_id"] = "p1-one"
    catalog = store.save(catalog)
    merged = merge_registry_edit(
        catalog, model_edit("p1", {"id": "p1-one"}, model_id="p1-one", delete=True)
    )
    bucket = merged["services"]["llm"]
    assert bucket["profiles"] == []
    assert bucket["active_profile_id"] is None
    assert bucket["active_model_id"] is None


def test_delete_reactivates_remaining_profile(tmp_path):
    store, catalog = make_store(tmp_path)
    add_profile(catalog, "llm", "p1")
    add_profile(catalog, "llm", "p2", api_key="key-p2")
    for profile in catalog["services"]["llm"]["profiles"]:
        profile["provider_ref"] = {"connection_id": "conn"}
    catalog = with_connection(catalog)
    catalog["services"]["llm"]["active_profile_id"] = "p1"
    catalog["services"]["llm"]["active_model_id"] = "p1-one"
    catalog = store.save(catalog)
    merged = merge_registry_edit(
        catalog, model_edit("p1", {"id": "p1-one"}, model_id="p1-one", delete=True)
    )
    bucket = merged["services"]["llm"]
    assert [p["id"] for p in bucket["profiles"]] == ["p2"]
    assert bucket["active_profile_id"] == "p2"
    assert bucket["active_model_id"] == "p2-one"


def test_search_delete_removes_referenced_profile_and_keeps_source(tmp_path):
    store, catalog = make_store(tmp_path)
    catalog["services"]["search"]["profiles"] = [
        {
            "id": "src",
            "name": "Tavily",
            "provider": "tavily",
            "api_key": "search-key",
            "models": [],
        },
        {
            "id": "refp",
            "name": "My search",
            "provider_ref": {"service": "search", "profile_id": "src", "binding": "tavily"},
            "models": [],
        },
    ]
    catalog["services"]["search"]["active_profile_id"] = "refp"
    catalog = store.save(catalog)
    merged = merge_registry_edit(
        catalog,
        {"kind": "model", "service": "search", "profile_id": "refp", "delete": True},
    )
    bucket = merged["services"]["search"]
    assert [p["id"] for p in bucket["profiles"]] == ["src"]
    assert not any(p.get("provider_only") for p in bucket["profiles"])
    assert bucket["active_profile_id"] == "src"


# ---------------------------------------------------------------------------
# merge_registry_edit — model field hygiene
# ---------------------------------------------------------------------------


def test_model_credentials_are_never_stored(tmp_path):
    store, catalog = make_store(tmp_path)
    add_profile(catalog, "llm", "p1")
    catalog = with_connection(catalog)
    catalog = store.save(catalog)
    merged = merge_registry_edit(
        catalog,
        model_edit(
            "p1",
            {
                "id": "p1-one",
                "model": "model-one",
                "api_key": "should-not-store",
                "base_url": "https://should-not.test",
                "extra_headers": {"X-Sneak": "1"},
                "api_version": "2099-01",
                "custom_note": "kept",
            },
            model_id="p1-one",
        ),
    )
    stored = merged["services"]["llm"]["profiles"][0]["models"][0]
    assert stored["custom_note"] == "kept"
    for field in ("api_key", "base_url", "extra_headers", "api_version"):
        assert field not in stored


@pytest.mark.parametrize(
    "submitted,kept",
    [("8192", False), ("4096", True)],
    ids=["changed-window", "unchanged-window"],
)
def test_context_window_change_drops_saved_tokens(submitted, kept, tmp_path):
    store, catalog = make_store(tmp_path)
    profile = add_profile(catalog, "llm", "p1")
    profile["models"][0]["context_window_tokens"] = 123
    catalog = with_connection(catalog)
    catalog = store.save(catalog)
    merged = merge_registry_edit(
        catalog,
        model_edit(
            "p1",
            {"id": "p1-one", "model": "model-one", "context_window": submitted},
            model_id="p1-one",
        ),
    )
    stored = merged["services"]["llm"]["profiles"][0]["models"][0]
    assert stored.get("context_window") == submitted
    assert ("context_window_tokens" in stored) is kept


# ---------------------------------------------------------------------------
# merge_provider_edit — illegal input rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "profile", [{}, {"id": ""}, {"id": 5}], ids=["missing", "empty", "not-str"]
)
def test_provider_id_required(profile):
    with pytest.raises(ValueError, match="provider ID is required"):
        merge_provider_edit({}, "llm", profile)


def test_connection_without_id_rejected(tmp_path):
    store, catalog = make_store(tmp_path)
    catalog = store.save(catalog)
    profile = {"id": "p1", "connection_id": "conn", "models": [{"id": "m", "model": "m"}]}
    with pytest.raises(ValueError, match="connection"):
        merge_provider_edit(catalog, "llm", profile, connection={})


# ---------------------------------------------------------------------------
# merge_provider_edit — append defaults and activation
# ---------------------------------------------------------------------------


def test_new_profile_appended_without_mutating_input(tmp_path):
    store, catalog = make_store(tmp_path)
    catalog = store.save(catalog)
    before = deepcopy(catalog)
    fresh = {
        "id": "fresh",
        "name": "Fresh",
        "api_key": "sk-fresh",
        "models": [{"id": "m1", "model": "m"}],
    }
    merged = merge_provider_edit(catalog, "llm", fresh)
    assert merged["services"]["llm"]["profiles"] == [fresh]
    assert catalog == before
    assert merged["services"]["task"] == before["services"]["task"]
    saved = store.save(merged)
    assert store.load() == saved


def test_new_connection_appended_when_absent(tmp_path):
    store, catalog = make_store(tmp_path)
    catalog = store.save(catalog)
    profile = {"id": "p1", "connection_id": "new-conn", "models": [{"id": "m1", "model": "m"}]}
    connection = {"id": "new-conn", "provider": "custom", "name": "NC", "api_key": "k"}
    merged = merge_provider_edit(catalog, "llm", profile, connection=connection)
    assert [c["id"] for c in merged["connections"]] == ["new-conn"]
    saved = store.save(merged)
    assert store.load() == saved
    assert store.load()["connections"][0]["id"] == "new-conn"


def test_activate_task_sets_profiles_mode(tmp_path):
    store, catalog = make_store(tmp_path)
    catalog = store.save(catalog)
    profile = {"id": "tp", "name": "T", "models": [{"id": "tm", "model": "m"}]}
    merged = merge_provider_edit(catalog, "task", profile, activate=True, active_model_id="tm")
    bucket = merged["services"]["task"]
    assert bucket["mode"] == "profiles"
    assert bucket["active_profile_id"] == "tp"
    assert bucket["active_model_id"] == "tm"


@pytest.mark.parametrize(
    "profile,active_model_id",
    [
        ({"id": "tp", "name": "T", "models": [{"id": "tm", "model": "m"}]}, None),
        ({"id": "tp", "name": "T", "models": [{"id": "tm"}]}, "tm"),
    ],
    ids=["no-active-model", "model-without-model-string"],
)
def test_activate_requires_a_saved_model(tmp_path, profile, active_model_id):
    _, catalog = make_store(tmp_path)
    with pytest.raises(ValueError, match="Choose a model"):
        merge_provider_edit(
            catalog, "task", profile, activate=True, active_model_id=active_model_id
        )


def test_activate_search_sets_default_without_models(tmp_path):
    store, catalog = make_store(tmp_path)
    catalog = store.save(catalog)
    profile = {"id": "sp", "name": "S", "provider": "tavily", "models": []}
    merged = merge_provider_edit(catalog, "search", profile, activate=True)
    assert merged["services"]["search"]["active_profile_id"] == "sp"
    assert "active_model_id" not in merged["services"]["search"]
