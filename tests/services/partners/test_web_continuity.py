"""Unit contract for the shared web conversation pointer (web_continuity.py).

Covers the service layer the web-continuity endpoints build on: selection-key
validation, pointer handoff after archive/branch/resume/delete, the persisted
state a second browser must observe, and recovery when the state file is
damaged or contended.

Router-level admission lives in tests/api/test_partners_router.py
(TestWebContinuity); manager turn admission lives in
tests/services/partners/test_partner_runtime.py; workspace binding lives in
tests/services/partners/test_workspace_binding.py.
"""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
from threading import Barrier, Thread

import pytest

from deeptutor.services.partners.web_continuity import (
    fresh_web_session_key,
    get_web_continuity,
    move_active_web_session,
    set_web_continuity,
    validate_session_key,
)

_DISABLED = {"enabled": False, "session_key": None}


@pytest.fixture
def state_path(partners_root) -> Path:
    """Where the continuity pointer for ada/account-a is persisted."""
    path = partners_root / "ada" / "users" / "account-a" / "web_continuity.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _spy_idle_lock(calls: list[str]):
    @contextmanager
    def _lock(key: str):
        calls.append(key)
        yield

    return _lock


# ── Selection-key validation ───────────────────────────────────


def test_valid_key_returns_canonical_stem():
    assert validate_session_key("web-current") == "web-current"
    # Only the legacy colon substitution is a lossless alias.
    assert validate_session_key("web:abc") == "web_abc"
    assert validate_session_key("  web:abc  ") == "web_abc"
    assert validate_session_key("web.1.2") == "web.1.2"


@pytest.mark.parametrize(
    "key",
    [
        "",
        "   ",
        "a" * 129,
        "web<1",
        "web>1",
        'web"1',
        "web/../../etc",
        "web\\1",
        "web|1",
        "web?1",
        "web*1",
        "web\x00key",
        "web\x1fkey",
        "web\x7fkey",
    ],
)
def test_invalid_keys_are_rejected(key):
    with pytest.raises(ValueError, match="Invalid Partner session key"):
        validate_session_key(key)


def test_key_at_length_boundary_is_accepted():
    assert validate_session_key("a" * 128) == "a" * 128
    with pytest.raises(ValueError):
        validate_session_key("a" * 129)


@pytest.mark.parametrize("key", ["web_abc.", "..hidden", "trailing.."])
def test_lossy_alias_keys_are_rejected(key):
    # safe_filename loses these characters, so accepting them would point the
    # selector at a stem no listed session carries.
    with pytest.raises(ValueError, match="Invalid Partner session key"):
        validate_session_key(key)


# ── Read-side defaults and recovery ────────────────────────────


def test_missing_state_file_reports_disabled(state_path):
    assert get_web_continuity("ada", "account-a") == _DISABLED
    assert not state_path.exists()


def test_state_round_trips_through_disk(state_path):
    set_web_continuity("ada", "account-a", enabled=True, session_key="web-a")
    # A second browser reads the same persisted pointer, not an in-memory copy.
    assert get_web_continuity("ada", "account-a") == {"enabled": True, "session_key": "web-a"}
    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "enabled": True,
        "session_key": "web-a",
    }


def test_legacy_state_file_key_is_canonicalized_on_read(state_path):
    state_path.write_text(json.dumps({"enabled": True, "session_key": "web:abc"}), encoding="utf-8")
    assert get_web_continuity("ada", "account-a") == {"enabled": True, "session_key": "web_abc"}


def test_disabled_state_ignores_any_stored_key(state_path):
    state_path.write_text(
        json.dumps({"enabled": False, "session_key": "web-stale"}), encoding="utf-8"
    )
    assert get_web_continuity("ada", "account-a") == _DISABLED


