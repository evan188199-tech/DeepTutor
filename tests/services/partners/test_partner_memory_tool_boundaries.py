"""Boundary tests for the partner split-memory tools.

Extends ``test_partner_memory_tools.py`` with the edge of the model: the
relationship-memory vs shared-workspace write boundary inside an assigned
user's turn, rejection paths of ``partner_memorize``, cross-partner and
cross-user read isolation, and ``partner_search`` empty-state / corrupted
record tolerance. All paths resolve under ``tmp_path`` via ``partners_root``;
no network is involved.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from deeptutor.multi_user.models import CurrentUser
from deeptutor.multi_user.paths import (
    get_admin_path_service,
    get_path_service_for_scope,
    get_current_path_service,
    scope_for_user,
    user_context,
)
from deeptutor.partners.config.paths import (
    get_partner_sessions_dir,
    get_partner_user_sessions_dir,
    get_partner_user_workspace,
    get_partner_workspace,
)
from deeptutor.services.partners.interaction import (
    build_partner_turn_context,
    partner_turn_context,
)
from deeptutor.services.partners.scope import partner_user
from deeptutor.services.partners.sessions import PartnerSessionStore
from deeptutor.tools.partner_memory import (
    PartnerMemorizeTool,
    PartnerReadTool,
    PartnerSearchTool,
)

PID = "alice"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _fresh_memory_singleton(monkeypatch):
    """Each test gets a fresh MemoryStore so its write locks don't leak."""
    from deeptutor.services.memory import store

    monkeypatch.setattr(store, "_singleton", None)


def _actor(user_id: str) -> CurrentUser:
    return CurrentUser(user_id, user_id, "user", scope_for_user(user_id, is_admin=False))


def _user_store(user_id: str) -> PartnerSessionStore:
    return PartnerSessionStore(get_partner_user_sessions_dir(PID, user_id))


def _in_user_turn(user_id: str, store: PartnerSessionStore, coro_factory):
    """Run ``coro_factory()`` inside an assigned-user partner turn."""

    async def _go():
        with user_context(partner_user(PID, name="Alice")):
            turn = build_partner_turn_context(
                PID,
                _actor(user_id),
                store,
                legacy_own_memory=get_current_path_service(),
            )
            with partner_turn_context(turn):
                return await coro_factory()

    return _run(_go())


def _seed_l3(memory_dir: Path, text: str) -> None:
    pref = memory_dir / "L3" / "preferences.md"
    pref.parent.mkdir(parents=True, exist_ok=True)
    pref.write_text(f"# Preferences\n\n## Preferences\n- {text}\n", encoding="utf-8")


# ── relationship memory vs shared workspace write boundary ──────────────


def test_memorize_in_user_turn_writes_relationship_only(partners_root: Path) -> None:
    """An assigned user's note lands in the relationship tree alone: never in
    the human's own personal memory and never in the owner's memory."""
    personal_memory = get_path_service_for_scope(
        scope_for_user("u_alice", is_admin=False)
    ).get_memory_dir()
    store = _user_store("u_alice")

    result = _in_user_turn(
        "u_alice", store, lambda: PartnerMemorizeTool().execute(op="add", text="alice preference")
    )

    assert result.success, result.content
    relationship = get_partner_user_workspace(PID, "u_alice") / "memory" / "L3" / "preferences.md"
    assert "alice preference" in relationship.read_text(encoding="utf-8")
    assert not (personal_memory / "L3" / "preferences.md").exists()
    assert not (get_admin_path_service().get_memory_dir() / "L3" / "preferences.md").exists()


def test_read_in_user_turn_folds_personal_shared_and_relationship(
    partners_root: Path,
) -> None:
    """Inside a user turn the shared layer is the human's personal L3 and the
    own layer is the relationship memory; neither leaks into the other."""
    store = _user_store("u_alice")

    with user_context(partner_user(PID, name="Alice")):
        turn = build_partner_turn_context(
            PID,
            _actor("u_alice"),
            store,
            legacy_own_memory=get_current_path_service(),
        )
        with partner_turn_context(turn):
            _seed_l3(
                get_path_service_for_scope(turn.actor.scope).get_memory_dir(),
                "u_alice personal context",
            )
            _run(PartnerMemorizeTool().execute(op="add", text="relationship-only note"))
            result = _run(PartnerReadTool().execute())

    assert result.metadata["has_shared"] is True
    assert result.metadata["has_own"] is True
    shared_part, _, own_part = result.content.partition("## Your own memory")
    assert "u_alice personal context" in shared_part
    assert "relationship-only note" not in shared_part
    assert "relationship-only note" in own_part
    assert "u_alice personal context" not in own_part


