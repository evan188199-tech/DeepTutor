"""Lifecycle state machine, failure triage and journal persistence for IndexingRun (#1612).

Focused unit coverage for the head of ``deeptutor/knowledge/indexing_run.py``:
failure classification, journal read/write validation, owner liveness
projection, exit-state triage and recovery handoff. Indexing execution itself
is never started; every scenario journals on temporary files only.
"""

import asyncio
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import threading

import psutil
import pytest

import deeptutor.knowledge.indexing_run as indexing_run
from deeptutor.knowledge.indexing_run import (
    IndexingCancelled,
    IndexingRun,
    _redact,
    current_run,
    failure_code,
    load_run,
    request_cancel,
    visible_run,
)

DEAD_PID = 999999999  # above every realistic pid ceiling, so no live owner matches


def write_journal(kb_dir: Path, **overrides) -> dict:
    data = {
        "schema": 1,
        "task_id": "crashed",
        "action": "rebuild",
        "provider": "",
        "pid": DEAD_PID,
        "process_started_at": None,
        "state": "running",
        "phase": "parsing",
        "started_at": 0.0,
        "last_activity_at": 0.0,
        "last_progress_at": 0.0,
        "documents": {},
        "previous_task_id": None,
        "recovery": "",
        "cancel_requested": False,
        "usable_version": None,
    }
    data.update(overrides)
    (Path(kb_dir) / ".indexing-run.json").write_text(json.dumps(data))
    return data


@pytest.mark.parametrize(
    "exc, expected",
    [
        (TimeoutError(), "timeout"),
        (RuntimeError("request timed out"), "timeout"),
        (MemoryError(), "resource_exhaustion"),
        (RuntimeError("out of memory while embedding"), "resource_exhaustion"),
        (RuntimeError("RESOURCE EXHAUSTED"), "resource_exhaustion"),
        (FileNotFoundError("missing file"), "dependency_missing"),
        (ModuleNotFoundError("no module"), "dependency_missing"),
        (RuntimeError("parser is not installed"), "dependency_missing"),
        (RuntimeError("cli_missing"), "dependency_missing"),
        (RuntimeError("unsupported format"), "unsupported_input"),
        (RuntimeError("this engine doesn't support epub"), "unsupported_input"),
        (RuntimeError("download interrupted"), "model_download_failed"),
        (RuntimeError("embedding provider error"), "embedding_failed"),
        (RuntimeError("vector store unavailable"), "embedding_failed"),
        (RuntimeError("no content extracted"), "invalid_output"),
        (RuntimeError("output was invalid"), "invalid_output"),
        (RuntimeError("mysterious"), "runtime_failure"),
    ],
)
def test_failure_code_mapping(exc, expected):
    assert failure_code(exc) == expected


def test_redact_strips_credentials_and_truncates():
    text = _redact("Bearer abc123 failed with api_key=xyz789 at https://user:pass@host/path")
    assert "abc123" not in text and "xyz789" not in text and "pass@" not in text
    assert "[redacted]" in text
    assert len(_redact("x" * 5000)) == 1600


def test_load_run_validates_journal_and_cancellation(tmp_path):
    assert load_run(tmp_path) is None
    journal = tmp_path / ".indexing-run.json"
    journal.write_text("{broken")
    with pytest.raises(OSError, match="unreadable"):
        load_run(tmp_path)
    for bad in (
        "[]",
        json.dumps({"schema": 2, "documents": {}}),
        json.dumps({"schema": 1, "documents": []}),
        json.dumps({"schema": 1}),
    ):
        journal.write_text(bad)
        with pytest.raises(OSError, match="invalid"):
            load_run(tmp_path)
    write_journal(tmp_path, task_id="live")
    assert load_run(tmp_path)["cancel_requested"] is False
    cancel = tmp_path / ".indexing-cancel.json"
    cancel.write_text(json.dumps({"task_id": "other"}))
    assert load_run(tmp_path)["cancel_requested"] is False
    cancel.write_text(json.dumps({"task_id": "live"}))
    assert load_run(tmp_path)["cancel_requested"] is True
    cancel.write_text("{broken")
    with pytest.raises(OSError, match="cancellation"):
        load_run(tmp_path)


