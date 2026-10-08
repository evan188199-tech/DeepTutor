"""External LTI subject → local account mapping (JIT provisioning)."""

from __future__ import annotations

import pytest

from deeptutor.services.auth import verify_password
from deeptutor.services.lti import LtiError
from deeptutor.services.lti.provisioning import (
    local_username_for,
    map_local_role,
    provision_lti_user,
)

from .conftest import (
    INSTRUCTOR_ROLE,
    ISSUER,
    LEARNER_ROLE,
    TEACHING_ASSISTANT_ROLE,
)


def _load_users() -> dict:
    from deeptutor.multi_user.identity import load_users

    return load_users()


def test_local_username_is_deterministic_and_opaque() -> None:
    first = local_username_for(ISSUER, "subject-1")
    second = local_username_for(ISSUER, "subject-1")
    other = local_username_for(ISSUER, "subject-2")

    assert first == second
    assert first != other
    assert first.startswith("lti-")
    assert len(first) == len("lti-") + 32
    # No platform identifier is embedded in the local username.
    assert "subject-1" not in first


def test_map_local_role_teaching_roles() -> None:
    assert map_local_role([INSTRUCTOR_ROLE]) == "teacher"
    assert map_local_role([TEACHING_ASSISTANT_ROLE]) == "teacher"
    assert map_local_role([INSTRUCTOR_ROLE, LEARNER_ROLE]) == "teacher"


def test_map_local_role_defaults_to_least_privilege() -> None:
    assert map_local_role([LEARNER_ROLE]) == "student"
    assert map_local_role([]) == "student"
    assert map_local_role(["http://purl.imsglobal.org/vocab/lis/v2/system#User"]) == "student"


def test_provision_learner_creates_student_with_learner_preset(lti_identity_root) -> None:
    username, record = provision_lti_user(ISSUER, "subject-1", [LEARNER_ROLE])

    users = _load_users()
    assert username in users
    assert record["role"] == "student"
    assert record["preset"] == "learner"
    assert record["id"].startswith("u_")


def test_provision_instructor_creates_teacher(lti_identity_root) -> None:
    _, record = provision_lti_user(ISSUER, "subject-2", [INSTRUCTOR_ROLE])
    assert record["role"] == "teacher"
    assert record["preset"] == "standard"


def test_provision_is_idempotent(lti_identity_root) -> None:
    first_username, first = provision_lti_user(ISSUER, "subject-1", [LEARNER_ROLE])
    second_username, second = provision_lti_user(ISSUER, "subject-1", [INSTRUCTOR_ROLE])

    assert first_username == second_username
    # The role is fixed at first provisioning and never drifts on re-launch.
    assert second["role"] == first["role"] == "student"
    assert len(_load_users()) == 1


def test_provision_never_creates_admin_even_in_empty_store(lti_identity_root) -> None:
    assert _load_users() == {}

    _, record = provision_lti_user(ISSUER, "first-ever-subject", [INSTRUCTOR_ROLE])

    assert record["role"] == "teacher"
    assert all(user["role"] != "admin" for user in _load_users().values())


def test_provisioned_account_cannot_password_login(lti_identity_root) -> None:
    _, record = provision_lti_user(ISSUER, "subject-1", [LEARNER_ROLE])
    assert verify_password("any-password", record["hash"]) is False


def test_provision_refuses_existing_admin_account(lti_identity_root) -> None:
    from deeptutor.multi_user.identity import save_user

    username = local_username_for(ISSUER, "subject-1")
    save_user(username, "hashed-password", role="admin")

    with pytest.raises(LtiError) as excinfo:
        provision_lti_user(ISSUER, "subject-1", [LEARNER_ROLE])
    assert excinfo.value.status_code == 403


def test_provision_refuses_disabled_account(lti_identity_root) -> None:
    username, _ = provision_lti_user(ISSUER, "subject-1", [LEARNER_ROLE])

    from deeptutor.multi_user.identity import _write_users, load_users

    users = load_users()
    users[username]["disabled"] = True
    _write_users(users)

    with pytest.raises(LtiError) as excinfo:
        provision_lti_user(ISSUER, "subject-1", [LEARNER_ROLE])
    assert excinfo.value.status_code == 403