def test_cross_partner_memory_isolated(partners_root: Path) -> None:
    """Legacy scopes: one partner's workspace never sees another partner's."""
    with user_context(partner_user(PID, name="Alice")):
        _run(PartnerMemorizeTool().execute(op="add", text="alice-only fact"))
    with user_context(partner_user("bob", name="Bob")):
        _run(PartnerMemorizeTool().execute(op="add", text="bob-only fact"))
        result = _run(PartnerReadTool().execute())

    alice_pref = get_partner_workspace(PID) / "memory" / "L3" / "preferences.md"
    bob_pref = get_partner_workspace("bob") / "memory" / "L3" / "preferences.md"
    assert "alice-only fact" in alice_pref.read_text(encoding="utf-8")
    assert "bob-only fact" not in alice_pref.read_text(encoding="utf-8")
    assert "bob-only fact" in bob_pref.read_text(encoding="utf-8")
    assert "alice-only fact" not in result.content


def test_edit_updates_own_entry_not_shared(partners_root: Path) -> None:
    with user_context(partner_user(PID, name="Alice")):
        added = _run(PartnerMemorizeTool().execute(op="add", text="original wording"))
        assert added.success, added.content
        entry_id = added.metadata["entry_id"]
        result = _run(
            PartnerMemorizeTool().execute(op="edit", text="revised wording", target_id=entry_id)
        )

    assert result.success, result.content
    own_pref = get_partner_workspace(PID) / "memory" / "L3" / "preferences.md"
    body = own_pref.read_text(encoding="utf-8")
    assert "revised wording" in body
    assert "original wording" not in body
    assert not (get_admin_path_service().get_memory_dir() / "L3" / "preferences.md").exists()


# ── rejection paths ──────────────────────────────────────────────────────


def test_memorize_in_user_turn_isolated_between_users(partners_root: Path) -> None:
    """Two assigned users of the same partner never share relationship state."""
    store_a = _user_store("u_alice")
    store_b = _user_store("u_bob")
    _in_user_turn("u_alice", store_a, lambda: PartnerMemorizeTool().execute(op="add", text="a note"))
    _in_user_turn("u_bob", store_b, lambda: PartnerMemorizeTool().execute(op="add", text="b note"))

    with user_context(partner_user(PID, name="Alice")):
        turn_b = build_partner_turn_context(
            PID, _actor("u_bob"), store_b, legacy_own_memory=get_current_path_service()
        )
        with partner_turn_context(turn_b):
            result = _run(PartnerReadTool().execute())

    assert "b note" in result.content
    assert "a note" not in result.content
    # Bob's shared layer is his own (empty) personal memory, not Alice's.
    assert "(none yet" in result.content.partition("## Your own memory")[0]


def test_memorize_rejects_edit_without_target_id(partners_root: Path) -> None:
    with user_context(partner_user(PID, name="Alice")):
        result = _run(PartnerMemorizeTool().execute(op="edit", text="x"))
    assert not result.success
    assert "edit requires target_id" in result.content
    assert not (
        get_partner_workspace(PID) / "memory" / "L3" / "preferences.md"
    ).exists()


def test_memorize_rejects_edit_unknown_target(partners_root: Path) -> None:
    # Well-formed entry id (m_ + 26 base32 chars) that does not exist.
    ghost_id = "m_" + "A" * 26
    with user_context(partner_user(PID, name="Alice")):
        result = _run(
            PartnerMemorizeTool().execute(op="edit", text="x", target_id=ghost_id)
        )
    assert not result.success
    assert "not found" in result.content
    assert not (
        get_partner_workspace(PID) / "memory" / "L3" / "preferences.md"
    ).exists()