def test_request_cancel_gates_on_owner_and_terminal_state(tmp_path):
    assert request_cancel(tmp_path, "any") is False
    write_journal(tmp_path, task_id="live", state="running")
    assert request_cancel(tmp_path, "other") is False
    assert not (tmp_path / ".indexing-cancel.json").exists()
    assert request_cancel(tmp_path, "live") is True
    cancel = json.loads((tmp_path / ".indexing-cancel.json").read_text())
    assert cancel["task_id"] == "live" and cancel["requested_at"] > 0
    write_journal(tmp_path, task_id="live", state="failed")
    assert request_cancel(tmp_path, "live") is False


def test_visible_run_without_journal_terminal_and_live_owner(tmp_path):
    assert visible_run(tmp_path) is None
    write_journal(tmp_path, state="completed")
    view = visible_run(tmp_path)
    assert view["state"] == "completed"
    assert view["cancel_requested"] is False
    write_journal(
        tmp_path,
        task_id="live",
        state="running",
        pid=os.getpid(),
        process_started_at=psutil.Process().create_time(),
    )
    assert visible_run(tmp_path)["state"] == "running"


def test_visible_run_uses_lock_lease_without_psutil(tmp_path, monkeypatch):
    monkeypatch.setattr(indexing_run, "psutil", None)
    write_journal(tmp_path, state="running", pid=1, documents={"a": {"status": "embedding"}})
    view = visible_run(tmp_path)
    assert view["state"] == "interrupted"
    assert view["documents"]["a"]["status"] == "unknown"
    lock = (tmp_path / ".indexing.lock").open("a+b")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    try:
        assert visible_run(tmp_path)["state"] == "running"
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def test_success_run_persists_completed_state_and_binds_context(tmp_path):
    source = tmp_path / "raw" / "notes.md"
    source.parent.mkdir()
    source.write_text("hello")
    with IndexingRun(tmp_path, [str(source)], provider="test", task_id="ok1") as run:
        assert current_run() is run
        assert load_run(tmp_path)["state"] == "running"
        run.document(source, "completed")
        run.finish("completed", version="v1")
        journal = load_run(tmp_path)
        assert journal["state"] == "completed"
        assert journal["usable_version"] == "v1"
        assert journal["error_code"] is None and journal["error"] is None
    assert current_run() is None
    journal = load_run(tmp_path)
    assert journal["documents"]["notes.md"]["status"] == "completed"
    assert journal["finished_at"] is not None


@pytest.mark.parametrize(
    "error, expected_state, expected_code",
    [
        (RuntimeError("parser exploded"), "failed", "runtime_failure"),
        (TimeoutError("embedding timed out"), "failed", "timeout"),
        (IndexingCancelled("cancellation reached a boundary"), "cancelled", "runtime_failure"),
    ],
)
def test_exit_triage_on_exception_without_usable_version(
    tmp_path, error, expected_state, expected_code
):
    source = tmp_path / "raw" / "book.txt"
    source.parent.mkdir()
    source.write_text("text")
    with pytest.raises(type(error)):
        with IndexingRun(tmp_path, [str(source)], task_id="f1") as run:
            run.phase("parsing", source=source)
            run.document(source, "parsing")
            raise error
    journal = load_run(tmp_path)
    assert journal["state"] == expected_state
    assert journal["error_code"] == expected_code
    assert journal["usable_version"] is None
    assert str(error) in journal["error"]
    assert journal["documents"]["book.txt"]["status"] == "unknown"
    assert journal["current_document"] == "book.txt"


