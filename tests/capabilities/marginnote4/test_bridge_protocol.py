from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

import pytest

from deeptutor.capabilities.marginnote4 import bridge as bridge_module
from deeptutor.capabilities.marginnote4.bridge import (
    BridgeJournal,
    BridgeRunner,
    BulkDeleteSafety,
    objects_from_notebook,
    plan_sync,
)
from deeptutor.capabilities.marginnote4.data.export_adapter import ExportAdapter
from deeptutor.capabilities.marginnote4.models import NOTE, MarginNoteObject, SyncBatch
from deeptutor.capabilities.marginnote4.store import (
    BulkDeleteGuard,
    MarginNoteStore,
    PairingError,
    SyncConflict,
    WritebackStateError,
)


def _obj(object_id: str) -> MarginNoteObject:
    return MarginNoteObject(
        object_id=object_id,
        object_type=NOTE,
        title=f"Title {object_id}",
        content=f"Content {object_id}",
        device_id="dev1",
    )


def _notebook(root: Path) -> None:
    (root / "doc.md").write_text("# Section\n\n> quoted text\n\na note\n", encoding="utf-8")


def test_pairing_code_expires_and_cannot_be_replayed(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "store.db")
    issued = store.create_pairing_code(user_id="u1", kb_id="kb1", kb_name="notes", ttl_seconds=60)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE mn4_pairing_codes SET expires_at = ? WHERE code_hash = ?",
            ("2000-01-01T00:00:00+00:00", issued.code and _sha(issued.code)),
        )
    with pytest.raises(PairingError, match="expired"):
        store.pair_device(issued.code)


def _sha(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()


def test_sync_batch_is_idempotent_and_rejects_cursor_mismatch(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "store.db")
    batch = SyncBatch(
        device_id="dev1",
        sync_id="sync-1",
        sequence=1,
        base_cursor="",
        snapshot_hash="hash-a",
        objects=[_obj("one")],
    )
    first = store.ingest(batch)
    replay = store.ingest(batch)
    assert first.new_cursor == replay.new_cursor
    assert store.count(device_id="dev1") == 1
    stale = SyncBatch(
        device_id="dev1",
        sync_id="sync-2",
        sequence=2,
        base_cursor="wrong",
        snapshot_hash="hash-b",
        objects=[_obj("two")],
    )
    with pytest.raises(SyncConflict, match="cursor"):
        store.ingest(stale)


def test_bulk_deletion_guard_blocks_more_than_25_percent(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "store.db")
    store.ingest(
        SyncBatch(
            device_id="dev1",
            sync_id="sync-1",
            sequence=1,
            snapshot_hash="a",
            objects=[_obj(str(i)) for i in range(4)],
        )
    )
    batch = SyncBatch(
        device_id="dev1",
        sync_id="sync-2",
        sequence=2,
        base_cursor=store.get_cursor("dev1"),
        snapshot_hash="b",
        deleted_ids=["0", "1"],
    )
    with pytest.raises(BulkDeleteGuard):
        store.ingest(batch)


def test_local_deletion_requires_two_stable_scans(tmp_path: Path) -> None:
    root = tmp_path / "exports"
    root.mkdir()
    for index in range(5):
        (root / f"doc{index}.md").write_text(
            f"# Section {index}\n\n> quoted text {index}\n\na note {index}\n",
            encoding="utf-8",
        )
    journal = BridgeJournal(tmp_path / "journal.db")
    first = plan_sync(root, journal)
    assert first.deleted_ids == []
    assert first.objects
    journal.commit_sync(
        objects={obj.object_id: obj.object_hash for obj in first.objects},
        deleted_ids=[],
        sequence=1,
        cursor="1:a",
        sync_id="sync-1",
    )
    (root / "doc2.md").unlink()
    assert plan_sync(root, journal).deleted_ids == []
    second = plan_sync(root, journal)
    assert second.deleted_ids


def test_bulk_local_deletion_pauses(tmp_path: Path) -> None:
    root = tmp_path / "exports"
    root.mkdir()
    for index in range(4):
        (root / f"doc{index}.md").write_text(f"# Doc\n\n> quote {index}\n", encoding="utf-8")
    journal = BridgeJournal(tmp_path / "journal.db")
    first = plan_sync(root, journal)
    journal.commit_sync(
        objects={obj.object_id: obj.object_hash for obj in first.objects},
        deleted_ids=[],
        sequence=1,
        cursor="1:a",
        sync_id="sync-1",
    )
    for path in root.glob("*.md"):
        path.unlink()
    with pytest.raises(BulkDeleteSafety):
        plan_sync(root, journal)


def test_writeback_lease_and_receipt_transitions(tmp_path: Path) -> None:
    from deeptutor.capabilities.marginnote4.models import WritebackPayload

    store = MarginNoteStore(tmp_path / "store.db")
    task = store.create_writeback(
        user_id="u1",
        kb_id="kb1",
        payload=WritebackPayload(title="Title", markdown="Body", source_refs=["obj:1"]),
    )
    store.approve_writeback(task["writeback_id"], user_id="u1")
    store.install_device(
        device_id="dev1",
        user_id="u1",
        kb_id="kb1",
        kb_name="notes",
        device_name="Mac",
        device_kind="macos",
        token="secret",
    )
    claimed = store.claim_writeback(device_id="dev1", lease_ttl_seconds=60)
    assert claimed is not None and claimed["delivery_mode"] == "import_queue"
    receipt = {
        "device_id": "dev1",
        "lease_token": claimed["lease"]["token"],
        "result": "awaiting_import",
        "payload_hash": claimed["payload_hash"],
        "delivery_mode": claimed["delivery_mode"],
        "provider": "import_queue",
        "written_at": "2026-01-01T00:00:00+00:00",
    }
    updated = store.complete_writeback(claimed["writeback_id"], **receipt)
    assert updated["status"] == "awaiting_import"
    assert store.mark_imported(claimed["writeback_id"], user_id="u1")["status"] == "imported"
    with pytest.raises(WritebackStateError):
        store.renew_writeback(
            claimed["writeback_id"],
            device_id="dev1",
            lease_token=claimed["lease"]["token"],
        )


def test_expired_lease_returns_to_approved(tmp_path: Path) -> None:
    from datetime import datetime, timedelta, timezone

    from deeptutor.capabilities.marginnote4.models import WritebackPayload

    store = MarginNoteStore(tmp_path / "store.db")
    task = store.create_writeback(
        user_id="u1", kb_id="kb1", payload=WritebackPayload(title="T", markdown="B")
    )
    store.approve_writeback(task["writeback_id"], user_id="u1")
    store.install_device(
        device_id="dev1",
        user_id="u1",
        kb_id="kb1",
        kb_name="notes",
        device_name="Mac",
        device_kind="macos",
        token="secret",
    )
    first = store.claim_writeback(device_id="dev1")
    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE mn4_writebacks SET lease_expires_at = ? WHERE writeback_id = ?",
            (expired, first["writeback_id"]),
        )
    second = store.claim_writeback(device_id="dev1")
    assert second["writeback_id"] == first["writeback_id"]
    assert second["lease"]["token"] != first["lease"]["token"]


