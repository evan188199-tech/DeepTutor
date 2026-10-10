"""Unit contracts for partner workspace binding, with fake storage only.

The runtime-level behaviour of ``workspace_binding`` is covered by
``test_workspace_binding.py`` against the real content-workspace service.
This file pins the same seams at unit granularity: owner resolution,
binding validation running inside the owner's identity and outside any
pinned content scope, and the assembly order of the partner content
context (activity lease -> validation -> scope pinning).
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.models import LOCAL_ADMIN_ID, CurrentUser, UserScope
from deeptutor.multi_user.paths import user_context
from deeptutor.services.partners import workspace_binding
from deeptutor.services.partners.manager import PartnerConfig
from deeptutor.services.partners.workspace_binding import (
    partner_content_context,
    validate_partner_workspace,
    workspace_owner,
)
from deeptutor.services.workspace import WorkspaceError


def _user(user_id: str, *, role: str = "user") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        username=user_id,
        role=role,
        scope=UserScope(
            kind="admin" if role == "admin" else "user",
            user_id=user_id,
            root=Path("/scopes") / user_id,
        ),
    )


class _FakeBindingService:
    """Records validate_chat_binding calls and optionally refuses them."""

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[dict] = []

    def validate_chat_binding(self, workspace_id, *, existing: bool = False):
        self.calls.append(
            {
                "workspace_id": workspace_id,
                "existing": existing,
                "user_id": get_current_user().id,
                "pinned_scope": _current_pinned_scope(),
            }
        )
        if self.error is not None:
            raise self.error
        return object()


def _current_pinned_scope() -> str:
    from deeptutor.services.workspace.context import get_workspace_scope

    scope = get_workspace_scope()
    return scope.workspace_id if scope else ""


@pytest.fixture
def events(monkeypatch) -> list[str]:
    """Route the binding module's context helpers through an event log."""
    log: list[str] = []

    @contextmanager
    def recording_workspace_context(workspace_id):
        log.append(f"workspace:enter:{workspace_id}")
        try:
            yield workspace_id
        finally:
            log.append("workspace:exit")

    @contextmanager
    def recording_activity(*, exclusive: bool = False):
        log.append("activity:enter")
        try:
            yield
        finally:
            log.append("activity:exit")

    monkeypatch.setattr(workspace_binding, "workspace_context", recording_workspace_context)
    monkeypatch.setattr(workspace_binding, "data_activity", recording_activity)
    return log


@pytest.fixture
def fake_service(monkeypatch) -> _FakeBindingService:
    service = _FakeBindingService()
    monkeypatch.setattr(workspace_binding, "get_content_workspace_service", lambda: service)
    return service


# ── workspace_owner ───────────────────────────────────────────────


def test_workspace_owner_blank_config_owner_falls_back_to_local_admin():
    assert workspace_owner("").id == LOCAL_ADMIN_ID
    assert workspace_owner("").role == "admin"


def test_workspace_owner_returns_authenticated_caller_without_store_lookup(monkeypatch):
    owner = _user("owner-1")
    monkeypatch.setattr(
        workspace_binding,
        "actor_for_account",
        lambda user_id: pytest.fail("The authenticated caller must not trigger a store lookup"),
    )
    with user_context(owner):
        assert workspace_owner(owner.id) is owner


def test_workspace_owner_rebuilds_saved_account_for_channel_traffic(monkeypatch):
    owner = _user("owner-1")
    looked_up: list[str] = []
    monkeypatch.setattr(
        workspace_binding,
        "actor_for_account",
        lambda user_id: (looked_up.append(user_id), owner)[1],
    )
    # Channel turns carry no session: someone else (or nobody) is current.
    with user_context(_user("onlooker")):
        assert workspace_owner("owner-1") is owner
    assert looked_up == ["owner-1"]


def test_workspace_owner_refuses_deleted_account(monkeypatch):
    monkeypatch.setattr(workspace_binding, "actor_for_account", lambda user_id: None)
    with (
        user_context(_user("onlooker")),
        pytest.raises(WorkspaceError, match="owner is unavailable"),
    ):
        workspace_owner("owner-1")


# ── validate_partner_workspace ────────────────────────────────────


