"""Service-level skill gating: default-policy branches of ``skill_access``.

Complements ``test_skill_resolution_scoped.py`` (admin-workspace routing) by
pinning the unconfigured-user default, id-fallback/malformed-entry filtering,
annotation contract, degradation branches, and the per-name scope of the 403
guard. Dedup: the route-level matrix lives in the permission-matrix suite and
partner-resource checks in the partner-access suite.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from deeptutor.multi_user import grants as grants_mod
from deeptutor.multi_user import skill_access
from deeptutor.multi_user.skill_access import (
    assert_skill_allowed,
    assigned_skill_detail,
    assigned_skill_ids,
    assigned_skill_infos,
)


def _write_skill(workspace_dir, name: str, body: str) -> None:
    skill_dir = workspace_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test skill\n---\n\n{body}\n"
    )


def _write_grant_skills(uid: str, entries: list[dict]) -> None:
    grant = grants_mod.empty_grant(uid)
    grant["skills"] = entries
    path = grants_mod.grant_path(uid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(__import__("json").dumps(grant), encoding="utf-8")


def _grant_skills(uid: str, names: list[str]) -> None:
    _write_grant_skills(
        uid, [{"skill_id": n, "access": "use", "source": "admin"} for n in names]
    )


def _admin_skills_root(mu_isolated_root):
    return (mu_isolated_root / "data" / "user" / "workspace" / "skills").resolve()


# ── unconfigured accounts ────────────────────────────────────────────────────


def test_unconfigured_user_has_no_assigned_skills(mu_isolated_root, as_user, monkeypatch):
    def _no_service():
        raise AssertionError("admin skill service must not be consulted without grants")

    monkeypatch.setattr(skill_access, "_admin_skill_service", _no_service)
    with as_user("u_alice"):
        assert assigned_skill_ids() == set()
        assert assigned_skill_infos() == []


def test_assigned_skill_ids_follow_explicit_user_id_over_context(
    mu_isolated_root, as_user
):
    _grant_skills("u_bob", ["granted-skill"])
    with as_user("u_admin", role="admin"):
        # An explicit user id reads that account's grant, not the caller's.
        assert assigned_skill_ids("u_bob") == {"granted-skill"}
        assert assigned_skill_ids() == set()


# ── grant entry normalization at the accessor level ──────────────────────────


def test_assigned_skill_ids_skip_malformed_and_blank_entries(mu_isolated_root, as_user):
    _write_grant_skills(
        "u_alice",
        [
            {},
            {"skill_id": ""},
            {"id": "   "},
            {"id": "legacy-named"},
            {"skill_id": "proper-id"},
        ],
    )
    with as_user("u_alice"):
        assert assigned_skill_ids() == {"legacy-named", "proper-id"}


# ── assigned skill catalog projection ────────────────────────────────────────


def test_assigned_skill_infos_only_assigned_and_annotated(mu_isolated_root, as_user):
    root = _admin_skills_root(mu_isolated_root)
    _write_skill(root, "alpha-skill", "Alpha body.")
    _write_skill(root, "beta-skill", "Beta body.")
    _grant_skills("u_alice", ["alpha-skill"])

    with as_user("u_alice"):
        infos = assigned_skill_infos()
    assert [i["name"] for i in infos] == ["alpha-skill"]
    entry = infos[0]
    assert entry["source"] == "admin"
    assert entry["assigned"] is True
    assert entry["read_only"] is True


def test_assigned_skill_detail_unknown_skill_returns_none(mu_isolated_root):
    # get_detail raises SkillNotFoundError for a missing name; the guard must
    # degrade to None instead of leaking the exception to the router.
    assert assigned_skill_detail("no-such-skill") is None


def test_assigned_skill_detail_service_error_returns_none(monkeypatch):
    def _broken():
        raise RuntimeError("skill store unavailable")

    monkeypatch.setattr(skill_access, "_admin_skill_service", _broken)
    assert assigned_skill_detail("any-skill") is None


# ── 403 guard ────────────────────────────────────────────────────────────────


def test_assert_skill_allowed_passes_for_assigned_skill(mu_isolated_root, as_user):
    _grant_skills("u_alice", ["my-skill"])
    with as_user("u_alice"):
        assert_skill_allowed("my-skill")


def test_assert_skill_allowed_403_for_skill_not_in_nonempty_grant(
    mu_isolated_root, as_user
):
    # A non-empty grant does not broaden access: assignment is per-name.
    _grant_skills("u_alice", ["other-skill"])
    with as_user("u_alice"):
        with pytest.raises(HTTPException) as exc:
            assert_skill_allowed("wanted-skill")
    assert exc.value.status_code == 403
