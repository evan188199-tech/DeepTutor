"""Lifecycle, concurrency and isolation behavior of the session handoff state."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3

import pytest

from deeptutor.multi_user import session_handoff

SECRET = "test-secret"
HOST = "app.example"
CODE_LIFETIME = session_handoff.CODE_LIFETIME_SECONDS
TICKET_LIFETIME = session_handoff.TICKET_LIFETIME_SECONDS
MAX_ATTEMPTS = session_handoff.MAX_CODE_ATTEMPTS
CREATE_LIMIT, CREATE_WINDOW = session_handoff.CREATE_RATE_LIMIT
RETENTION = session_handoff.STATE_RETENTION_SECONDS


def _make_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str = "handoff.sqlite3"):
    monkeypatch.setattr(session_handoff, "load_or_create_auth_secret", lambda: SECRET)
    return session_handoff.SessionHandoffStore(tmp_path / name)


def _ticket(host: str = HOST, mode: str = "builtin", token: str | None = None) -> str:
    payload: dict = {"mode": mode, "host": host, "exp": 10_000}
    if token is not None:
        payload["token"] = token
    return session_handoff.encrypt_ticket_payload(payload, secret=SECRET)


def _create(store, ticket: str, host: str = HOST, now: int = 100, rate_key: str = "unknown"):
    return store.create(
        encrypted_ticket=ticket,
        ticket_hash=session_handoff.hash_secret(ticket),
        public_host=host,
        now=now,
        rate_key=rate_key,
    )


def _record_count(store) -> int:
    with sqlite3.connect(store.db_path) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM handoff_records").fetchone()[0])


def _single_row(store) -> dict:
    with sqlite3.connect(store.db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM handoff_records").fetchall()
    assert len(rows) == 1
    return dict(rows[0])


@pytest.mark.parametrize(
    ("stage", "offset", "expect_ok"),
    [
        ("code", -1, True),
        ("code", 0, False),
        ("code", 1, False),
        ("ticket", -1, True),
        ("ticket", 0, False),
        ("ticket", 1, False),
    ],
)
def test_handoff_expiry_boundaries(
    tmp_path, monkeypatch, stage: str, offset: int, expect_ok: bool
) -> None:
    store = _make_store(tmp_path, monkeypatch)
    created_at = 1_000
    ticket = _ticket()
    record = _create(store, ticket, now=created_at, rate_key="alice")

    if stage == "code":
        moment = created_at + CODE_LIFETIME + offset
        if expect_ok:
            fresh = store.exchange(code=record.code, public_host=HOST, now=moment)
            claims = session_handoff.decrypt_ticket_payload(fresh)
            assert claims["exp"] == moment + TICKET_LIFETIME
        else:
            with pytest.raises(session_handoff.HandoffRejected):
                store.exchange(code=record.code, public_host=HOST, now=moment)
            assert _record_count(store) == 0
        return

    exchanged_at = created_at + 10
    fresh = store.exchange(code=record.code, public_host=HOST, now=exchanged_at)
    moment = exchanged_at + TICKET_LIFETIME + offset
    if expect_ok:
        assert store.consume_ticket(ticket=fresh, public_host=HOST, now=moment) == fresh
    else:
        with pytest.raises(session_handoff.HandoffRejected):
            store.consume_ticket(ticket=fresh, public_host=HOST, now=moment)


@pytest.mark.parametrize(
    ("bad_attempts", "code_survives"),
    [
        (1, True),
        (MAX_ATTEMPTS - 1, True),
        (MAX_ATTEMPTS, False),
    ],
)
def test_wrong_host_attempts_lockout(
    tmp_path, monkeypatch, bad_attempts: int, code_survives: bool
) -> None:
    store = _make_store(tmp_path, monkeypatch)
    record = _create(store, _ticket(), now=100)

    for _ in range(bad_attempts):
        with pytest.raises(session_handoff.HandoffRejected):
            store.exchange(code=record.code, public_host="attacker.example", now=101)

    if code_survives:
        fresh = store.exchange(code=record.code, public_host=HOST, now=102)
        assert session_handoff.decrypt_ticket_payload(fresh)["host"] == HOST
    else:
        with pytest.raises(session_handoff.HandoffRejected):
            store.exchange(code=record.code, public_host=HOST, now=102)
        assert _record_count(store) == 0


def test_create_rate_limit_is_per_key_and_window_scoped(tmp_path, monkeypatch) -> None:
    store = _make_store(tmp_path, monkeypatch, "limits.sqlite3")
    for _ in range(CREATE_LIMIT):
        _create(store, _ticket(), now=1_000, rate_key="alice")
    with pytest.raises(session_handoff.HandoffRateLimited):
        _create(store, _ticket(), now=1_000, rate_key="alice")

    _create(store, _ticket(), now=1_000, rate_key="bob")
    _create(store, _ticket(), now=1_000 + CREATE_WINDOW, rate_key="alice")


def test_exchange_rotates_ticket_and_resets_attempts(tmp_path, monkeypatch) -> None:
    store = _make_store(tmp_path, monkeypatch)
    original = _ticket()
    record = _create(store, original, now=100)

    with pytest.raises(session_handoff.HandoffRejected):
        store.exchange(code=record.code, public_host="attacker.example", now=101)
    fresh = store.exchange(code=record.code, public_host=HOST, now=102)

    row = _single_row(store)
    assert row["failed_attempts"] == 0
    assert row["code_consumed_at"] == 102
    assert row["ticket_hash"] == session_handoff.hash_secret(fresh)
    assert row["encrypted_ticket"] == fresh
    assert fresh != original
    with pytest.raises(session_handoff.HandoffRejected):
        store.consume_ticket(ticket=original, public_host=HOST, now=103)


def test_exchange_preserves_identity_claims_and_rebases_expiry(tmp_path, monkeypatch) -> None:
    store = _make_store(tmp_path, monkeypatch)
    ticket = _ticket(mode="pocketbase", token="pb-bearer-token")
    record = _create(store, ticket, now=100)

    fresh = store.exchange(code=record.code, public_host=HOST, now=200)
    claims = session_handoff.decrypt_ticket_payload(fresh)
    assert claims["mode"] == "pocketbase"
    assert claims["host"] == HOST
    assert claims["token"] == "pb-bearer-token"
    assert claims["exp"] == 200 + TICKET_LIFETIME
    assert fresh != ticket


def test_re_encrypted_same_claims_is_not_the_issued_ticket(tmp_path, monkeypatch) -> None:
    store = _make_store(tmp_path, monkeypatch)
    claims = {"mode": "builtin", "host": HOST, "exp": 10_000}
    original = session_handoff.encrypt_ticket_payload(claims, secret=SECRET)
    duplicate = session_handoff.encrypt_ticket_payload(claims, secret=SECRET)
    assert duplicate != original
    record = _create(store, original, now=100)
    rotated = store.exchange(code=record.code, public_host=HOST, now=101)

    with pytest.raises(session_handoff.HandoffRejected):
        store.consume_ticket(ticket=duplicate, public_host=HOST, now=102)
    with pytest.raises(session_handoff.HandoffRejected):
        store.consume_ticket(ticket=original, public_host=HOST, now=102)
    assert store.consume_ticket(ticket=rotated, public_host=HOST, now=103) == rotated


def test_retention_cleanup_purges_expired_records_and_old_buckets(tmp_path, monkeypatch) -> None:
    store = _make_store(tmp_path, monkeypatch, "retention.sqlite3")
    _create(store, _ticket(), now=100, rate_key="early")

    later = 4_000
    _create(store, _ticket(), now=later, rate_key="late")

    assert _record_count(store) == 1
    with sqlite3.connect(store.db_path) as connection:
        buckets = connection.execute(
            "SELECT bucket, window_start FROM handoff_rate_limits"
        ).fetchall()
    assert buckets == [("create:late", later - later % CREATE_WINDOW)]


@pytest.mark.parametrize("other_host", ["alt.example", "other.example:8443"])
def test_codes_are_distinct_and_cross_host_exchange_is_isolated(
    tmp_path, monkeypatch, other_host: str
) -> None:
    store = _make_store(tmp_path, monkeypatch)
    first = _create(store, _ticket(host=HOST), now=100)
    second = _create(store, _ticket(host=other_host), host=other_host, now=100, rate_key="bob")
    assert first.code != second.code

    with pytest.raises(session_handoff.HandoffRejected):
        store.exchange(code=first.code, public_host=other_host, now=101)
    assert _record_count(store) == 2

    fresh_first = store.exchange(code=first.code, public_host=HOST, now=102)
    fresh_second = store.exchange(code=second.code, public_host=other_host, now=103)
    assert fresh_first != fresh_second
    assert session_handoff.decrypt_ticket_payload(fresh_first)["host"] == HOST
    assert session_handoff.decrypt_ticket_payload(fresh_second)["host"] == other_host


def test_concurrent_exchange_admits_exactly_one_winner(tmp_path, monkeypatch) -> None:
    store = _make_store(tmp_path, monkeypatch)
    record = _create(store, _ticket(), now=100)

    def attempt(_index: int):
        try:
            return store.exchange(code=record.code, public_host=HOST, now=200)
        except session_handoff.HandoffRejected as exc:
            return exc

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(attempt, range(6)))

    tickets = [o for o in outcomes if not isinstance(o, Exception)]
    rejected = [o for o in outcomes if isinstance(o, session_handoff.HandoffRejected)]
    assert len(tickets) == 1
    assert len(rejected) == 5
    fresh = tickets[0]
    assert session_handoff.decrypt_ticket_payload(fresh)["exp"] == 200 + TICKET_LIFETIME
    assert store.consume_ticket(ticket=fresh, public_host=HOST, now=201) == fresh


def test_concurrent_consume_admits_exactly_one_winner(tmp_path, monkeypatch) -> None:
    store = _make_store(tmp_path, monkeypatch)
    record = _create(store, _ticket(), now=100)
    fresh = store.exchange(code=record.code, public_host=HOST, now=200)

    def attempt(_index: int):
        try:
            return store.consume_ticket(ticket=fresh, public_host=HOST, now=201)
        except session_handoff.HandoffRejected as exc:
            return exc

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(attempt, range(6)))

    tickets = [o for o in outcomes if not isinstance(o, Exception)]
    rejected = [o for o in outcomes if isinstance(o, session_handoff.HandoffRejected)]
    assert tickets == [fresh]
    assert len(rejected) == 5


def test_concurrent_create_enforces_quota(tmp_path, monkeypatch) -> None:
    store = _make_store(tmp_path, monkeypatch, "concurrent-create.sqlite3")
    workers = CREATE_LIMIT + 3

    def attempt(_index: int):
        try:
            _create(store, _ticket(), now=1_000, rate_key="alice")
            return "ok"
        except session_handoff.HandoffRateLimited:
            return "limited"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(attempt, range(workers)))

    assert outcomes.count("ok") == CREATE_LIMIT
    assert outcomes.count("limited") == workers - CREATE_LIMIT
