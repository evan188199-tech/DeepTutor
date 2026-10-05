"""Decision-level tests for :mod:`deeptutor.multi_user.model_access`.

These exercise the module's own grant-resolution logic — the no-grant
default, grant hit/miss, invalid model ids, stale provider references and
selection validation — at function level. Route and dependency matrices are
covered elsewhere (test-permission-matrix, AGEN-483, AGEN-565).
"""

from __future__ import annotations

import pytest

from deeptutor.multi_user import model_access
from deeptutor.multi_user.models import CurrentUser, UserScope

PROFILE_ID = "p_shared"
MODEL_ID = "m1"
SECOND_MODEL_ID = "m2"
GHOST_MODEL_ID = "m_ghost"


def _catalog(*, active_model: str = MODEL_ID, model_provider_ref: dict | None = None) -> dict:
    model: dict = {
        "id": MODEL_ID,
        "name": "Shared One",
        "model": "vendor/shared-one",
        "reasoning_effort": "medium",
        "capabilities": {"reasoning": True, "vision": False, "tools": True},
    }
    if model_provider_ref is not None:
        model["provider_ref"] = model_provider_ref
    second = {
        "id": SECOND_MODEL_ID,
        "name": "Shared Two",
        "model": "vendor/shared-two",
    }
    return {
        "services": {
            "llm": {
                "active_profile_id": PROFILE_ID,
                "active_model_id": active_model,
                "profiles": [
                    {
                        "id": PROFILE_ID,
                        "name": "Shared",
                        "binding": "openai",
                        "models": [model, second],
                    }
                ],
            }
        }
    }


def _grant(*items: dict) -> dict:
    return {"models": {"llm": list(items)}}


def _patch_no_personal_models(monkeypatch) -> None:
    import deeptutor.multi_user.personal_models as personal_models

    monkeypatch.setattr(personal_models, "personal_llm_rows", lambda: [])


def test_no_grant_denies_llm_by_default(as_user, monkeypatch):
    """An account with no grant on disk has no models and may not select any."""
    _patch_no_personal_models(monkeypatch)
    monkeypatch.setattr(model_access, "admin_catalog", lambda: _catalog())
    with as_user("u_alice"):
        assert model_access.redacted_model_access()["llm"] == []
        assert model_access.allowed_llm_options() == {"active": None, "options": []}
        assert model_access.has_capability_access("llm") is False
        with pytest.raises(PermissionError):
            model_access.apply_allowed_llm_selection(
                {"profile_id": PROFILE_ID, "model_id": MODEL_ID}
            )


def test_granted_model_resolves_to_available_row(as_user, monkeypatch):
    monkeypatch.setattr(model_access, "admin_catalog", lambda: _catalog())
    monkeypatch.setattr(
        model_access,
        "load_grant",
        lambda _uid: _grant({"profile_id": PROFILE_ID, "model_ids": [MODEL_ID]}),
    )
    with as_user("u_alice"):
        rows = model_access.redacted_model_access()["llm"]
        assert len(rows) == 1
        row = rows[0]
        assert row["profile_id"] == PROFILE_ID
        assert row["model_id"] == MODEL_ID
        assert row["available"] is True
        assert row["source"] == "admin"
        assert row["name"] == "Shared One"
        assert row["model"] == "vendor/shared-one"
        assert row["provider"] == "openai"
        assert row["profile_name"] == "Shared"
        assert row["reasoning_effort"] == "medium"
        # Only boolean reasoning/vision capabilities are declared forward.
        assert row["declared_reasoning"] is True
        assert row["declared_vision"] is False
        assert "declared_tools" not in row
        assert model_access.has_capability_access("llm") is True


def test_grant_referencing_missing_profile_reports_unavailable(as_user, monkeypatch):
    """A grant pointing at a profile no longer in the catalog stays visible."""
    monkeypatch.setattr(model_access, "admin_catalog", lambda: _catalog())
    monkeypatch.setattr(
        model_access,
        "load_grant",
        lambda _uid: _grant(
            {"profile_id": "p_gone", "name": "Old Profile", "model_ids": [MODEL_ID]}
        ),
    )
    with as_user("u_alice"):
        rows = model_access.redacted_model_access()["llm"]
        assert rows == [
            {
                "profile_id": "p_gone",
                "name": "Old Profile",
                "source": "admin",
                "available": False,
            }
        ]
        assert "model_id" not in rows[0]
        assert model_access.has_capability_access("llm") is False


def test_unnamed_missing_grant_falls_back_to_placeholder_name(as_user, monkeypatch):
    monkeypatch.setattr(model_access, "admin_catalog", lambda: _catalog())
    monkeypatch.setattr(
        model_access, "load_grant", lambda _uid: _grant({"profile_id": "", "model_ids": []})
    )
    with as_user("u_alice"):
        rows = model_access.redacted_model_access()["llm"]
        assert rows[0]["name"] == "Unavailable profile"
        assert rows[0]["available"] is False


def test_unknown_model_id_in_grant_is_marked_unavailable(as_user, monkeypatch):
    """Valid models resolve; an id missing from the profile degrades its row."""
    monkeypatch.setattr(model_access, "admin_catalog", lambda: _catalog())
    monkeypatch.setattr(
        model_access,
        "load_grant",
        lambda _uid: _grant({"profile_id": PROFILE_ID, "model_ids": [MODEL_ID, GHOST_MODEL_ID]}),
    )
    with as_user("u_alice"):
        rows = model_access.redacted_model_access()["llm"]
        assert [row["available"] for row in rows] == [True, False]
        ghost = rows[1]
        assert ghost["model_id"] == GHOST_MODEL_ID
        assert ghost["name"] == GHOST_MODEL_ID
        assert ghost["model"] == ""
        assert model_access.has_capability_access("llm") is True


