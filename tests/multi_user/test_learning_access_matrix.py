"""Access-decision matrix for ``learning_access`` (policy × action).

Table-driven behavior contract for the learning-account policy gates: who gets
a policy, how malformed/absent policies behave, which capabilities, surfaces
and materials each policy allows or denies, and how the turn payload is
scrubbed. Grant validation itself is covered by ``test_grants_and_settings``
and the preset/legacy normalization by ``test_learning_policy``.
"""

from __future__ import annotations

import pytest

from deeptutor.multi_user.grants import save_grant
from deeptutor.multi_user.learning_access import (
    apply_learning_policy,
    assert_learning_material,
    assert_learning_material_mutation,
    assert_learning_surface,
    current_learning_policy,
    learning_material_allowed,
    learning_policy_for_user,
)


def _policy(
    *,
    capabilities=("chat", "immersive_reading"),
    surfaces=None,
    reading=True,
    allow_upload=False,
    material_ids=("m1",),
):
    policy = {
        "age_band": "9-12",
        "locked_persona": "teacher",
        "allowed_capabilities": list(capabilities),
        "default_capability": list(capabilities)[0],
    }
    if surfaces is not None:
        policy["allowed_surfaces"] = list(surfaces)
    if reading:
        policy["reading"] = {
            "allow_upload": allow_upload,
            "material_ids": list(material_ids),
            "extensions": ["quiz"],
        }
    return {
        "enabled_tools": [],
        "mcp_tools": [],
        "cli_apps": [],
        "exec_enabled": False,
        "learning_policy": policy,
    }


def _seed_learner(seed_user, name):
    seed_user("admin", role="admin")
    return seed_user(name)


def _saved_learner(seed_user, name, payload):
    learner = _seed_learner(seed_user, name)
    save_grant(learner["id"], payload)
    return learner["id"]


def test_who_gets_a_policy(mu_isolated_root, seed_user, as_user):
    uid = _saved_learner(seed_user, "student", _policy())

    # Admins always run unrestricted, with or without a stored grant.
    assert learning_policy_for_user(uid, is_admin=True) is None
    with as_user("u_admin", role="admin"):
        assert current_learning_policy() is None

    # A standard user without any grant has no policy...
    assert learning_policy_for_user("u_plain", is_admin=False) is None
    # ...and neither does an unknown id.
    assert learning_policy_for_user("u_ghost", is_admin=False) is None

    with as_user(uid, username="student"):
        policy = current_learning_policy()
    assert policy is not None
    assert policy["locked_persona"] == "teacher"


def test_returned_policy_is_a_defensive_copy(mu_isolated_root, seed_user):
    uid = _saved_learner(seed_user, "student", _policy())

    first = learning_policy_for_user(uid, is_admin=False)
    first["allowed_capabilities"].append("deep_research")
    first["reading"]["material_ids"].append("injected")

    second = learning_policy_for_user(uid, is_admin=False)

    assert "deep_research" not in second["allowed_capabilities"]
    assert "injected" not in second["reading"]["material_ids"]
    assert set(second["allowed_capabilities"]) == {"chat", "immersive_reading"}


def test_no_policy_leaves_the_turn_payload_untouched(mu_isolated_root, seed_user, as_user):
    _seed_learner(seed_user, "plain")
    payload = {"capability": "chat", "tools": [{"name": "web_search"}], "kb_name": "kb"}

    with as_user("u_plain", username="plain"):
        assert apply_learning_policy(payload) is payload
        assert_learning_surface("books")
        assert_learning_material("anything")
        assert_learning_material_mutation("anything")


CAPABILITY_ROWS = [
    ("missing-capability-defaults-to-chat", ("chat", "immersive_reading"), {}, True),
    ("missing-capability-denied-without-chat", ("immersive_reading",), {}, False),
    ("explicit-allowed-capability", ("chat",), {"capability": "chat"}, True),
    ("explicit-denied-capability", ("chat",), {"capability": "immersive_reading"}, False),
]


@pytest.mark.parametrize(
    ("label", "capabilities", "payload", "allowed"),
    CAPABILITY_ROWS,
    ids=[row[0] for row in CAPABILITY_ROWS],
)
def test_apply_policy_capability_gate(seed_user, as_user, label, capabilities, payload, allowed):
    uid = _saved_learner(seed_user, "student", _policy(capabilities=capabilities))

    with as_user(uid, username="student"):
        if allowed:
            result = apply_learning_policy(dict(payload))
            assert result["persona"] == "teacher"
        else:
            with pytest.raises(PermissionError, match="cannot use this mode"):
                apply_learning_policy(dict(payload))