def test_memorize_rejects_empty_text(partners_root: Path) -> None:
    with user_context(partner_user(PID, name="Alice")):
        result = _run(PartnerMemorizeTool().execute(op="add", text="   "))
    assert not result.success
    assert "text is required" in result.content
    assert not (
        get_partner_workspace(PID) / "memory" / "L3" / "preferences.md"
    ).exists()


def test_memorize_rejects_oversized_text(partners_root: Path) -> None:
    with user_context(partner_user(PID, name="Alice")):
        result = _run(PartnerMemorizeTool().execute(op="add", text="x" * 241))
    assert not result.success
    assert "rejected" in result.content
    assert not (
        get_partner_workspace(PID) / "memory" / "L3" / "preferences.md"
    ).exists()


# ── history tool: empty state, corrupted records, limit handling ────────


def test_search_empty_history(partners_root: Path) -> None:
    with user_context(partner_user(PID, name="Alice")):
        result = _run(PartnerSearchTool().execute(query="calculus"))
    assert result.success
    assert result.metadata["count"] == 0
    assert "No past messages matched" in result.content


def test_search_tolerates_corrupted_session_lines(partners_root: Path) -> None:
    sessions_dir = get_partner_sessions_dir(PID)
    store = PartnerSessionStore(sessions_dir)
    store.append("s1", "user", "a valid calculus question")
    with open(sessions_dir / "s1.jsonl", "a", encoding="utf-8") as f:
        f.write("{not json at all\n")
        f.write(json.dumps([1, 2, 3]) + "\n")
        f.write(json.dumps({"role": "user"}) + "\n")
        f.write("\n")

    with user_context(partner_user(PID, name="Alice")):
        result = _run(PartnerSearchTool().execute(query="calculus"))

    assert result.success
    assert result.metadata["count"] == 1
    assert "valid calculus question" in result.content


def test_search_tolerates_corrupted_index(partners_root: Path) -> None:
    sessions_dir = get_partner_sessions_dir(PID)
    store = PartnerSessionStore(sessions_dir)
    store.append("s1", "user", "calculus survives a broken index")
    (sessions_dir / "_index.json").write_text("{broken json", encoding="utf-8")

    with user_context(partner_user(PID, name="Alice")):
        result = _run(PartnerSearchTool().execute(query="calculus"))

    assert result.success
    assert result.metadata["count"] == 1


def test_search_clamps_limit(partners_root: Path) -> None:
    store = PartnerSessionStore(get_partner_sessions_dir(PID))
    for i in range(3):
        store.append("s1", "user", f"theta question number {i}")

    with user_context(partner_user(PID, name="Alice")):
        capped = _run(PartnerSearchTool().execute(query="theta", limit=2))
        floor = _run(PartnerSearchTool().execute(query="theta", limit=-5))
        default = _run(PartnerSearchTool().execute(query="theta", limit="abc"))

    assert capped.metadata["count"] == 2
    assert floor.metadata["count"] == 1
    assert default.metadata["count"] == 3


def test_search_rejects_empty_query(partners_root: Path) -> None:
    with user_context(partner_user(PID, name="Alice")):
        result = _run(PartnerSearchTool().execute(query="  "))
    assert not result.success
    assert "query is required" in result.content


def test_search_foreign_turn_context_cannot_leave_its_store(
    partners_root: Path,
) -> None:
    """A turn context from another partner must not redirect the search: the
    active scope's own sessions dir is searched instead of the foreign store."""
    PartnerSessionStore(get_partner_user_sessions_dir(PID, "u_alice")).append(
        "k", "user", "zebra inside alice relationship store"
    )
    PartnerSessionStore(get_partner_sessions_dir("bob")).append(
        "k", "user", "zebra inside bob shared sessions"
    )

    with user_context(partner_user("bob", name="Bob")):
        turn = build_partner_turn_context(
            PID,
            _actor("u_alice"),
            _user_store("u_alice"),
            legacy_own_memory=get_current_path_service(),
        )
        with partner_turn_context(turn):
            result = _run(PartnerSearchTool().execute(query="zebra"))

    assert result.success
    assert result.metadata["count"] == 1
    assert "bob shared sessions" in result.content
    assert "alice relationship store" not in result.content
