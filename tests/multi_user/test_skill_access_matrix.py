"""Access-decision matrix for ``skill_access`` (grant shape × role).

Table-driven behavior contract for which skill references a role may use: what
a grant entry may look like, what malformed entries do, how the assigned-info
projection filters the admin catalog, and when a read raises. The admin-scope
storage routing itself is covered by ``test_skill_resolution_scoped``.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import HTTPException
import pytest

from deeptutor.multi_user import grants as grants_mod
from deeptutor.multi_user.skill_access import (
    assert_skill_allowed,
    assigned_skill_detail,
    assigned_skill_ids,
    assigned_skill_infos,
)

SKILL = "research-mode"


def _write_skill(root: Path, name: str, body: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test skill\n---\n\n{body}\n"
    )


def _grant_skills(uid: str, entries: list) -> None:
    grant = grants_mod.empty_grant(uid)
    grant["skills"] = entries
    path = grants_mod.grant_path(uid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(grant), encoding="utf-8")


@pytest.fixture
def admin_catalog(mu_isolated_root):
    """Two skills in the admin workspace catalog."""
    root = (mu_isolated_root / "data" / "user" / "workspace" / "skills").resolve()
    _write_skill(root, SKILL, "Use citations.")
    _write_skill(root, "other-skill", "Other body.")
    return root


ID_SHAPE_ROWS = [
    ("skill_id key", [{"skill_id": SKILL}]),
    ("id key", [{"id": SKILL}]),
    ("whitespace stripped", [{"skill_id": f"  {SKILL}  "}]),
    ("access field ignored", [{"skill_id": SKILL, "access": "view-only"}]),
]


@pytest.mark.parametrize(("label", "entries"), ID_SHAPE_ROWS, ids=[row[0] for row in ID_SHAPE_ROWS])
def test_grant_entry_shapes_grant_access(admin_catalog, as_user, label, entries):
    _grant_skills("u_alice", entries)

    with as_user("u_alice", role="user"):
        assert assigned_skill_ids() == {SKILL}
        assert_skill_allowed(SKILL)


def test_malformed_entries_are_dropped(admin_catalog, as_user):
    _grant_skills("u_alice", [{}, "junk", 7, {"skill_id": ""}, {"id": "   "}, {"skill_id": SKILL}])

    with as_user("u_alice", role="user"):
        assert assigned_skill_ids() == {SKILL}


def test_explicit_user_id_reads_that_grant_not_the_callers(admin_catalog, as_user):
    _grant_skills("u_alice", [{"skill_id": SKILL}])

    with as_user("u_bob", role="user"):
        assert assigned_skill_ids("u_alice") == {SKILL}
        # The caller's own grant is still the one enforced for reads.
        with pytest.raises(HTTPException) as exc:
            assert_skill_allowed(SKILL)
    assert exc.value.status_code == 403


def test_empty_grant_short_circuits_before_the_admin_catalog(admin_catalog, as_user, monkeypatch):
    def _explode():
        raise AssertionError("admin catalog must not be read for an empty grant")

    monkeypatch.setattr("deeptutor.multi_user.skill_access._admin_skill_service", _explode)

    with as_user("u_alice", role="user"):
        assert assigned_skill_infos() == []


def test_assigned_infos_filter_the_admin_catalog(admin_catalog, as_user):
    _grant_skills("u_alice", [{"skill_id": SKILL}])

    with as_user("u_alice", role="user"):
        infos = assigned_skill_infos()

    assert [info["name"] for info in infos] == [SKILL]
    entry = infos[0]
    assert (entry["source"], entry["assigned"], entry["read_only"]) == ("admin", True, True)


def test_assigned_detail_contract(admin_catalog, as_user):
    _grant_skills("u_alice", [{"skill_id": SKILL}])

    with as_user("u_alice", role="user"):
        detail = assigned_skill_detail(SKILL)
        assert detail is not None
        assert "Use citations." in detail["content"]
        assert (detail["source"], detail["assigned"], detail["read_only"]) == ("admin", True, True)

        # A granted id with no backing catalog entry yields no detail.
        assert assigned_skill_detail("vanished-skill") is None


ALLOW_ROWS = [
    ("admin passes any name", "admin", SKILL, True),
    ("admin passes unknown name", "admin", "anything", True),
    ("granted skill allowed", "user", SKILL, True),
    ("ungranted skill denied", "user", "other-skill", False),
]


@pytest.mark.parametrize(
    ("label", "role", "name", "allowed"), ALLOW_ROWS, ids=[row[0] for row in ALLOW_ROWS]
)
def test_assert_skill_allowed_matrix(admin_catalog, as_user, label, role, name, allowed):
    _grant_skills("u_alice", [{"skill_id": SKILL}])

    with as_user("u_alice", role=role):
        if allowed:
            assert_skill_allowed(name)
        else:
            with pytest.raises(HTTPException) as exc:
                assert_skill_allowed(name)
    if not allowed:
        assert exc.value.status_code == 403
