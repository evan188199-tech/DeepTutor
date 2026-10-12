"""Recycling + mutual-exclusion semantics of the partners lock tables.

``_start_locks`` dedupes concurrent partner auto-starts and
``_draft_confirm_locks`` promotes a draft into a Partner exactly once. Both
used to keep every entry forever, growing monotonically with the number of
partners and drafts the process had ever served. These tests pin the fixed
contract: entries live exactly as long as some caller holds or awaits them,
mutual exclusion is preserved, and a later caller gets a fresh lock.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import deeptutor.api.routers.partners as partners_router_mod
from deeptutor.api.routers.partners import (
    ConfirmPartnerDraftRequest,
    _ensure_running_partner,
    confirm_partner_draft,
)


@pytest.fixture(autouse=True)
def fresh_lock_tables(monkeypatch):
    """Swap in fresh tables: a contended lock binds to this test's event loop.

    Also tolerates the pre-fix router (plain dicts) so a run against the
    unfixed code reports the leak behaviorally instead of erroring out.
    """
    table_cls = getattr(partners_router_mod, "_RecycledLockTable", None)
    if table_cls is not None:
        monkeypatch.setattr(partners_router_mod, "_start_locks", table_cls())
        monkeypatch.setattr(partners_router_mod, "_draft_confirm_locks", table_cls())
    else:
        partners_router_mod._start_locks.clear()
        partners_router_mod._draft_confirm_locks.clear()


@pytest.fixture
def user_context():
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope

    token = set_current_user(
        CurrentUser(
            id="user-1",
            username="user-1",
            role="user",
            scope=UserScope(kind="user", user_id="user-1", root=Path("/tmp/dt-test-user-1")),
        )
    )
    yield "user-1"
    reset_current_user(token)


class FakeManager:
    """Minimal partner manager around one startable instance."""

    def __init__(self, start_delay: float = 0.0) -> None:
        self.start_delay = start_delay
        self.start_calls = 0
        self.in_critical = 0
        self.max_in_critical = 0
        self.instance = SimpleNamespace(running=False)

    def get_partner(self, partner_id: str):
        return self.instance

    def load_config(self, partner_id: str):
        return object()

    async def start_partner(self, partner_id: str, config):
        self.start_calls += 1
        self.in_critical += 1
        self.max_in_critical = max(self.max_in_critical, self.in_critical)
        assert partner_id in partners_router_mod._start_locks, "entry vanished while held"
        if self.start_delay:
            await asyncio.sleep(self.start_delay)
        self.in_critical -= 1
        self.instance.running = True
        return self.instance


class TestStartLockRecycle:
    @pytest.mark.asyncio
    async def test_entry_recycled_after_use_then_reusable(self, monkeypatch):
        mgr = FakeManager()
        monkeypatch.setattr(partners_router_mod, "get_partner_manager", lambda: mgr)

        first = await _ensure_running_partner("ada", allow_stopped=True)
        assert first is mgr.instance
        assert mgr.start_calls == 1
        assert "ada" not in partners_router_mod._start_locks

        # Create → recycle → create again: the second lifecycle gets a fresh
        # entry and recycles it too.
        mgr.instance.running = False
        second = await _ensure_running_partner("ada", allow_stopped=True)
        assert second is mgr.instance
        assert mgr.start_calls == 2
        assert "ada" not in partners_router_mod._start_locks

    @pytest.mark.asyncio
    async def test_concurrent_starts_neither_deadlock_nor_break_mutex(self, monkeypatch):
        mgr = FakeManager(start_delay=0.02)
        monkeypatch.setattr(partners_router_mod, "get_partner_manager", lambda: mgr)

        results = await asyncio.wait_for(
            asyncio.gather(
                *(_ensure_running_partner("ada", allow_stopped=True) for _ in range(8))
            ),
            timeout=10,
        )

        assert all(result is mgr.instance for result in results)
        assert mgr.start_calls == 1, "double-check inside the lock must dedupe starts"
        assert mgr.max_in_critical == 1, "critical sections must never overlap"
        assert "ada" not in partners_router_mod._start_locks

    @pytest.mark.asyncio
    async def test_failed_start_still_recycles(self, monkeypatch):
        from fastapi import HTTPException

        mgr = FakeManager()

        async def explode(partner_id, config):
            raise RuntimeError("boom")

        mgr.start_partner = explode  # type: ignore[method-assign]
        monkeypatch.setattr(partners_router_mod, "get_partner_manager", lambda: mgr)

        with pytest.raises(HTTPException):
            await _ensure_running_partner("ada", allow_stopped=True)
        assert "ada" not in partners_router_mod._start_locks

    @pytest.mark.asyncio
    async def test_waiter_keeps_entry_until_last_reference_drops(self):
        table = partners_router_mod._RecycledLockTable()
        lock_a = await table.acquire("k")
        lock_b = await table.acquire("k")
        assert lock_a is lock_b

        await table.release("k")
        assert "k" in table, "a waiter still references the entry"

        await table.release("k")
        assert "k" not in table, "last reference must free the entry"

        fresh = await table.acquire("k")
        assert fresh is not lock_a, "a later caller must get a new lock object"
        await table.release("k")
        assert len(table) == 0


def _draft() -> SimpleNamespace:
    return SimpleNamespace(
        draft_id="d" * 32,
        status="pending",
        created_partner_id="",
        name="Draft Ada",
        description="",
        soul="",
        language="",
        emoji="",
        color="",
        enabled_tools=None,
        builtin_tools=None,
        mcp_tools=[],
    )


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        workspace_id="",
        name="Draft Ada",
        description="",
        channels={},
        llm_selection={},
        backup_llm_selection={},
        model=None,
        language="",
        emoji="",
        color="",
        avatar=None,
        soul_origin=None,
        enabled_tools=[],
        builtin_tools=[],
        mcp_tools=[],
    )


class FakeDraftStore:
    def __init__(self, draft: SimpleNamespace) -> None:
        self.draft = draft

    def get(self, draft_id: str):
        if draft_id != self.draft.draft_id:
            raise ValueError("unknown draft")
        return self.draft

    def mark_created(self, draft: SimpleNamespace, partner_id: str) -> None:
        draft.status = "created"
        draft.created_partner_id = partner_id


class FakeCreator:
    """Stand-in for _create_partner that observes the critical section."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.calls = 0
        self.in_critical = 0
        self.max_in_critical = 0

    async def __call__(self, payload):
        self.calls += 1
        self.in_critical += 1
        self.max_in_critical = max(self.max_in_critical, self.in_critical)
        if self.delay:
            await asyncio.sleep(self.delay)
        self.in_critical -= 1
        return {"partner_id": "draft-ada", "name": payload.name}