def test_stale_provider_reference_drops_the_row(as_user, monkeypatch):
    """A model whose provider_ref no longer resolves is silently withheld."""
    monkeypatch.setattr(
        model_access,
        "admin_catalog",
        lambda: _catalog(model_provider_ref={"connection_id": "ghost-conn"}),
    )
    monkeypatch.setattr(
        model_access,
        "load_grant",
        lambda _uid: _grant({"profile_id": PROFILE_ID, "model_ids": [MODEL_ID]}),
    )
    with as_user("u_alice"):
        assert model_access.redacted_model_access()["llm"] == []
        assert model_access.has_capability_access("llm") is False


def test_personal_models_attach_only_to_the_caller(as_user, monkeypatch):
    """Inspecting another user's grant never leaks the caller's personal rows."""
    import deeptutor.multi_user.personal_models as personal_models

    personal_row = {
        "profile_id": "p_personal",
        "model_id": "mp",
        "available": True,
        "source": "personal",
    }
    monkeypatch.setattr(personal_models, "personal_llm_rows", lambda: [personal_row])
    monkeypatch.setattr(model_access, "admin_catalog", lambda: _catalog())

    def fake_grant(user_id: str) -> dict:
        if user_id == "u_bob":
            return _grant({"profile_id": PROFILE_ID, "model_ids": [MODEL_ID]})
        return _grant()

    monkeypatch.setattr(model_access, "load_grant", fake_grant)
    with as_user("u_alice"):
        assert model_access.redacted_model_access()["llm"] == [personal_row]

        bob_rows = model_access.redacted_model_access("u_bob")["llm"]
        assert [row["profile_id"] for row in bob_rows] == [PROFILE_ID]
        assert bob_rows[0]["source"] == "admin"
        assert bob_rows[0]["available"] is True


def test_selection_of_unassigned_model_is_rejected(as_user, monkeypatch):
    _patch_no_personal_models(monkeypatch)
    monkeypatch.setattr(model_access, "admin_catalog", lambda: _catalog())
    monkeypatch.setattr(
        model_access,
        "load_grant",
        lambda _uid: _grant({"profile_id": PROFILE_ID, "model_ids": [MODEL_ID]}),
    )
    selection = {"profile_id": PROFILE_ID, "model_id": MODEL_ID}
    with as_user("u_alice"):
        assert model_access.apply_allowed_llm_selection(dict(selection)) == selection
        with pytest.raises(PermissionError):
            model_access.apply_allowed_llm_selection(
                {"profile_id": PROFILE_ID, "model_id": GHOST_MODEL_ID}
            )
        with pytest.raises(PermissionError):
            model_access.apply_allowed_llm_selection({"profile_id": "p_gone", "model_id": MODEL_ID})


def test_selection_validation_skipped_for_admins_and_blank(as_user, monkeypatch):
    def _boom(_user_id=None):
        raise AssertionError("redacted_model_access should not be consulted")

    monkeypatch.setattr(model_access, "redacted_model_access", _boom)
    with as_user("u_admin", role="admin"):
        ghost = {"profile_id": PROFILE_ID, "model_id": GHOST_MODEL_ID}
        assert model_access.apply_allowed_llm_selection(ghost) == ghost
    with as_user("u_alice"):
        assert model_access.apply_allowed_llm_selection(None) is None
        assert model_access.apply_allowed_llm_selection({}) == {}


def test_active_default_flags_only_the_deployment_active_model(as_user, monkeypatch):
    _patch_no_personal_models(monkeypatch)
    monkeypatch.setattr(
        model_access,
        "load_grant",
        lambda _uid: _grant({"profile_id": PROFILE_ID, "model_ids": [MODEL_ID, SECOND_MODEL_ID]}),
    )

    def _options(active_model: str) -> dict:
        monkeypatch.setattr(
            model_access, "admin_catalog", lambda: _catalog(active_model=active_model)
        )
        return model_access.allowed_llm_options()

    with as_user("u_alice"):
        options = _options(MODEL_ID)
        flags = {o["model_id"]: o["is_active_default"] for o in options["options"]}
        assert flags == {MODEL_ID: True, SECOND_MODEL_ID: False}
        assert options["active"] == {"profile_id": PROFILE_ID, "model_id": MODEL_ID}

        options = _options(SECOND_MODEL_ID)
        flags = {o["model_id"]: o["is_active_default"] for o in options["options"]}
        assert flags == {MODEL_ID: False, SECOND_MODEL_ID: True}
        assert options["active"] == {"profile_id": PROFILE_ID, "model_id": SECOND_MODEL_ID}


def test_capability_gate_targets_the_requested_user(as_user, monkeypatch):
    requested: list[str] = []

    def fake_access(user_id=None):
        requested.append(user_id)
        if user_id == "u_bob":
            return {"llm": [{"profile_id": PROFILE_ID, "model_id": MODEL_ID, "available": True}]}
        return {"llm": []}

    monkeypatch.setattr(model_access, "redacted_model_access", fake_access)
    with as_user("u_alice"):
        assert model_access.has_capability_access("llm") is False
        assert model_access.has_capability_access("llm", user_id="u_bob") is True
        assert requested == ["u_alice", "u_bob"]
