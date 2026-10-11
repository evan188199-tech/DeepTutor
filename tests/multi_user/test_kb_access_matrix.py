"""Access-decision matrix for ``knowledge_access`` (role × resource × write).

Table-driven behavior contract: which (role, reference, require_write)
combinations resolve, which resource shape they yield (source / assigned /
read_only), and which are refused. Fixtures construct the roles and KBs on an
isolated root; the workspace-selection and routing layers are covered by
``test_workspace_resources`` and the manifest seam by
``test_kb_manifest_access``.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import HTTPException
import pytest

from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.multi_user import grants
from deeptutor.multi_user.knowledge_access import (
    admin_kb_manager,
    assert_writable,
    current_kb_manager,
    list_visible_knowledge_bases,
    resolve_for_rag,
    resolve_kb,
    resolve_kb_document_path,
    resolve_kb_metadata,
)

ADMIN_KB = "admin-notes"
ADMIN_SECRET_KB = "admin-secret"
OWN_KB = "alice-kb"

# (source, assigned, read_only) for an accepted reference.
USER_RESOURCE = ("user", False, False)
ADMIN_ASSIGNED_RESOURCE = ("admin", True, True)
ADMIN_OWN_RESOURCE = ("admin", False, False)


def _make_kb(manager: KnowledgeBaseManager, name: str, *files: str) -> None:
    raw = Path(manager.base_dir) / name / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "sub").mkdir(exist_ok=True)
    for filename in files:
        (raw / filename).write_bytes(b"x" * 16)
    manager.register_knowledge_base(name, description=f"matrix {name}")


def _grant_kbs(uid: str, entries: list) -> None:
    grant = grants.empty_grant(uid)
    grant["knowledge_bases"] = entries
    path = grants.grant_path(uid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(grant), encoding="utf-8")


@pytest.fixture
def seeded_world(mu_isolated_root, as_user):
    """Alice owns one KB, the admin workspace holds two, alice is granted one."""
    with as_user("u_alice", role="user"):
        _make_kb(current_kb_manager(), OWN_KB, "a.pdf")
    with as_user("u_admin", role="admin"):
        _make_kb(admin_kb_manager(), ADMIN_KB, "doc.pdf")
        _make_kb(admin_kb_manager(), ADMIN_SECRET_KB, "secret.pdf")
    _grant_kbs("u_alice", [{"name": ADMIN_KB}])


def _assert_decision(kb_ref: str, require_write: bool, expected) -> None:
    if expected[0] == "http":
        with pytest.raises(HTTPException) as exc:
            resolve_kb(kb_ref, require_write=require_write)
        assert exc.value.status_code == expected[1]
        return
    resource = resolve_kb(kb_ref, require_write=require_write)
    assert (resource.source, resource.assigned, resource.read_only) == expected


USER_ROWS = [
    ("own bare name", OWN_KB, False, USER_RESOURCE),
    ("own user-prefixed", f"user:kb:{OWN_KB}", False, USER_RESOURCE),
    ("own account-qualified", f"account:kb:{OWN_KB}", False, USER_RESOURCE),
    ("own write", OWN_KB, True, USER_RESOURCE),
    ("assigned bare name", ADMIN_KB, False, ADMIN_ASSIGNED_RESOURCE),
    ("assigned admin-prefixed", f"admin:kb:{ADMIN_KB}", False, ADMIN_ASSIGNED_RESOURCE),
    ("assigned write", ADMIN_KB, True, ("http", 403)),
    ("assigned prefixed write", f"admin:kb:{ADMIN_KB}", True, ("http", 403)),
    ("unassigned admin kb", "admin:kb:not-yours", False, ("http", 403)),
    ("unknown kb", "ghost-kb", False, ("http", 404)),
]


@pytest.mark.parametrize(
    ("label", "kb_ref", "require_write", "expected"),
    USER_ROWS,
    ids=[row[0] for row in USER_ROWS],
)
def test_user_decision_matrix(seeded_world, as_user, label, kb_ref, require_write, expected):
    with as_user("u_alice", role="user"):
        _assert_decision(kb_ref, require_write, expected)


ADMIN_ROWS = [
    ("admin own kb", ADMIN_KB, False, ADMIN_OWN_RESOURCE),
    ("admin own kb write", f"admin:kb:{ADMIN_KB}", True, ADMIN_OWN_RESOURCE),
    ("admin unknown kb", "ghost-kb", False, ("http", 404)),
]


@pytest.mark.parametrize(
    ("label", "kb_ref", "require_write", "expected"),
    ADMIN_ROWS,
    ids=[row[0] for row in ADMIN_ROWS],
)
def test_admin_decision_matrix(seeded_world, as_user, label, kb_ref, require_write, expected):
    with as_user("u_admin", role="admin"):
        _assert_decision(kb_ref, require_write, expected)


def test_assert_writable_seam(seeded_world, as_user):
    with as_user("u_alice", role="user"):
        assert assert_writable(OWN_KB).source == "user"
        with pytest.raises(HTTPException) as exc:
            assert_writable(f"admin:kb:{ADMIN_KB}")
        assert exc.value.status_code == 403


DEFAULT_ALIASES = [
    "",
    "default",
    "DEFAULT",
    "current",
    "selected",
    "默认",
    "默认知识库",
    "当前知识库",
]


@pytest.mark.parametrize("alias", DEFAULT_ALIASES)
def test_default_alias_resolves_to_the_first_kb(seeded_world, as_user, alias):
    with as_user("u_alice", role="user"):
        _make_kb(current_kb_manager(), "a-first")
        _make_kb(current_kb_manager(), "b-second")

        resource = resolve_kb(alias)

    assert (resource.source, resource.name, resource.read_only) == ("user", "a-first", False)


def test_default_alias_without_any_kb_is_404(mu_isolated_root, as_user):
    with as_user("u_alice", role="user"):
        with pytest.raises(HTTPException) as exc:
            resolve_kb("default")
    assert "No default" in exc.value.detail


def test_admin_default_alias_without_any_kb_is_404(mu_isolated_root, as_user):
    with as_user("u_admin", role="admin"):
        with pytest.raises(HTTPException) as exc:
            resolve_kb("current")
    assert "No default" in exc.value.detail


# Grant-entry shapes ``_assigned_admin_names`` must understand; the malformed
# entries are ignored rather than crashing the resolution.
GRANT_SHAPES = [
    ("name key", [{"name": ADMIN_KB}]),
    ("kb_name key", [{"kb_name": ADMIN_KB}]),
    ("resource_id key", [{"resource_id": f"admin:kb:{ADMIN_KB}"}]),
    ("id key", [{"id": f"admin:kb:{ADMIN_KB}"}]),
]


@pytest.mark.parametrize(("label", "entries"), GRANT_SHAPES, ids=[row[0] for row in GRANT_SHAPES])
def test_grant_entry_shapes_assign_admin_kb(seeded_world, as_user, label, entries):
    _grant_kbs("u_alice", entries)
    with as_user("u_alice", role="user"):
        resource = resolve_kb(f"admin:kb:{ADMIN_KB}")
    assert (resource.source, resource.assigned, resource.read_only) == ADMIN_ASSIGNED_RESOURCE


def test_malformed_grant_entries_are_ignored(seeded_world, as_user):
    _grant_kbs("u_alice", [{}, "junk-string", 42, {"name": "   "}, {"name": ADMIN_KB}])
    with as_user("u_alice", role="user"):
        assert resolve_kb(f"admin:kb:{ADMIN_KB}").assigned is True
        with pytest.raises(HTTPException) as exc:
            resolve_kb("admin:kb:never-granted")
    assert exc.value.status_code == 403


def test_resolve_for_rag_audits_only_assigned_admin_kbs(seeded_world, as_user, monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(
        "deeptutor.multi_user.audit.log_usage",
        lambda *args, **kwargs: calls.append(args),
    )

    with as_user("u_alice", role="user"):
        assert resolve_for_rag(None) is None
        assert resolve_for_rag("") is None

        own = resolve_for_rag(OWN_KB)
        assert own is not None and own.source == "user"
        assert calls == []

        assigned = resolve_for_rag(ADMIN_KB)
        assert assigned is not None and assigned.assigned is True

    assert calls == [("knowledge_base", f"admin:kb:{ADMIN_KB}", "rag_query")]


def test_resolve_kb_metadata_contract(seeded_world, as_user):
    with as_user("u_alice", role="user"):
        assert resolve_kb_metadata(None) is None
        assert resolve_kb_metadata("") is None
        assert resolve_kb_metadata("ghost-kb") is None
        assert resolve_kb_metadata("admin:kb:not-yours") is None

        metadata = resolve_kb_metadata(OWN_KB)
    assert isinstance(metadata, dict)
    assert metadata["name"] == OWN_KB


DOC_PATH_ROWS = [
    ("no kb ref", None, "a.pdf", None),
    ("blank kb ref", "", "a.pdf", None),
    ("empty rel path", OWN_KB, "", None),
    ("whitespace rel path", OWN_KB, "   ", None),
    ("direct file", OWN_KB, "a.pdf", "raw/a.pdf"),
    ("nested file", OWN_KB, "sub/inner.pdf", "raw/sub/inner.pdf"),
    ("dotdot escape", OWN_KB, "../escape.pdf", None),
    ("absolute path", OWN_KB, "/etc/hosts", None),
    ("missing file", OWN_KB, "missing.pdf", None),
    ("directory", OWN_KB, "sub", None),
]


@pytest.mark.parametrize(
    ("label", "kb_ref", "rel_path", "relative"),
    DOC_PATH_ROWS,
    ids=[row[0] for row in DOC_PATH_ROWS],
)
def test_resolve_kb_document_path_matrix(seeded_world, as_user, label, kb_ref, rel_path, relative):
    with as_user("u_alice", role="user"):
        kb_dir = Path(current_kb_manager().base_dir) / OWN_KB
        (kb_dir / "raw" / "sub" / "inner.pdf").write_bytes(b"x")
        expected = kb_dir / relative if relative else None

        assert resolve_kb_document_path(kb_ref, rel_path) == expected


def test_document_path_denied_for_unassigned_admin_kb(seeded_world, as_user):
    with as_user("u_alice", role="user"):
        assert resolve_kb_document_path(f"admin:kb:{ADMIN_SECRET_KB}", "secret.pdf") is None


def test_visible_knowledge_bases_split_by_role(seeded_world, as_user):
    with as_user("u_alice", role="user"):
        items = {item["id"]: item for item in list_visible_knowledge_bases()}
        assert items[f"user:kb:{OWN_KB}"]["assigned"] is False
        assigned = items[f"admin:kb:{ADMIN_KB}"]
        assert (assigned["assigned"], assigned["read_only"], assigned["available"]) == (
            True,
            True,
            True,
        )
        assert set(items) == {f"user:kb:{OWN_KB}", f"admin:kb:{ADMIN_KB}"}

    with as_user("u_admin", role="admin"):
        items = {item["id"]: item for item in list_visible_knowledge_bases()}
        assert set(items) == {f"admin:kb:{ADMIN_KB}", f"admin:kb:{ADMIN_SECRET_KB}"}
        assert items[f"admin:kb:{ADMIN_KB}"]["assigned"] is False


def test_visible_knowledge_bases_ignore_malformed_grant_entries(seeded_world, as_user):
    _grant_kbs(
        "u_alice",
        [{"name": ADMIN_KB}, {"resource_id": f"admin:kb:{ADMIN_KB}"}, {"name": "ghost"}],
    )
    with as_user("u_alice", role="user"):
        ids = [item["id"] for item in list_visible_knowledge_bases()]

    # Granted admin KBs and granted-but-absent names both surface; entries
    # without a usable name are dropped by the grant loader.
    assert f"admin:kb:{ADMIN_KB}" in ids
    assert "admin:kb:ghost" in ids
    assert f"user:kb:{OWN_KB}" in ids
