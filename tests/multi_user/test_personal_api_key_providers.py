"""Personal API-key providers — bring your own key (issue #1927).

An ordinary user in an authenticated deployment adds an API-key provider
(OpenAI-compatible registry vendors) usable only by their own account. The
isolation that makes it safe is asserted here:

* the deployment switch is off by default — no personal provider can be
  saved, and one already saved disappears from every surface without
  deleting the stored key;
* when the administrator allows it, the profile lands in the user's OWN
  catalog with an empty ``api_key``, and the key in the owner's secret
  store — never in any catalog file, and never outside that user's scope;
* options, the capability gate, selection validation, and runtime resolution
  all expose the provider to its owner and to nobody else;
* admin behavior and grants are unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deeptutor.multi_user import model_access, personal_models, personal_providers
from deeptutor.services.config.runtime_settings import get_runtime_settings_service

SHARED_PROFILE = "llm-profile-shared-key"


@pytest.fixture(autouse=True)
def current_codex_profile(monkeypatch):
    monkeypatch.setattr(
        personal_models,
        "_codex_profile_is_current",
        lambda _profile: True,
        raising=False,
    )


@pytest.fixture
def no_grants(monkeypatch):
    monkeypatch.setattr(model_access, "load_grant", lambda _uid=None: {"models": {"llm": []}})


@pytest.fixture
def empty_admin_catalog(monkeypatch):
    monkeypatch.setattr(
        model_access, "admin_catalog", lambda: {"services": {"llm": {"profiles": []}}}
    )


def _allow_personal_providers(monkeypatch, allowed: bool) -> None:
    """Flip the deployment switch the way the admin endpoint does."""
    service = get_runtime_settings_service()
    current = service.load_system(include_process_overrides=False)
    saved = service.save_system({**current, "allow_personal_providers": allowed})
    assert saved["allow_personal_providers"] is allowed


def _save_openrouter(as_user, *, key: str = "sk-or-v1-test") -> dict[str, Any]:
    with as_user("u_alice"):
        return personal_providers.save_personal_provider(
            name="My OpenRouter",
            binding="openrouter",
            api_key=key,
            models=[{"id": "m-or", "name": "OpenRouter model", "model": "openai/gpt-4o"}],
        )


def test_policy_is_off_by_default(as_user, mu_isolated_root):
    with as_user("u_alice"):
        assert personal_providers.personal_providers_allowed() is False
        assert personal_providers.allowed_provider_bindings()  # the list itself is public


def test_save_is_refused_while_the_policy_is_off(as_user, mu_isolated_root, no_grants):
    with as_user("u_alice"):
        with pytest.raises(personal_providers.PersonalProviderError):
            personal_providers.save_personal_provider(
                name="My OpenRouter",
                binding="openrouter",
                api_key="sk-or-v1-test",
                models=[{"model": "openai/gpt-4o"}],
            )
        # Nothing was written anywhere.
        assert not personal_models.owner_catalog_service().path.exists()
        assert personal_providers.list_personal_providers() == []


def test_saved_provider_lands_in_the_users_own_catalog_and_secret_store(
    as_user, monkeypatch, mu_isolated_root, no_grants, empty_admin_catalog
):
    _allow_personal_providers(monkeypatch, True)
    saved = _save_openrouter(as_user)

    assert saved == {
        "id": "personal-openrouter",
        "name": "My OpenRouter",
        "binding": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "has_api_key": True,
        "models": [{"id": "m-or", "name": "OpenRouter model", "model": "openai/gpt-4o"}],
    }
    # The stored catalog profile carries no secret…
    with as_user("u_alice"):
        stored = personal_models.owner_catalog_service().load()
        profile = stored["services"]["llm"]["profiles"][0]
        assert profile["api_key"] == ""
        assert profile["owner_bound"] is True
        assert profile["managed_by"] == personal_providers.MANAGED_BY
        assert profile["base_url"] == "https://openrouter.ai/api/v1"
        # …the key lives in the owner's secret store, under data/system.
        secret_file = (
            mu_isolated_root
            / "data"
            / "system"
            / "user-secrets"
            / "u_alice"
            / "private"
            / "personal-providers"
            / "personal-openrouter.json"
        )
        assert secret_file.is_file()
        assert json.loads(secret_file.read_text("utf-8")) == {"api_key": "sk-or-v1-test"}
        assert (secret_file.stat().st_mode & 0o777) == 0o600


def test_personal_provider_reaches_the_owners_options_and_no_one_elses(
    as_user, monkeypatch, mu_isolated_root, no_grants, empty_admin_catalog
):
    _allow_personal_providers(monkeypatch, True)
    _save_openrouter(as_user)

    with as_user("u_alice"):
        rows = model_access.redacted_model_access()["llm"]
        assert [(r["model_id"], r["source"], r["available"]) for r in rows] == [
            ("m-or", "personal", True)
        ]
        options = model_access.allowed_llm_options()["options"]
        assert [(o["model_id"], o["source"]) for o in options] == [("m-or", "personal")]
        assert model_access.has_capability_access("llm") is True
        assert model_access.apply_allowed_llm_selection(
            {"profile_id": "personal-openrouter", "model_id": "m-or"}
        ) == {"profile_id": "personal-openrouter", "model_id": "m-or"}

    with as_user("u_bob"):
        assert model_access.redacted_model_access()["llm"] == []
        assert model_access.has_capability_access("llm") is False
        with pytest.raises(PermissionError):
            model_access.apply_allowed_llm_selection(
                {"profile_id": "personal-openrouter", "model_id": "m-or"}
            )

    with as_user("root", role="admin"):
        # The grant editor's view of the user, and the admin's own list.
        assert model_access.redacted_model_access("u_alice")["llm"] == []
        assert personal_models.personal_llm_rows() == []


def test_runtime_resolution_uses_the_injected_key_for_the_owner_only(
    as_user, monkeypatch, mu_isolated_root, no_grants, empty_admin_catalog
):
    from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config

    _allow_personal_providers(monkeypatch, True)
    _save_openrouter(as_user)

    with as_user("u_alice"):
        merged = personal_models.merge_personal_llm_profiles(
            {"services": {"llm": {"profiles": []}}}
        )
        profile = merged["services"]["llm"]["profiles"][0]
        assert profile["api_key"] == "sk-or-v1-test"

        resolved = resolve_llm_runtime_config(
            llm_selection={"profile_id": "personal-openrouter", "model_id": "m-or"}
        )
        assert resolved.model == "openai/gpt-4o"
        assert resolved.api_key == "sk-or-v1-test"
        assert resolved.effective_url == "https://openrouter.ai/api/v1"
        assert resolved.provider_name == "openrouter"

    with as_user("u_bob"):
        # The same selection does not resolve for anybody else: the merged
        # catalog bob resolves against has no such profile, so the selection
        # is rejected instead of silently billing somebody else's key.
        with pytest.raises(ValueError):
            resolve_llm_runtime_config(
                llm_selection={"profile_id": "personal-openrouter", "model_id": "m-or"}
            )


def test_turning_the_policy_off_hides_the_provider_but_keeps_the_secret(
    as_user, monkeypatch, mu_isolated_root, no_grants, empty_admin_catalog
):
    _allow_personal_providers(monkeypatch, True)
    _save_openrouter(as_user)

    _allow_personal_providers(monkeypatch, False)
    with as_user("u_alice"):
        assert model_access.redacted_model_access()["llm"] == []
        assert model_access.has_capability_access("llm") is False
        with pytest.raises(PermissionError):
            model_access.apply_allowed_llm_selection(
                {"profile_id": "personal-openrouter", "model_id": "m-or"}
            )
        merged = personal_models.merge_personal_llm_profiles(
            {"services": {"llm": {"profiles": []}}}
        )
        assert merged["services"]["llm"]["profiles"] == []
        # Still listed (so it can be deleted), key still on disk.
        providers = personal_providers.list_personal_providers()
        assert [p["id"] for p in providers] == ["personal-openrouter"]
        secret_file = (
            mu_isolated_root
            / "data"
            / "system"
            / "user-secrets"
            / "u_alice"
            / "private"
            / "personal-providers"
            / "personal-openrouter.json"
        )
        assert secret_file.is_file()


def test_delete_removes_the_profile_and_the_secret(
    as_user, monkeypatch, mu_isolated_root, no_grants, empty_admin_catalog
):
    _allow_personal_providers(monkeypatch, True)
    _save_openrouter(as_user)

    # Policy off on purpose: deleting one's own provider stays possible.
    _allow_personal_providers(monkeypatch, False)
    with as_user("u_alice"):
        personal_providers.delete_personal_provider("personal-openrouter")
        assert personal_providers.list_personal_providers() == []
        stored = personal_models.owner_catalog_service().load()
        assert stored["services"]["llm"]["profiles"] == []
        assert not (
            mu_isolated_root
            / "data"
            / "system"
            / "user-secrets"
            / "u_alice"
            / "private"
            / "personal-providers"
            / "personal-openrouter.json"
        ).exists()
        with pytest.raises(personal_providers.PersonalProviderError):
            personal_providers.delete_personal_provider("personal-openrouter")


def test_update_without_a_key_keeps_the_stored_one(
    as_user, monkeypatch, mu_isolated_root, no_grants, empty_admin_catalog
):
    _allow_personal_providers(monkeypatch, True)
    _save_openrouter(as_user)

    with as_user("u_alice"):
        saved = personal_providers.save_personal_provider(
            profile_id="personal-openrouter",
            name="Renamed",
            binding="openrouter",
            api_key=None,
            models=[{"model": "openai/gpt-4o"}, {"model": "anthropic/claude-sonnet-4"}],
        )
        assert saved["name"] == "Renamed"
        assert saved["has_api_key"] is True
        assert [m["model"] for m in saved["models"]] == [
            "openai/gpt-4o",
            "anthropic/claude-sonnet-4",
        ]
        # One profile, not two.
        assert [p["id"] for p in personal_providers.list_personal_providers()] == [
            "personal-openrouter"
        ]


def test_only_fixed_endpoint_vendors_are_accepted(
    as_user, monkeypatch, mu_isolated_root, no_grants
):
    _allow_personal_providers(monkeypatch, True)
    bindings = personal_providers.allowed_provider_bindings()
    assert "openrouter" in bindings and "openai" in bindings and "anthropic" in bindings
    # No user-supplied endpoint, no OAuth vendors, no local ones.
    assert "custom" not in bindings
    assert "custom_anthropic" not in bindings
    assert "openai_codex" not in bindings
    assert "github_copilot" not in bindings
    assert "codebuddy" not in bindings
    assert "ollama" not in bindings

    with as_user("u_alice"):
        for binding in ("custom", "openai_codex", "ollama", "no-such-vendor"):
            with pytest.raises(personal_providers.PersonalProviderError):
                personal_providers.save_personal_provider(
                    binding=binding,
                    api_key="k",
                    models=[{"model": "m"}],
                )


def test_ids_cannot_replace_another_providers_profile(
    as_user, monkeypatch, mu_isolated_root, no_grants
):
    _allow_personal_providers(monkeypatch, True)
    codex_profile = {
        "id": "llm-profile-openai-codex-managed",
        "name": "OpenAI Codex",
        "binding": "openai_codex",
        "api_key": "",
        "owner_bound": True,
        "managed_by": "openai_codex_oauth",
        "models": [{"id": "m-sol", "name": "m-sol", "model": "gpt-5.6-sol"}],
    }
    with as_user("u_alice"):
        personal_models.owner_catalog_service().update(
            lambda catalog: catalog["services"]["llm"]["profiles"].append(codex_profile)
        )
        with pytest.raises(personal_providers.PersonalProviderError):
            personal_providers.save_personal_provider(
                profile_id="llm-profile-openai-codex-managed",
                binding="openrouter",
                api_key="k",
                models=[{"model": "m"}],
            )
        with pytest.raises(personal_providers.PersonalProviderError):
            personal_providers.save_personal_provider(
                profile_id="personal-../escape",
                binding="openrouter",
                api_key="k",
                models=[{"model": "m"}],
            )


def test_a_key_is_required_and_admins_are_refused(
    as_user, monkeypatch, mu_isolated_root, no_grants
):
    _allow_personal_providers(monkeypatch, True)
    with as_user("u_alice"):
        with pytest.raises(personal_providers.PersonalProviderError):
            personal_providers.save_personal_provider(
                binding="openrouter",
                api_key="",
                models=[{"model": "m"}],
            )
    with as_user("root", role="admin"):
        with pytest.raises(personal_providers.PersonalProviderError):
            personal_providers.save_personal_provider(
                binding="openrouter",
                api_key="k",
                models=[{"model": "m"}],
            )


def test_granted_admin_models_and_personal_providers_coexist(
    as_user, monkeypatch, mu_isolated_root, empty_admin_catalog
):
    shared = {
        "id": SHARED_PROFILE,
        "name": "Team key",
        "models": [{"id": "m-team", "name": "Team model", "model": "gpt-4o"}],
    }
    monkeypatch.setattr(
        model_access,
        "admin_catalog",
        lambda: {"services": {"llm": {"profiles": [shared]}}},
    )
    monkeypatch.setattr(
        model_access,
        "load_grant",
        lambda _uid=None: {
            "models": {"llm": [{"profile_id": SHARED_PROFILE, "model_ids": ["m-team"]}]}
        },
    )
    _allow_personal_providers(monkeypatch, True)
    _save_openrouter(as_user)

    with as_user("u_alice"):
        rows = model_access.redacted_model_access()["llm"]
        assert [(r["model_id"], r["source"]) for r in rows] == [
            ("m-team", "admin"),
            ("m-or", "personal"),
        ]


def test_codex_personal_profiles_are_not_gated_by_the_new_switch(
    as_user, monkeypatch, mu_isolated_root, no_grants, empty_admin_catalog
):
    """The switch guards API-key providers only; the per-user Codex sign-in
    (#781) must keep working on a deployment that never turned it on."""
    codex_profile = {
        "id": "llm-profile-openai-codex-managed",
        "name": "OpenAI Codex",
        "binding": "openai_codex",
        "api_key": "",
        "owner_bound": True,
        "managed_by": "openai_codex_oauth",
        "models": [{"id": "m-sol", "name": "m-sol", "model": "gpt-5.6-sol"}],
    }
    with as_user("u_alice"):
        personal_models.owner_catalog_service().update(
            lambda catalog: catalog["services"]["llm"]["profiles"].append(codex_profile)
        )

    assert personal_providers.personal_providers_allowed() is False
    with as_user("u_alice"):
        rows = model_access.redacted_model_access()["llm"]
        assert [(r["model_id"], r["source"]) for r in rows] == [("m-sol", "personal")]