@pytest.mark.parametrize(
    "payload",
    [
        "not json{",
        "[1, 2]",
        '{"enabled": "yes"}',
        '{"enabled": 1, "session_key": "web-a"}',
        '{"enabled": true}',
        '{"enabled": true, "session_key": "bad*key"}',
    ],
)
def test_damaged_state_file_raises_and_is_not_overwritten(state_path, payload):
    state_path.write_text(payload, encoding="utf-8")
    with pytest.raises(RuntimeError, match="continuity state"):
        get_web_continuity("ada", "account-a")
    with pytest.raises(RuntimeError, match="continuity state"):
        set_web_continuity("ada", "account-a", enabled=True, session_key="web-a")
    # Recovery is explicit: the damaged file survives until a human repairs it,
    # a failing writer must not silently reset or replace it.
    assert state_path.read_text(encoding="utf-8") == payload


def test_atomic_write_leaves_no_temporary_files(state_path):
    set_web_continuity("ada", "account-a", enabled=True, session_key="web-a")
    set_web_continuity("ada", "account-a", enabled=False)
    assert sorted(p.name for p in state_path.parent.iterdir()) == [
        ".web_continuity.json.lock",
        "web_continuity.json",
    ]


# ── Selection updates ──────────────────────────────────────────


def test_enable_persists_canonical_key():
    state = set_web_continuity("ada", "account-a", enabled=True, session_key="web:abc")
    assert state == {"enabled": True, "session_key": "web_abc"}
    assert get_web_continuity("ada", "account-a") == state


def test_enable_without_a_key_fails_and_writes_nothing(state_path):
    with pytest.raises(ValueError, match="Invalid Partner session key"):
        set_web_continuity("ada", "account-a", enabled=True, session_key=None)
    with pytest.raises(ValueError, match="Invalid Partner session key"):
        set_web_continuity("ada", "account-a", enabled=True, session_key="bad*")
    assert get_web_continuity("ada", "account-a") == _DISABLED
    assert not state_path.exists()


def test_failed_enable_keeps_previous_selection():
    set_web_continuity("ada", "account-a", enabled=True, session_key="web-a")
    with pytest.raises(ValueError, match="Invalid Partner session key"):
        set_web_continuity("ada", "account-a", enabled=True, session_key="web<*b")
    assert get_web_continuity("ada", "account-a") == {"enabled": True, "session_key": "web-a"}


def test_disable_clears_the_key_without_validating_it():
    set_web_continuity("ada", "account-a", enabled=True, session_key="web:abc")
    assert set_web_continuity("ada", "account-a", enabled=False, session_key="bad*") == _DISABLED
    assert set_web_continuity("ada", "account-a", enabled=False) == _DISABLED
    assert get_web_continuity("ada", "account-a") == _DISABLED


def test_idle_lock_only_guards_a_key_change():
    calls: list[str] = []
    idle_lock = _spy_idle_lock(calls)

    set_web_continuity("ada", "account-a", enabled=True, session_key="web-a", idle_lock=idle_lock)
    assert calls == []  # First selection: no turn can be running on an old key.
    set_web_continuity("ada", "account-a", enabled=True, session_key="web-a", idle_lock=idle_lock)
    assert calls == []  # Rewriting the same selection needs no guard either.
    set_web_continuity("ada", "account-a", enabled=True, session_key="web_b", idle_lock=idle_lock)
    assert calls == ["web-a"]  # Switching waits for the in-flight turn on web-a.
    set_web_continuity("ada", "account-a", enabled=False, idle_lock=idle_lock)
    assert calls == ["web-a", "web_b"]  # Disabling guards the current key.


# ── Pointer handoff (archive / delete / branch / resume) ───────


def test_move_is_ignored_while_continuity_is_disabled(state_path):
    moved = move_active_web_session(
        "ada", "account-a", session_key="web-a", new_session_key="web-b"
    )
    assert moved is None
    assert not state_path.exists()


def test_guarded_move_requires_the_selected_source_key():
    set_web_continuity("ada", "account-a", enabled=True, session_key="web-a")
    moved = move_active_web_session(
        "ada", "account-a", session_key="web-b", new_session_key="web-c"
    )
    assert moved is None
    moved = move_active_web_session("ada", "account-a", session_key="bad*", new_session_key="web-c")
    assert moved is None
    assert get_web_continuity("ada", "account-a") == {"enabled": True, "session_key": "web-a"}


