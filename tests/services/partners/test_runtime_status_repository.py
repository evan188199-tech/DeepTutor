"""PartnerRuntimeStatusRepository: upsert idempotency, missing-table recovery, WAL concurrency."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
from types import SimpleNamespace

from deeptutor.services.partners import runtime_status
from deeptutor.services.partners.runtime_status import PartnerRuntimeStatusRepository

_TABLE = "partner_runtime_status"


def _row(path, partner_id: str):
    connection = sqlite3.connect(path)
    try:
        return connection.execute(
            f"SELECT owner_id, running, state, started_at, updated_at FROM {_TABLE}"
            " WHERE partner_id=?",
            (partner_id,),
        ).fetchone()
    finally:
        connection.close()


def test_repository_initializes_wal_schema_at_nested_path(tmp_path) -> None:
    path = tmp_path / "deep" / "nested" / "status.sqlite3"
    repo = PartnerRuntimeStatusRepository(path)

    assert path.exists()
    connection = sqlite3.connect(path)
    try:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({_TABLE})")}
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        connection.close()
    assert {
        "partner_id",
        "owner_id",
        "running",
        "state",
        "started_at",
        "last_reload_error",
        "payload",
        "updated_at",
    } <= columns
    assert str(mode).lower() == "wal"


def test_repeated_set_with_same_values_is_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runtime_status, "time", SimpleNamespace(time=lambda: 1_700_000_000.0))
    repo = PartnerRuntimeStatusRepository(tmp_path / "status.sqlite3")

    written = [
        repo.set(
            "ada",
            owner_id="worker-a",
            running=True,
            state="running",
            payload={"name": "Ada"},
            started_at="2026-09-01T12:00:00",
        )
        for _ in range(3)
    ]

    assert written[0] == written[1] == written[2]
    rows = sqlite3.connect(repo.path).execute(f"SELECT COUNT(*) FROM {_TABLE}").fetchone()[0]
    assert rows == 1
    row = _row(repo.path, "ada")
    assert row == ("worker-a", 1, "running", "2026-09-01T12:00:00", 1_700_000_000.0)
    assert repo.get("ada") == written[0]


def test_set_overwrites_previous_owner_and_clears_reload_error(tmp_path) -> None:
    repo = PartnerRuntimeStatusRepository(tmp_path / "status.sqlite3")

    repo.set("ada", owner_id="worker-a", running=True, state="running", payload={"name": "Ada"})
    repo.set(
        "ada",
        owner_id="worker-b",
        running=False,
        state="reload_failed",
        last_reload_error="boom",
        payload={"name": "Ada v2"},
    )
    status = repo.get("ada")
    assert status is not None
    assert status["runtime_owner_id"] == "worker-b"
    assert status["running"] is False
    assert status["runtime_state"] == "reload_failed"
    assert status["name"] == "Ada v2"
    assert status["last_reload_error"] == "boom"
    assert repo.list() == {"ada": status}

    repo.set("ada", owner_id="worker-b", running=True, state="running", payload={"name": "Ada v2"})
    recovered = repo.get("ada")
    assert recovered is not None
    assert recovered["last_reload_error"] is None
    assert recovered["runtime_state"] == "running"
    count = sqlite3.connect(repo.path).execute(f"SELECT COUNT(*) FROM {_TABLE}").fetchone()[0]
    assert count == 1


def test_constructor_recreates_missing_table(tmp_path) -> None:
    path = tmp_path / "status.sqlite3"
    first = PartnerRuntimeStatusRepository(path)
    first.set("ada", owner_id="worker-a", running=True, state="running")

    connection = sqlite3.connect(path)
    try:
        connection.execute(f"DROP TABLE {_TABLE}")
        connection.commit()
    finally:
        connection.close()

    reopened = PartnerRuntimeStatusRepository(path)
    assert reopened.get("ada") is None
    assert reopened.list() == {}
    reopened.set("ada", owner_id="worker-b", running=False, state="stopped")
    status = reopened.get("ada")
    assert status is not None
    assert status["runtime_owner_id"] == "worker-b"


def test_get_missing_and_delete_missing_are_noops(tmp_path) -> None:
    repo = PartnerRuntimeStatusRepository(tmp_path / "status.sqlite3")

    assert repo.get("ghost") is None
    repo.delete("ghost")
    assert repo.list() == {}


def test_concurrent_writers_and_readers_stay_consistent(tmp_path) -> None:
    repo = PartnerRuntimeStatusRepository(tmp_path / "status.sqlite3")
    partner_ids = [f"p{index}" for index in range(8)]

    def writer(partner_id: str) -> None:
        for seq in range(15):
            running = seq % 2 == 0
            repo.set(
                partner_id,
                owner_id=f"owner-{partner_id}",
                running=running,
                state="running" if running else "stopped",
                payload={"seq": seq},
            )

    with ThreadPoolExecutor(max_workers=len(partner_ids)) as pool:
        writer_futures = [pool.submit(writer, partner_id) for partner_id in partner_ids]
        reader_futures = [pool.submit(repo.list) for _ in range(40)]
        for future in writer_futures + reader_futures:
            future.result()

    snapshot = repo.list()
    assert set(snapshot) == set(partner_ids)
    for partner_id in partner_ids:
        status = repo.get(partner_id)
        assert status is not None
        assert status["runtime_owner_id"] == f"owner-{partner_id}"
        assert status["seq"] == snapshot[partner_id]["seq"]


def test_concurrent_overwrites_of_same_partner_end_consistent(tmp_path) -> None:
    repo = PartnerRuntimeStatusRepository(tmp_path / "status.sqlite3")
    owner_tags = [f"owner-{index}" for index in range(6)]

    def overwrite(tag: str) -> None:
        for seq in range(10):
            repo.set(
                "ada",
                owner_id=tag,
                running=True,
                state=f"state-{seq}",
                payload={"seq": seq, "writer": tag},
            )

    with ThreadPoolExecutor(max_workers=len(owner_tags)) as pool:
        for future in [pool.submit(overwrite, tag) for tag in owner_tags]:
            future.result()

    status = repo.get("ada")
    assert status is not None
    assert status["runtime_owner_id"] in owner_tags
    row = (
        sqlite3.connect(repo.path)
        .execute(
            f"SELECT owner_id, state, payload FROM {_TABLE} WHERE partner_id=?",
            ("ada",),
        )
        .fetchone()
    )
    assert row is not None
    assert row[0] == status["runtime_owner_id"]
    assert row[1] == status["runtime_state"]
    assert json.loads(row[2]) == status


def test_process_wide_repository_is_cached(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runtime_status, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(runtime_status, "_repository", None)

    first = runtime_status.get_partner_runtime_status_repository()
    second = runtime_status.get_partner_runtime_status_repository()

    assert first is second
    assert first.path == (tmp_path / "_runtime" / "status.sqlite3").resolve()
