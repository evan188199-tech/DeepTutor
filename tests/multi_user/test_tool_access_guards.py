"""Service-level tool/exec gating: default-policy branches of ``tool_access``.

Complements ``test_tool_access.py`` (normalization + happy-path resolution) by
pinning the deny-by-default posture for MCP tools and CLI apps, the
explicit-empty whitelist edge, and the failure branch when stored grant data
cannot be read. Dedup: the route-level matrix lives in the permission-matrix
suite; this file only exercises the service accessors.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.multi_user import grants as grants_mod
from deeptutor.multi_user.grants import GrantStorageError, save_grant
from deeptutor.multi_user.tool_access import (
    allowed_cli_apps,
    allowed_mcp_tools,
    allowed_optional_tools,
    combine_whitelists,
    exec_override,
)


def _write_raw_grant(uid: str, payload: dict) -> None:
    """Write a grant file bypassing save_grant normalization."""
    path = grants_mod.grant_path(uid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


# ── cli_apps: deny-by-default for every non-admin account ────────────────────


def test_cli_apps_unconfigured_user_denied_by_default(as_user, mu_isolated_root):
    with as_user("u_alice"):
        assert allowed_cli_apps() == set()
        # Contrast: built-in optional tools still follow defaults.
        assert allowed_optional_tools() is None


def test_cli_apps_admin_unrestricted(as_user, mu_isolated_root):
    _write_raw_grant("u_alice", {"cli_apps": ["codex"]})
    with as_user("u_admin", role="admin"):
        assert allowed_cli_apps() is None


def test_cli_apps_explicit_empty_whitelist_denies_all(as_user, grantable_user):
    save_grant(grantable_user, {"cli_apps": []})
    with as_user(grantable_user):
        assert allowed_cli_apps() == set()


def test_cli_apps_whitelist_resolves_from_grant(as_user, grantable_user):
    save_grant(grantable_user, {"cli_apps": ["codex", "claude"]})
    with as_user(grantable_user):
        assert allowed_cli_apps() == {"codex", "claude"}


# ── exec_override: tri-state on top of the deployment policy ─────────────────


def test_exec_override_true_grant_honored(as_user, grantable_user):
    save_grant(grantable_user, {"exec_enabled": True})
    with as_user(grantable_user):
        assert exec_override() is True


def test_exec_override_absent_follows_deployment_policy(as_user, grantable_user):
    save_grant(grantable_user, {"enabled_tools": ["reason"]})
    with as_user(grantable_user):
        assert exec_override() is None


def test_exec_override_non_bool_value_follows_policy(as_user, monkeypatch):
    # Defense-in-depth: any non-bool grant value resolves to "follow policy"
    # instead of being truthy-coerced into an enable.
    from deeptutor.multi_user import tool_access

    monkeypatch.setattr(
        tool_access, "load_grant", lambda _uid: {"exec_enabled": "yes", "user_id": "u_alice"}
    )
    with as_user("u_alice"):
        assert tool_access.exec_override() is None


# ── default-policy branches for tool whitelists ──────────────────────────────


def test_mcp_explicit_empty_whitelist_denies_all(as_user, grantable_user):
    save_grant(grantable_user, {"mcp_tools": []})
    with as_user(grantable_user):
        assert allowed_mcp_tools() == set()


def test_optional_tools_explicit_empty_whitelist_denies_all(as_user, grantable_user):
    save_grant(grantable_user, {"enabled_tools": []})
    with as_user(grantable_user):
        assert allowed_optional_tools() == set()


def test_optional_tools_grant_strips_whitespace_entries(as_user, grantable_user):
    save_grant(grantable_user, {"enabled_tools": [" reason ", "", "web_search"]})
    with as_user(grantable_user):
        assert allowed_optional_tools() == {"reason", "web_search"}


def test_unreadable_grant_fails_closed_with_storage_error(as_user, mu_isolated_root):
    path = grants_mod.grant_path("u_broken")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    with as_user("u_broken"):
        with pytest.raises(GrantStorageError):
            allowed_optional_tools()
        with pytest.raises(GrantStorageError):
            allowed_mcp_tools()


def test_combine_whitelists_empty_sets_intersect_to_empty():
    assert combine_whitelists(set(), set()) == set()
    assert combine_whitelists(None, set()) == set()
    assert combine_whitelists(set(), None) == set()


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def grantable_user(mu_isolated_root, monkeypatch):
    """Make ``save_grant`` accept u_bob without a real identity record."""
    monkeypatch.setattr(
        grants_mod,
        "get_user_by_id",
        lambda user_id: ("bob", {"role": "user"}) if user_id == "u_bob" else None,
    )
    return "u_bob"