def test_move_hands_the_selection_to_the_new_key():
    set_web_continuity("ada", "account-a", enabled=True, session_key="web-a")
    moved = move_active_web_session(
        "ada", "account-a", session_key="web-a", new_session_key="web:xyz"
    )
    assert moved == "web_xyz"
    assert get_web_continuity("ada", "account-a") == {"enabled": True, "session_key": "web_xyz"}


def test_unguarded_move_follows_a_resume_of_any_session():
    set_web_continuity("ada", "account-a", enabled=True, session_key="web-a")
    moved = move_active_web_session(
        "ada",
        "account-a",
        session_key="web-archived-elsewhere",
        new_session_key="web-a",
        only_if_current=False,
    )
    assert moved == "web-a"
    assert get_web_continuity("ada", "account-a") == {"enabled": True, "session_key": "web-a"}


def test_move_rejects_invalid_target_key_and_keeps_state():
    set_web_continuity("ada", "account-a", enabled=True, session_key="web-a")
    with pytest.raises(ValueError, match="Invalid Partner session key"):
        move_active_web_session("ada", "account-a", session_key="web-a", new_session_key="bad*")
    assert get_web_continuity("ada", "account-a") == {"enabled": True, "session_key": "web-a"}


def test_move_idle_lock_only_fires_when_the_key_changes():
    calls: list[str] = []
    idle_lock = _spy_idle_lock(calls)
    set_web_continuity("ada", "account-a", enabled=True, session_key="web-a")

    assert (
        move_active_web_session(
            "ada",
            "account-a",
            session_key="web-a",
            new_session_key="web-a",
            idle_lock=idle_lock,
        )
        == "web-a"
    )
    assert calls == []  # Rewriting the identical pointer: no in-flight turn.
    move_active_web_session(
        "ada", "account-a", session_key="web-a", new_session_key="web:xyz", idle_lock=idle_lock
    )
    assert calls == ["web-a"]  # The stored key changes, so the turn guard fires.


# ── Fresh key generation ───────────────────────────────────────


def test_fresh_keys_are_unique_and_selectable():
    first = fresh_web_session_key()
    second = fresh_web_session_key()
    assert first != second
    assert first.startswith("web-") and second.startswith("web-")
    assert validate_session_key(first) == first
    assert validate_session_key(second) == second


# ── Cross-browser consistency ──────────────────────────────────


def test_concurrent_browsers_serialize_on_one_persisted_pointer(state_path):
    barrier = Barrier(2)
    outcomes: list[dict] = []

    def _select(key: str) -> None:
        barrier.wait()
        outcomes.append(set_web_continuity("ada", "account-a", enabled=True, session_key=key))

    threads = [
        Thread(target=_select, args=(key,), name=f"browser-{key}") for key in ("web-t1", "web-t2")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert sorted(o["session_key"] for o in outcomes) == ["web-t1", "web-t2"]
    final = get_web_continuity("ada", "account-a")
    assert final["enabled"] is True
    assert final["session_key"] in {"web-t1", "web-t2"}
    # The file itself holds exactly the last serialized write, readable as JSON.
    assert json.loads(state_path.read_text(encoding="utf-8")) == final


def test_state_lock_waits_for_a_foreign_process_lock(state_path):
    lock_path = state_path.with_name(".web_continuity.json.lock")
    with open(lock_path, "a+b") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)  # Another backend worker wins it first.
        writer = Thread(
            target=lambda: set_web_continuity(
                "ada", "account-a", enabled=True, session_key="web-a"
            ),
            name="second-worker",
        )
        writer.start()
        writer.join(timeout=0.3)
        assert writer.is_alive()  # Blocked on the flock, not racing the file.
        fcntl.flock(held.fileno(), fcntl.LOCK_UN)
    writer.join(timeout=10)
    assert not writer.is_alive()
    assert get_web_continuity("ada", "account-a") == {"enabled": True, "session_key": "web-a"}