def test_blank_workspace_id_is_a_passthrough_and_touches_nothing(fake_service, monkeypatch):
    monkeypatch.setattr(
        workspace_binding,
        "actor_for_account",
        lambda user_id: pytest.fail("A blank binding must not resolve any owner"),
    )
    assert validate_partner_workspace("   ", "owner-1") == ""
    assert fake_service.calls == []


def test_validation_runs_under_owner_identity_outside_any_content_scope(
    fake_service, events, monkeypatch
):
    monkeypatch.setattr(
        workspace_binding,
        "actor_for_account",
        lambda user_id: _user(user_id),
    )
    # The caller is somebody else entirely: the stored owner, not the
    # caller, decides whose catalog the binding is checked against.
    with user_context(_user("message-sender")):
        result = validate_partner_workspace("  ws-7  ", "owner-1")
    assert result == "ws-7"
    assert fake_service.calls == [
        {
            "workspace_id": "ws-7",
            "existing": False,
            "user_id": "owner-1",
            "pinned_scope": "",
        }
    ]
    assert events == ["workspace:enter:", "workspace:exit"]


def test_missing_workspace_rejection_propagates_without_returning_an_id(
    fake_service, events, monkeypatch
):
    fake_service.error = WorkspaceError("Workspace not found or archived.")
    monkeypatch.setattr(
        workspace_binding,
        "actor_for_account",
        lambda user_id: _user(user_id),
    )
    with user_context(_user("owner-1")), pytest.raises(WorkspaceError):
        validate_partner_workspace("ws-gone", "owner-1")
    assert [call["workspace_id"] for call in fake_service.calls] == ["ws-gone"]


# ── partner_content_context ───────────────────────────────────────


def test_unbound_partner_runs_in_its_own_synthetic_scope(fake_service, events, monkeypatch):
    marker = _user("partner_ada")
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(
        workspace_binding,
        "partner_user",
        lambda partner_id, *, name="": (seen.append((partner_id, name)), marker)[1],
    )
    config = PartnerConfig(name="Ada")
    with partner_content_context("ada", config):
        assert get_current_user() is marker
    assert seen == [("ada", "Ada")]
    assert fake_service.calls == []
    assert events == []


def test_bound_partner_pins_owner_scope_activity_lease_and_workspace(
    fake_service, events, monkeypatch
):
    monkeypatch.setattr(
        workspace_binding,
        "actor_for_account",
        lambda user_id: _user(user_id),
    )
    config = PartnerConfig(name="Ada", owner_id="owner-1", workspace_id="ws-7")
    with user_context(_user("message-sender")):
        with partner_content_context("ada", config):
            assert get_current_user().id == "owner-1"
    assert fake_service.calls == [
        {
            "workspace_id": "ws-7",
            "existing": False,
            "user_id": "owner-1",
            "pinned_scope": "",
        }
    ]
    assert events == [
        "activity:enter",
        "workspace:enter:ws-7",
        "workspace:exit",
        "activity:exit",
    ]


def test_failed_binding_refuses_the_turn_and_leaves_nothing_installed(
    fake_service, events, monkeypatch
):
    fake_service.error = WorkspaceError("Workspace not found or archived.")
    monkeypatch.setattr(
        workspace_binding,
        "actor_for_account",
        lambda user_id: _user(user_id),
    )
    config = PartnerConfig(name="Ada", owner_id="owner-1", workspace_id="ws-7")
    entered = []

    with user_context(_user("owner-1")), pytest.raises(WorkspaceError):
        with partner_content_context("ada", config):
            entered.append(True)

    assert entered == []
    assert events == ["activity:enter", "activity:exit"]
    assert _current_pinned_scope() == ""


def test_turn_body_error_releases_lease_and_workspace_scope(fake_service, events, monkeypatch):
    monkeypatch.setattr(
        workspace_binding,
        "actor_for_account",
        lambda user_id: _user(user_id),
    )
    config = PartnerConfig(name="Ada", owner_id="owner-1", workspace_id="ws-7")
    with pytest.raises(RuntimeError, match="generation failed"):
        with partner_content_context("ada", config):
            raise RuntimeError("generation failed")
    assert events == [
        "activity:enter",
        "workspace:enter:ws-7",
        "workspace:exit",
        "activity:exit",
    ]