@pytest.fixture
def draft_env(monkeypatch):
    draft = _draft()
    creator = FakeCreator()
    monkeypatch.setattr(partners_router_mod, "PartnerDraftStore", lambda: FakeDraftStore(draft))
    monkeypatch.setattr(partners_router_mod, "_create_partner", creator)
    monkeypatch.setattr(
        partners_router_mod,
        "get_partner_manager",
        lambda: SimpleNamespace(
            load_config=lambda partner_id: _config(),
            get_partner=lambda partner_id: None,
        ),
    )
    monkeypatch.setattr(
        "deeptutor.services.partners.runtime_status.get_partner_runtime_status_repository",
        lambda: SimpleNamespace(get=lambda partner_id: None),
    )
    return SimpleNamespace(draft=draft, creator=creator)


class TestDraftConfirmLockRecycle:
    @pytest.mark.asyncio
    async def test_confirm_recycles_entry_and_repeat_is_idempotent(self, draft_env, user_context):
        key = (user_context, draft_env.draft.draft_id)

        first = await confirm_partner_draft(
            draft_env.draft.draft_id, ConfirmPartnerDraftRequest()
        )
        assert first["already_created"] is False
        assert first["partner_id"] == "draft-ada"
        assert key not in partners_router_mod._draft_confirm_locks

        repeated = await confirm_partner_draft(
            draft_env.draft.draft_id, ConfirmPartnerDraftRequest()
        )
        assert repeated["already_created"] is True
        assert repeated["partner_id"] == "draft-ada"
        assert key not in partners_router_mod._draft_confirm_locks
        assert draft_env.creator.calls == 1, "repeat confirm must not re-create"

    @pytest.mark.asyncio
    async def test_concurrent_confirms_promote_exactly_once(
        self, monkeypatch, draft_env, user_context
    ):
        creator = FakeCreator(delay=0.02)
        monkeypatch.setattr(partners_router_mod, "_create_partner", creator)
        key = (user_context, draft_env.draft.draft_id)

        results = await asyncio.wait_for(
            asyncio.gather(
                *(
                    confirm_partner_draft(draft_env.draft.draft_id, ConfirmPartnerDraftRequest())
                    for _ in range(6)
                )
            ),
            timeout=10,
        )

        assert {result["partner_id"] for result in results} == {"draft-ada"}
        assert creator.calls == 1, "exactly one confirm may create the Partner"
        assert creator.max_in_critical == 1, "confirmations must serialize per draft"
        assert key not in partners_router_mod._draft_confirm_locks
