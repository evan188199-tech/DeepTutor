"""Direct contract and boundary tests for ``multi_user.personal_models``.

``test_personal_codex_models.py`` drives the module end to end through
``model_access``; this file pins the module's own functions at the unit
level — which catalog each scope resolves to, which profiles survive the
personal filter, the exact row shape, the degradation when the Codex auth
service is unavailable, and the merge's replace-priority and immutability
contract.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from deeptutor.multi_user import personal_models
from deeptutor.services.path_service import PathService

CODEX_PROFILE = "llm-profile-openai-codex-managed"
COPILOT_PROFILE = "llm-profile-copilot"
REAL_CURRENCY_CHECK = personal_models._codex_profile_is_current


@pytest.fixture(autouse=True)
def codex_sign_in_is_current(monkeypatch):
    monkeypatch.setattr(
        personal_models,
        "_codex_profile_is_current",
        lambda _profile: True,
        raising=False,
    )


@pytest.fixture(autouse=True)
def default_path_service_isolated(monkeypatch, mu_isolated_root):
    """Re-resolve the no-context ``PathService`` singleton under tmp_path.

    ``_resolve_owner`` falls back to the process-wide singleton for CLI and
    background scopes; without this it could be a cached instance still
    pointed at the developer's real runtime home.
    """
    monkeypatch.setenv("DEEPTUTOR_HOME", str(mu_isolated_root))
    monkeypatch.setattr(PathService, "_instance", None)


def _codex_profile(model_id: str, model: str) -> dict[str, Any]:
    return {
        "id": CODEX_PROFILE,
        "name": "OpenAI Codex",
        "binding": "openai_codex",
        "api_key": "",
        "owner_bound": True,
        "read_only": True,
        "managed_by": "openai_codex_oauth",
        "models": [{"id": model_id, "name": model_id, "model": model}],
    }


def _copilot_profile() -> dict[str, Any]:
    return {
        "id": COPILOT_PROFILE,
        "name": "Copilot",
        "binding": "github_copilot",
        "owner_bound": True,
        "models": [{"id": "m-cop", "name": "Copilot model", "model": "gpt-cop"}],
    }


def _write_catalog(path, profiles: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "services": {"llm": {"profiles": profiles}}}),
        encoding="utf-8",
    )


def _catalog(profiles: list[Any]) -> dict[str, Any]:
    return {"services": {"llm": {"profiles": profiles}}}


def _sign_in(as_user, uid: str, profiles: list[dict[str, Any]]) -> None:
    with as_user(uid):
        _write_catalog(personal_models.owner_catalog_service().path, profiles)


# ---------------------------------------------------------------------------
# owner_catalog_service: which account's file each scope resolves to
# ---------------------------------------------------------------------------


def test_user_scope_resolves_its_own_catalog_file(mu_isolated_root, as_user):
    with as_user("u_alice"):
        path = personal_models.owner_catalog_service().path
    assert path.name == "model_catalog.json"
    assert path.is_relative_to((mu_isolated_root / "data" / "users" / "u_alice").resolve())


def test_admin_scope_resolves_the_shared_catalog_file(mu_isolated_root, as_user):
    with as_user("root", role="admin"):
        admin_path = personal_models.owner_catalog_service().path
    with as_user("u_alice"):
        user_path = personal_models.owner_catalog_service().path

    assert admin_path == (
        mu_isolated_root / "data" / "user" / "settings" / "model_catalog.json"
    ).resolve()
    assert admin_path != user_path


def test_no_request_scope_resolves_the_shared_catalog_like_an_administrator(
    mu_isolated_root,
    as_user,
):
    """CLI runs and background jobs act as the deployment, not as any user."""
    background_path = personal_models.owner_catalog_service().path
    with as_user("root", role="admin"):
        admin_path = personal_models.owner_catalog_service().path

    assert background_path == admin_path


def test_partner_scope_resolves_the_owners_catalog_never_a_partner_file(
    mu_isolated_root,
    as_user,
):
    """A partner owns no account: an owner-keyed asset belongs to the human
    whose workspace the partner lives in."""
    from deeptutor.multi_user.paths import get_admin_path_service
    from deeptutor.services.partners.scope import partner_user

    token_path = None
    from deeptutor.multi_user.context import (
        reset_current_user,
        set_current_user,
    )

    token = set_current_user(partner_user("ada"))
    try:
        token_path = personal_models.owner_catalog_service().path
    finally:
        reset_current_user(token)

    assert token_path == get_admin_path_service().get_settings_file("model_catalog")
    assert "partners" not in token_path.parts


# ---------------------------------------------------------------------------
# _personal_catalog_profiles: the account filter
# ---------------------------------------------------------------------------


def test_personal_profiles_are_empty_without_a_scope_and_for_administrators(as_user):
    catalog_profiles = [_codex_profile("m-sol", "gpt-5.6-sol")]
    _sign_in(as_user, "u_alice", catalog_profiles)

    assert personal_models.personal_llm_rows() == []
    with as_user("root", role="admin"):
        assert personal_models.personal_llm_rows() == []


def test_missing_catalog_file_surfaces_nothing_and_writes_nothing(as_user):
    with as_user("u_alice"):
        path = personal_models.owner_catalog_service().path
        assert personal_models.personal_llm_rows() == []
        assert not path.exists()


def test_only_owner_bound_profiles_surface_from_the_personal_catalog(as_user):
    profiles: list[Any] = [
        {
            "id": "llm-profile-team",
            "name": "Team key",
            "binding": "openai",
            "models": [{"id": "m-team", "name": "Team", "model": "gpt-team"}],
        },
        _codex_profile("m-sol", "gpt-5.6-sol"),
        _copilot_profile(),
    ]
    _sign_in(as_user, "u_alice", profiles)

    with as_user("u_alice"):
        rows = personal_models.personal_llm_rows()

    assert {(r["profile_id"], r["model_id"]) for r in rows} == {
        (CODEX_PROFILE, "m-sol"),
        (COPILOT_PROFILE, "m-cop"),
    }


def test_stale_codex_profile_is_dropped_while_other_owner_bound_profiles_remain(
    as_user,
    monkeypatch,
):
    _sign_in(as_user, "u_alice", [_codex_profile("m-sol", "gpt-5.6-sol"), _copilot_profile()])
    monkeypatch.setattr(
        personal_models,
        "_codex_profile_is_current",
        lambda _profile: False,
    )

    with as_user("u_alice"):
        rows = personal_models.personal_llm_rows()

    assert [(r["profile_id"], r["model_id"]) for r in rows] == [(COPILOT_PROFILE, "m-cop")]


def test_codex_auth_service_failure_degrades_to_stale(as_user, monkeypatch):
    """The real currency check swallows every failure: an unavailable auth
    service must hide the profile, never crash the options request."""
    import deeptutor.services.codex_auth as codex_auth

    def _unavailable() -> Any:
        raise RuntimeError("codex auth backend unavailable")

    monkeypatch.setattr(codex_auth, "get_codex_oauth_service", _unavailable)
    monkeypatch.setattr(personal_models, "_codex_profile_is_current", REAL_CURRENCY_CHECK)

    _sign_in(as_user, "u_alice", [_codex_profile("m-sol", "gpt-5.6-sol")])
    with as_user("u_alice"):
        assert personal_models.personal_llm_rows() == []


# ---------------------------------------------------------------------------
# personal_llm_rows: the row shape
# ---------------------------------------------------------------------------


# NOTE: entries below are written to a real catalog file, so they must stay
# loadable — the catalog normalizer fills or rejects malformed shapes before
# the row builder sees them. An explicit empty name/id is what survives
# loading and exercises the row builder's own fallback/skip branches.
def _rich_profile() -> dict[str, Any]:
    return {
        "id": "llm-profile-mine",
        "binding": "github_copilot",
        "owner_bound": True,
        "models": [
            {
                "id": "m-full",
                "name": "Full Model",
                "model": "gpt-full",
                "reasoning_effort": "high",
                "codex_supported_reasoning_levels": ["low", "high"],
                "capabilities": {
                    "reasoning": True,
                    "vision": False,
                    "tools": "yes",
                    "audio": 1,
                },
            },
            {"id": "m-bare", "name": ""},
            {"id": "", "name": "id-less"},
        ],
    }


def test_row_shape_passthrough_fallbacks_and_bool_only_capabilities(as_user):
    _sign_in(as_user, "u_alice", [_rich_profile()])

    with as_user("u_alice"):
        rows = personal_models.personal_llm_rows()

    assert [r["model_id"] for r in rows] == ["m-full", "m-bare"]
    full, bare = rows
    assert full == {
        "profile_id": "llm-profile-mine",
        "model_id": "m-full",
        "name": "Full Model",
        "model": "gpt-full",
        "provider": "github_copilot",
        "reasoning_effort": "high",
        "supported_reasoning_efforts": ["low", "high"],
        "declared_reasoning": True,
        "declared_vision": False,
        "source": "personal",
        "available": True,
    }
    assert bare["name"] == "m-bare"
    assert bare["model"] == ""
    assert bare["provider"] == "github_copilot"
    assert bare["reasoning_effort"] is None
    assert bare["supported_reasoning_efforts"] is None
    assert "declared_reasoning" not in bare
    assert "declared_vision" not in bare


# ---------------------------------------------------------------------------
# merge_personal_llm_profiles: priority, order, and immutability
# ---------------------------------------------------------------------------


def test_merge_returns_the_input_object_when_there_is_nothing_personal(as_user):
    shared = {"id": "llm-profile-team", "models": [{"id": "m-team"}]}
    catalog = _catalog([shared])

    assert personal_models.merge_personal_llm_profiles(catalog) is catalog
    with as_user("u_alice"):
        assert personal_models.merge_personal_llm_profiles(catalog) is catalog


def test_merge_for_another_account_is_unaffected_by_someone_elses_sign_in(as_user):
    """Alice's sign-in lives in Alice's catalog only: Bob's resolution must
    not even look at it."""
    _sign_in(as_user, "u_alice", [_codex_profile("m-sol", "gpt-5.6-sol")])
    catalog = _catalog([{"id": "llm-profile-team", "models": [{"id": "m-team"}]}])

    with as_user("u_bob"):
        assert personal_models.merge_personal_llm_profiles(catalog) is catalog


def test_merge_replaces_same_id_shared_profile_and_keeps_the_rest_in_order(as_user):
    """A managed profile id is a per-provider constant, so the shared catalog
    can hold a same-id profile listing the administrator's models; inside the
    owner's scope the owner's own profile is the authority."""
    team = {"id": "llm-profile-team", "models": [{"id": "m-team"}]}
    admin_side_codex = _codex_profile("m-admin-only", "gpt-5.6-admin")
    catalog = _catalog([team, admin_side_codex, "not-a-dict"])
    _sign_in(as_user, "u_alice", [_codex_profile("m-sol", "gpt-5.6-sol"), _copilot_profile()])

    with as_user("u_alice"):
        merged = personal_models.merge_personal_llm_profiles(catalog)

    profiles = merged["services"]["llm"]["profiles"]
    assert [(p["id"] if isinstance(p, dict) else p) for p in profiles] == [
        "llm-profile-team",
        "not-a-dict",
        CODEX_PROFILE,
        COPILOT_PROFILE,
    ]
    assert [m["id"] for m in profiles[-2]["models"]] == ["m-sol"]


def test_merge_never_mutates_the_input_catalog(as_user):
    team = {"id": "llm-profile-team", "models": [{"id": "m-team"}]}
    catalog = _catalog([team, _codex_profile("m-admin-only", "gpt-5.6-admin")])
    snapshot = copy.deepcopy(catalog)
    _sign_in(as_user, "u_alice", [_codex_profile("m-sol", "gpt-5.6-sol")])

    with as_user("u_alice"):
        merged = personal_models.merge_personal_llm_profiles(catalog)

    assert merged is not catalog
    assert catalog == snapshot
    assert merged["services"] is not catalog["services"]
    assert merged["services"]["llm"] is not catalog["services"]["llm"]


def test_merge_into_a_catalog_without_llm_services_yields_personal_profiles(as_user):
    _sign_in(as_user, "u_alice", [_codex_profile("m-sol", "gpt-5.6-sol")])

    with as_user("u_alice"):
        merged = personal_models.merge_personal_llm_profiles({})

    assert [m["id"] for m in merged["services"]["llm"]["profiles"][0]["models"]] == ["m-sol"]


def test_administrator_merge_is_identity_even_when_their_catalog_is_owner_bound(
    as_user,
):
    """The admin's owner-bound profiles already live in the catalog they
    manage; overlaying them would duplicate every model, so the merge must
    leave their resolution path untouched."""
    with as_user("root", role="admin"):
        _write_catalog(
            personal_models.owner_catalog_service().path,
            [_codex_profile("m-admin", "gpt-5.6-admin")],
        )
    catalog = _catalog([_codex_profile("m-admin", "gpt-5.6-admin")])

    with as_user("root", role="admin"):
        assert personal_models.merge_personal_llm_profiles(catalog) is catalog