def test_apply_policy_scrubs_the_turn_surface(seed_user, as_user):
    uid = _saved_learner(seed_user, "student", _policy())

    with as_user(uid, username="student"):
        result = apply_learning_policy(
            {
                "capability": "chat",
                "persona": "friend",
                "tools": [{"name": "web_search"}],
                "enabled_tools": ["web_search"],
                "knowledge_bases": ["admin:kb:private"],
                "kb_name": "private",
                "enable_rag": True,
                "enable_web_search": True,
                "partner_id": "partner",
                "bot_id": "bot",
                "kept": "value",
            }
        )

    assert result["kept"] == "value"
    assert result["persona"] == "teacher"
    assert result["tools"] == []
    assert result["enabled_tools"] == []
    assert result["knowledge_bases"] == []
    assert result["kb_name"] == ""
    assert result["enable_rag"] is False
    assert result["enable_web_search"] is False
    assert result["partner_id"] is None
    assert result["bot_id"] is None


SURFACE_ROWS = [
    ("explicit surface allowed", ["reading"], "reading", True),
    ("explicit surface denied", ["reading"], "chat", False),
    ("empty surface named in the error", ["chat"], "", False),
    ("default surfaces allow chat", None, "chat", True),
    ("default surfaces deny books", None, "books", False),
]


@pytest.mark.parametrize(
    ("label", "surfaces", "surface", "allowed"),
    SURFACE_ROWS,
    ids=[row[0] for row in SURFACE_ROWS],
)
def test_surface_guard_matrix(seed_user, as_user, label, surfaces, surface, allowed):
    uid = _saved_learner(seed_user, "student", _policy(surfaces=surfaces))

    with as_user(uid, username="student"):
        if allowed:
            assert_learning_surface(surface)
        else:
            with pytest.raises(PermissionError, match="cannot use"):
                assert_learning_surface(surface)


def test_empty_surface_error_names_the_requested_surface(seed_user, as_user):
    uid = _saved_learner(seed_user, "student", _policy(surfaces=["chat"]))

    with as_user(uid, username="student"):
        with pytest.raises(PermissionError, match="requested server surface"):
            assert_learning_surface("")


MATERIAL_ROWS = [
    ("assigned material allowed", ("m1",), "m1", True),
    ("unassigned material denied", ("m1",), "m2", False),
    ("no wildcard on empty list", (), "", False),
    ("absent reading keeps legacy access", None, "anything", True),
]


@pytest.mark.parametrize(
    ("label", "material_ids", "material", "allowed"),
    MATERIAL_ROWS,
    ids=[row[0] for row in MATERIAL_ROWS],
)
def test_material_guard_matrix(seed_user, as_user, label, material_ids, material, allowed):
    uid = _saved_learner(
        seed_user,
        "student",
        _policy(reading=material_ids is not None, material_ids=material_ids or ()),
    )

    with as_user(uid, username="student"):
        assert learning_material_allowed(material) is allowed
        if allowed:
            assert_learning_material(material)
        else:
            with pytest.raises(PermissionError, match="not assigned"):
                assert_learning_material(material)


MUTATION_ROWS = [
    ("standard user mutates freely", None, "m1", True),
    ("upload denied denies mutation", (False, ("m1",)), "m1", False),
    ("upload allowed but material unassigned", (True, ("m1",)), "m2", False),
    ("upload allowed and material assigned", (True, ("m1",)), "m1", True),
]


@pytest.mark.parametrize(
    ("label", "reading", "material", "allowed"),
    MUTATION_ROWS,
    ids=[row[0] for row in MUTATION_ROWS],
)
def test_material_mutation_matrix(seed_user, as_user, label, reading, material, allowed):
    if reading is None:
        payload = {"learning_policy": None}
    else:
        allow_upload, material_ids = reading
        payload = _policy(allow_upload=allow_upload, material_ids=material_ids)
    uid = _saved_learner(seed_user, "student", payload)

    with as_user(uid, username="student"):
        if allowed:
            assert_learning_material_mutation(material)
        else:
            with pytest.raises(PermissionError):
                assert_learning_material_mutation(material)