def test_automation_verification_is_version_and_config_bound(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "store.db")
    store.install_device(
        device_id="dev1",
        user_id="u1",
        kb_id="kb1",
        kb_name="notes",
        device_name="Mac",
        device_kind="macos",
        token="secret",
    )
    kwargs = {
        "device_id": "dev1",
        "provider": "applescript",
        "bundle_id": "com.marginnote.MarginNote4",
        "app_version": "4.2",
        "config_hash": "cfg",
    }
    store.set_automation_verification(**kwargs, test_external_id="note")
    assert store.is_automation_verified(**kwargs) is True
    assert store.is_automation_verified(**{**kwargs, "app_version": "4.3"}) is False


def test_automation_writeback_rechecks_device_verification() -> None:
    from deeptutor.capabilities.marginnote4 import bridge as bridge_module

    class FakeJournal:
        def writeback_receipt(self, _payload_hash: str) -> None:
            return None

        def record_writeback(self, **_kwargs: Any) -> None:
            raise AssertionError("A failed delivery must not become a durable receipt")

    class FakeClient:
        def __init__(self) -> None:
            self.completed: dict[str, Any] | None = None

        def claim(self, _device_id: str, _token: str) -> dict[str, Any]:
            return {
                "writeback_id": "wb1",
                "title": "Title",
                "markdown": "Body",
                "tags": [],
                "target_notebook": "",
                "payload_hash": "hash",
                "delivery_mode": "automation",
                "last_error": "",
                "lease": {"token": "lease"},
            }

        def automation_status(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {"verified": False, "reason": "stale version"}

        def complete(self, _device_id: str, _token: str, receipt: dict[str, Any]) -> dict[str, Any]:
            self.completed = receipt
            return {}

    original_token = bridge_module.load_token
    bridge_module.load_token = lambda _config: "secret"
    try:
        runner = object.__new__(BridgeRunner)
        runner.config = object()
        runner.journal = FakeJournal()
        runner.client = FakeClient()
        runner.device_id = "dev1"
        runner.data = {
            "notebook_path": "/unused",
            "automation_provider": "url_scheme",
            "url_action_template": "marginnote4://note?title={title}",
        }
        result = runner.writebacks_once()
    finally:
        bridge_module.load_token = original_token

    assert result["result"] == "failed"
    assert runner.client.completed is not None
    assert "stale version" in runner.client.completed["error"]


def test_large_sync_sends_deletions_only_on_final_batch(tmp_path: Path) -> None:
    root = tmp_path / "exports"
    root.mkdir()
    for index in range(101):
        (root / f"doc{index}.md").write_text(
            f"# Doc {index}\n\n> quote {index}\n\nnote {index}\n", encoding="utf-8"
        )
    journal = BridgeJournal(tmp_path / "journal.db")

    class FakeClient:
        def __init__(self) -> None:
            self.batches: list[Any] = []

        def sync(self, batch: Any, _token: str) -> dict[str, Any]:
            self.batches.append(batch)
            return {"new_cursor": f"{batch.sequence}:snapshot"}

    client = FakeClient()
    runner = object.__new__(BridgeRunner)
    runner.config = object()
    runner.journal = journal
    runner.client = client
    runner.device_id = "dev1"
    runner.data = {"notebook_path": str(root)}
    original_token = bridge_module.load_token
    bridge_module.load_token = lambda _config: "secret"
    try:
        first = runner.sync_once()
        (root / "doc50.md").unlink()
        assert runner.sync_once()["deleted"] == 0
        deletion = runner.sync_once()
        second = runner.sync_once()
    finally:
        bridge_module.load_token = original_token

    assert first["changed"] > 100
    assert deletion["deleted"] == 3
    assert second["changed"] == 0
    assert second["deleted"] == 0
    assert len(client.batches) == 5
    assert all(not batch.deleted_ids for batch in client.batches[:-1])
    assert len(client.batches[-1].deleted_ids) == 3
