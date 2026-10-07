"""Module-level behavior tests for the guardian authorization store.

``tests/multi_user/test_guardians.py`` exercises the HTTP surface; this file
pins the decision rules of ``deeptutor.multi_user.guardians`` itself: which
accounts may be linked, how permissions are canonicalized, how revocation and
access checks behave, and how a corrupted store file is tolerated.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.multi_user import guardians
from deeptutor.multi_user.identity import save_user, set_preset
from deeptutor.services.auth import hash_password

MISSING_USER_ID = "u_does_not_exist"


@pytest.fixture
def users(mu_isolated_root):
    """Seed an admin, two standard guardians and two learner accounts."""
    admin = save_user("root-admin", hash_password("admin-password"), role="admin")
    guardian = save_user("guardian-a", hash_password("guardian-password"))
    guardian_b = save_user("guardian-b", hash_password("guardian-password"))
    learner = save_user("learner-a", hash_password("learner-password"), preset="learner")
    learner_b = save_user("learner-b", hash_password("learner-password"), preset="learner")
    return {
        "admin": admin,
        "guardian": guardian,
        "guardian_b": guardian_b,
        "learner": learner,
        "learner_b": learner_b,
    }


def _authorize(guardian_id: str, learner_id: str, permissions=("view_reports",)):
    return guardians.authorize_guardian(guardian_id, learner_id, list(permissions))


def _write_store(records) -> None:
    guardians.GUARDIANS_FILE.parent.mkdir(parents=True, exist_ok=True)
    guardians.GUARDIANS_FILE.write_text(json.dumps(records), encoding="utf-8")


@pytest.mark.parametrize(
    ("guardian_key", "learner_key", "permissions", "expected_error"),
    [
        pytest.param(
            "missing",
            "learner",
            ["view_reports"],
            "Unknown guardian user id",
            id="unknown_guardian_user",
        ),
        pytest.param(
            "guardian",
            "missing",
            ["view_reports"],
            "Unknown learner user id",
            id="unknown_learner_user",
        ),
        pytest.param(
            "admin",
            "learner",
            ["view_reports"],
            "Admin users cannot be guardians",
            id="admin_account_as_guardian",
        ),
        pytest.param(
            "guardian",
            "admin",
            ["view_reports"],
            "Admin users cannot be learners",
            id="admin_account_as_learner",
        ),
        pytest.param(
            "learner",
            "learner_b",
            ["view_reports"],
            "Learner accounts cannot be guardians",
            id="learner_preset_account_as_guardian",
        ),
        pytest.param(
            "guardian",
            "guardian_b",
            ["view_reports"],
            "requires a learner account",
            id="non_learner_target",
        ),
        pytest.param(
            "guardian",
            "learner",
            [],
            "At least one guardian permission is required",
            id="empty_permissions",
        ),
        pytest.param(
            "guardian",
            "learner",
            ["not_a_real_permission"],
            "At least one guardian permission is required",
            id="unknown_permissions_only",
        ),
        pytest.param(
            "guardian",
            "learner",
            "view_reports",
            "At least one guardian permission is required",
            id="string_permissions_rejected",
        ),
    ],
)
def test_authorize_guardian_rejection_table(
    users, guardian_key, learner_key, permissions, expected_error
):
    guardian_id = (
        MISSING_USER_ID if guardian_key == "missing" else users[guardian_key]["id"]
    )
    learner_id = MISSING_USER_ID if learner_key == "missing" else users[learner_key]["id"]

    with pytest.raises(ValueError, match=expected_error):
        guardians.authorize_guardian(guardian_id, learner_id, permissions)

    assert guardians.list_relationships(include_revoked=True) == []


def test_authorize_guardian_rejects_duplicate_but_allows_regrant_after_revocation(users):
    first = _authorize(users["guardian"]["id"], users["learner"]["id"])
    assert first["revoked_at"] is None

    with pytest.raises(ValueError, match="already authorized"):
        _authorize(users["guardian"]["id"], users["learner"]["id"])

    guardians.revoke_guardian(first["id"], revoked_by="admin", reason="rekey")
    replacement = _authorize(users["guardian"]["id"], users["learner"]["id"])

    active = guardians.list_relationships()
    assert [record["id"] for record in active] == [replacement["id"]]
    history = guardians.list_relationships(include_revoked=True)
    assert {record["id"] for record in history} == {first["id"], replacement["id"]}
    assert next(r for r in history if r["id"] == first["id"])["revoked_at"] is not None


def test_authorize_guardian_rejects_reciprocal_pair(users):
    _write_store(
        [
            {
                "id": "ga_reciprocal",
                "guardian_user_id": users["learner"]["id"],
                "learner_user_id": users["guardian"]["id"],
                "permissions": ["view_reports"],
                "granted_at": "2026-01-01T00:00:00+00:00",
                "revoked_at": None,
                "revoked_by": "",
                "revocation_reason": "",
            }
        ]
    )

    with pytest.raises(ValueError, match="cannot guard their active guardian"):
        _authorize(users["guardian"]["id"], users["learner"]["id"])

    assert [record["id"] for record in guardians.list_relationships()] == ["ga_reciprocal"]


def test_authorize_guardian_canonicalizes_permissions_and_returns_detached_copy(users):
    record = _authorize(
        users["guardian"]["id"],
        users["learner"]["id"],
        ("assign_materials", "view_reports", "not_a_real_permission"),
    )

    assert record["guardian_user_id"] == users["guardian"]["id"]
    assert record["learner_user_id"] == users["learner"]["id"]
    assert record["permissions"] == ["assign_materials", "view_reports"]
    assert record["granted_at"]
    assert record["revoked_at"] is None
    assert record["revoked_by"] == ""
    assert record["revocation_reason"] == ""

    record["permissions"].append("reset_credentials")
    stored = guardians.relationship_by_id(record["id"])
    assert stored["permissions"] == ["assign_materials", "view_reports"]


@pytest.mark.parametrize(
    ("scenario", "permission", "expected"),
    [
        pytest.param("none", "view_reports", True, id="granted_permission_allowed"),
        pytest.param("none", "assign_materials", False, id="ungranted_permission_denied"),
        pytest.param("revoke", "view_reports", False, id="revoked_relationship_denied"),
        pytest.param(
            "learner_to_standard", "view_reports", False, id="former_learner_denied"
        ),
        pytest.param(
            "guardian_to_learner", "view_reports", False, id="guardian_turned_learner_denied"
        ),
        pytest.param(
            "guardian_to_admin", "view_reports", False, id="guardian_promoted_admin_denied"
        ),
        pytest.param("swap_ids", "view_reports", False, id="reversed_pair_denied"),
        pytest.param("unknown_guardian", "view_reports", False, id="unknown_guardian_denied"),
        pytest.param("unknown_learner", "view_reports", False, id="unknown_learner_denied"),
    ],
)
def test_guardian_can_access_decision_table(users, scenario, permission, expected):
    guardian_id = users["guardian"]["id"]
    learner_id = users["learner"]["id"]
    relationship = _authorize(guardian_id, learner_id, ("view_reports",))

    if scenario == "revoke":
        guardians.revoke_guardian(
            relationship["id"], revoked_by="admin", reason="season_over"
        )
    elif scenario == "learner_to_standard":
        assert set_preset("learner-a", "standard") is True
    elif scenario == "guardian_to_learner":
        assert set_preset("guardian-a", "learner") is True
    elif scenario == "guardian_to_admin":
        promoted = save_user(
            "guardian-a", hash_password("guardian-password"), role="admin"
        )
        assert promoted["role"] == "admin"
    elif scenario == "swap_ids":
        guardian_id, learner_id = learner_id, guardian_id
    elif scenario == "unknown_guardian":
        guardian_id = MISSING_USER_ID
    elif scenario == "unknown_learner":
        learner_id = MISSING_USER_ID

    assert (
        guardians.guardian_can_access(guardian_id, learner_id, permission) is expected
    )


def test_revoke_guardian_records_actor_and_is_idempotent(users):
    relationship = _authorize(users["guardian"]["id"], users["learner"]["id"])

    assert guardians.revoke_guardian("ga_missing", revoked_by="admin", reason="n/a") is None

    revoked = guardians.revoke_guardian(
        relationship["id"], revoked_by="admin", reason="school_request"
    )
    assert revoked["revoked_at"] is not None
    assert revoked["revoked_by"] == "admin"
    assert revoked["revocation_reason"] == "school_request"
    assert guardians.relationship_by_id(relationship["id"])["revoked_at"] == revoked[
        "revoked_at"
    ]

    repeated = guardians.revoke_guardian(
        relationship["id"], revoked_by="someone_else", reason="tamper"
    )
    assert repeated["revoked_at"] == revoked["revoked_at"]
    assert repeated["revoked_by"] == "admin"
    assert repeated["revocation_reason"] == "school_request"

    assert guardians.list_relationships() == []
    assert len(guardians.list_relationships(include_revoked=True)) == 1


def test_revoke_relationships_for_user_covers_both_roles_and_skips_revoked(users):
    as_guardian_a = _authorize(users["guardian"]["id"], users["learner"]["id"])
    as_guardian_b = _authorize(users["guardian"]["id"], users["learner_b"]["id"])
    other_pair = _authorize(users["guardian_b"]["id"], users["learner"]["id"])

    assert (
        guardians.revoke_relationships_for_user(
            users["guardian"]["id"], reason="account_removed"
        )
        == 2
    )
    assert [record["id"] for record in guardians.list_relationships()] == [other_pair["id"]]
    assert (
        guardians.revoke_relationships_for_user(
            users["guardian"]["id"], reason="account_removed"
        )
        == 0
    )

    assert (
        guardians.revoke_relationships_for_user(
            users["learner"]["id"], reason="account_removed"
        )
        == 1
    )
    assert guardians.list_relationships() == []

    history = guardians.list_relationships(include_revoked=True)
    assert {record["id"] for record in history} == {
        as_guardian_a["id"],
        as_guardian_b["id"],
        other_pair["id"],
    }
    assert all(record["revoked_by"] == "system" for record in history)
    assert all(record["revocation_reason"] == "account_removed" for record in history)


def test_list_relationships_filters_by_side_and_revocation_state(users):
    guardian_pair = _authorize(users["guardian"]["id"], users["learner"]["id"])
    guardian_b_pair = _authorize(users["guardian_b"]["id"], users["learner_b"]["id"])

    by_guardian = guardians.list_relationships(guardian_user_id=users["guardian"]["id"])
    assert [record["id"] for record in by_guardian] == [guardian_pair["id"]]
    by_learner = guardians.list_relationships(learner_user_id=users["learner_b"]["id"])
    assert [record["id"] for record in by_learner] == [guardian_b_pair["id"]]

    guardians.revoke_guardian(guardian_b_pair["id"], revoked_by="admin", reason="done")
    assert [record["id"] for record in guardians.list_relationships()] == [
        guardian_pair["id"]
    ]
    assert [
        record["id"]
        for record in guardians.list_relationships(
            guardian_user_id=users["guardian_b"]["id"], include_revoked=True
        )
    ] == [guardian_b_pair["id"]]


@pytest.mark.parametrize(
    ("raw",),
    [
        pytest.param("not json at all{", id="corrupt_json_yields_no_relationships"),
        pytest.param({"guardians": []}, id="non_list_document_yields_no_relationships"),
        pytest.param([], id="empty_list_yields_no_relationships"),
    ],
)
def test_store_tolerates_broken_files(users, raw):
    guardians.GUARDIANS_FILE.parent.mkdir(parents=True, exist_ok=True)
    guardians.GUARDIANS_FILE.write_text(
        raw if isinstance(raw, str) else json.dumps(raw), encoding="utf-8"
    )

    assert guardians.list_relationships(include_revoked=True) == []
    assert guardians.relationship_by_id("ga_any") is None


def test_store_canonicalization_drops_invalid_entries_and_keeps_first_duplicate(users):
    guardian_id = users["guardian"]["id"]
    learner_id = users["learner"]["id"]
    valid = {
        "id": "ga_valid",
        "guardian_user_id": guardian_id,
        "learner_user_id": learner_id,
        "permissions": ["view_reports", "not_a_real_permission"],
    }
    _write_store(
        [
            valid,
            {"id": "ga_missing_learner", "guardian_user_id": guardian_id},
            "junk-entry",
            dict(valid, permissions=["manage_restrictions"]),
            {
                "id": "ga_revoked",
                "guardian_user_id": users["guardian_b"]["id"],
                "learner_user_id": users["learner_b"]["id"],
                "permissions": ["view_reports"],
                "granted_at": "2026-01-02T00:00:00+00:00",
                "revoked_at": "2026-02-01T00:00:00+00:00",
                "revoked_by": "admin",
                "revocation_reason": "season_end",
            },
        ]
    )

    active = guardians.list_relationships()
    assert [record["id"] for record in active] == ["ga_valid"]
    assert active[0]["permissions"] == ["view_reports"]
    assert active[0]["granted_at"]

    history = guardians.list_relationships(include_revoked=True)
    assert [record["id"] for record in history] == ["ga_valid", "ga_revoked"]
    assert history[1]["revoked_by"] == "admin"
    assert history[1]["revocation_reason"] == "season_end"

    assert guardians.guardian_can_access(guardian_id, learner_id, "view_reports") is True
    assert (
        guardians.guardian_can_access(
            users["guardian_b"]["id"], users["learner_b"]["id"], "view_reports"
        )
        is False
    )