def test_exit_triage_keeps_partial_version_when_late_failure_hits(tmp_path):
    with pytest.raises(RuntimeError, match="late failure"):
        with IndexingRun(tmp_path, [], task_id="p1") as run:
            run.data["usable_version"] = "v-partial"
            raise RuntimeError("late failure")
    journal = load_run(tmp_path)
    assert journal["state"] == "partial"
    assert journal["usable_version"] == "v-partial"


def test_exit_without_exception_or_finish_fails_readiness_gate(tmp_path):
    with IndexingRun(tmp_path, [], task_id="r1"):
        pass
    journal = load_run(tmp_path)
    assert journal["state"] == "failed"
    assert "readiness was not verified" in journal["error"]


def test_interrupted_owner_is_projected_then_recovered_by_new_run(tmp_path):
    source = tmp_path / "raw" / "book.pdf"
    source.parent.mkdir()
    source.write_bytes(b"payload")
    digest = sha256(source.read_bytes()).hexdigest()
    write_journal(
        tmp_path,
        task_id="crashed",
        documents={
            "book.pdf": {"status": "parsing", "source_hash": digest},
            "done.pdf": {"status": "completed", "source_hash": "x"},
        },
    )
    view = visible_run(tmp_path)
    assert view["state"] == "interrupted"
    assert view["documents"]["book.pdf"]["status"] == "unknown"
    assert view["documents"]["done.pdf"]["status"] == "completed"
    assert "Retry reuses" in view["recovery"]
    with IndexingRun(tmp_path, [str(source)], task_id="second") as run:
        assert run.data["previous_task_id"] == "crashed"
        assert run.data["documents"]["book.pdf"]["source_hash"] == digest
        assert run.data["recovery"].startswith("Validated parser caches")
        run.finish("completed", version="v9")
    assert load_run(tmp_path)["state"] == "completed"


def test_stale_owner_cannot_clobber_newer_journal(tmp_path):
    with pytest.raises(RuntimeError, match="owner replaced"):
        with IndexingRun(tmp_path, [], task_id="old") as run:
            write_journal(tmp_path, task_id="new", state="running")
            with pytest.raises(IndexingCancelled):
                run.check()
            with pytest.raises(IndexingCancelled):
                run.phase("parsing")
            before = (tmp_path / ".indexing-run.json").read_bytes()
            run.document(tmp_path / "raw" / "x.txt", "parsing")
            run.finish("failed", error=RuntimeError("boom"))
            assert (tmp_path / ".indexing-run.json").read_bytes() == before
            raise RuntimeError("owner replaced")
    journal = load_run(tmp_path)
    assert journal["task_id"] == "new" and journal["state"] == "running"


def test_document_and_finish_ignore_inactive_run(tmp_path):
    with IndexingRun(tmp_path, [], task_id="d1") as run:
        run.finish("completed")
    before = (tmp_path / ".indexing-run.json").read_bytes()
    run.document(tmp_path / "raw" / "y.txt", "parsing")
    run.finish("cancelled")
    assert (tmp_path / ".indexing-run.json").read_bytes() == before


def test_start_classifies_sources_and_honors_upload_action(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "keep.txt").write_text("hello")
    (raw / "skip.xyz").write_bytes(b"\x00\x01not-text")
    outside = tmp_path / "outside.txt"
    outside.write_text("out")
    with IndexingRun(tmp_path, [str(outside)], action="upload", task_id="u1") as run:
        documents = run.data["documents"]
        key = run.source_key(outside)
        assert set(documents) == {key}
        assert key.startswith("external-") and key.endswith("/outside.txt")
        run.finish("completed")
    with IndexingRun(tmp_path, [str(raw / "keep.txt"), str(raw / "keep.txt")], task_id="u2") as run:
        documents = run.data["documents"]
        assert set(documents) == {"keep.txt", "skip.xyz"}
        assert documents["keep.txt"]["status"] == "pending"
        assert documents["skip.xyz"]["status"] == "excluded"
        assert documents["skip.xyz"]["reason"] == "unsupported_input"
        run.finish("completed")


def test_start_marks_unreadable_source_as_failed_with_redacted_reason(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "locked.txt").write_text("secret-body")

    def broken_hash(source):
        raise PermissionError("api_key=secretvalue denied")

    monkeypatch.setattr(IndexingRun, "_hash", staticmethod(broken_hash))
    with IndexingRun(tmp_path, [str(raw / "locked.txt")], task_id="h1") as run:
        document = run.data["documents"]["locked.txt"]
        assert document["status"] == "failed"
        assert "secretvalue" not in document["reason"]
        assert "[redacted]" in document["reason"]
        run.finish("failed")


def test_phase_updates_progress_only_on_change_and_redacts_activity(tmp_path):
    with IndexingRun(tmp_path, [], task_id="p1") as run:
        run.phase("parsing", current=1, total=3, activity="chunk 1 api_key=abc123")
        journal = load_run(tmp_path)
        assert journal["phase"] == "parsing"
        assert journal["phase_current"] == 1 and journal["phase_total"] == 3
        assert "abc123" not in journal["activity"] and "[redacted]" in journal["activity"]
        progress = journal["last_progress_at"]
        run.phase("parsing", current=1, total=3)
        assert load_run(tmp_path)["last_progress_at"] == progress
        run.finish("completed")


def test_verify_sources_checks_only_completed_stages(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    source = raw / "a.txt"
    source.write_text("v1")
    excluded = raw / "b.xyz"
    excluded.write_bytes(b"\x00\x01bin")
    with IndexingRun(tmp_path, [str(source), str(excluded)], task_id="v1") as run:
        run.document(source, "completed")
        excluded.write_text("mutated")
        run.verify_sources()
        source.write_text("v2")
        with pytest.raises(RuntimeError, match="Source changed"):
            run.verify_sources()
        run.finish("failed")


def test_reporter_receives_snapshots_and_failure_is_swallowed(tmp_path):
    snapshots = []

    def reporter(snapshot):
        snapshots.append(snapshot)

    with IndexingRun(tmp_path, [], reporter=reporter, task_id="rep1") as run:
        run.finish("completed")
    assert snapshots and snapshots[-1]["state"] == "completed"
    assert load_run(tmp_path)["state"] == "completed"

    def broken(snapshot):
        raise RuntimeError("webhook down")

    with IndexingRun(tmp_path, [], reporter=broken, task_id="rep2") as run:
        run.finish("completed")
    journal = load_run(tmp_path)
    assert journal["task_id"] == "rep2" and journal["state"] == "completed"


@pytest.mark.asyncio
async def test_async_run_binds_current_and_persists_completion(tmp_path):
    async with IndexingRun(tmp_path, [], task_id="a1") as run:
        assert current_run() is run
        run.finish("completed", version="v1")
    assert current_run() is None
    journal = load_run(tmp_path)
    assert journal["state"] == "completed" and journal["usable_version"] == "v1"


@pytest.mark.asyncio
async def test_async_start_cancellation_finalizes_as_cancelled_and_releases_lock(tmp_path):
    started = threading.Event()
    gate = threading.Event()

    class GatedRun(IndexingRun):
        def _start(self, bind_context=True):
            started.set()
            assert gate.wait(timeout=10)
            return super()._start(bind_context)

    run = GatedRun(tmp_path, [], task_id="g1")
    task = asyncio.create_task(run.__aenter__())
    for _ in range(500):
        if started.is_set():
            break
        await asyncio.sleep(0.01)
    assert started.is_set()
    task.cancel()
    gate.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert load_run(tmp_path)["state"] == "cancelled"
    with IndexingRun(tmp_path, [], task_id="g2") as follower:
        follower.finish("completed")
    assert load_run(tmp_path)["task_id"] == "g2"
