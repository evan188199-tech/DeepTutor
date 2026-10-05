"""Degradation and snapshot-robustness regressions for ``ProgressTracker``.

Every test names the DT-22 risk point it pins down (evidence report
``evidence/todo-scan-2026-10-03/report.md`` §7 / §3):

- ``_notify`` at ``deeptutor/knowledge/progress_tracker.py:103`` — MEDIUM,
  ``asyncio.get_running_loop()`` ``RuntimeError`` is silently swallowed when
  indexing runs outside an event loop (CLI / worker thread).
- ``_notify`` at ``deeptutor/knowledge/progress_tracker.py:105`` — MEDIUM,
  ``ImportError`` of the broadcast module and any other exception on the
  broadcast path are silently swallowed (§3 #1612: silent broadcast failure
  hides indexing progress).

Snapshot guarantees around ``update``/``get_progress`` back the same #1612
"truthful progress" theme: the HIGH site
``deeptutor/api/routers/knowledge.py:3952`` feeds this tracker, so the
persisted snapshot must stay correct even when updates arrive out of
chronological order, readers meet malformed payloads, or a callback fails.

Scope note (deduplication): this file is unit-level only. Router-level
reindex progress handling is covered by ``fix-reindex-progress``
(``tests/api/test_knowledge_router.py``) and websocket fan-out by
``test-websocket-progress`` (``tests/api/test_knowledge_progress_ws.py``);
neither overlaps the assertions here.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import sys

import pytest

from deeptutor.knowledge import progress_events
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.knowledge.progress_tracker import ProgressStage, ProgressTracker
from deeptutor.runtime import mode


def _force_mode(monkeypatch: pytest.MonkeyPatch, run_mode: mode.RunMode) -> None:
    """Pin the run mode without touching the process environment."""
    monkeypatch.delenv("DEEPTUTOR_MODE", raising=False)
    monkeypatch.setattr(mode, "_current_mode", run_mode)


def test_notify_without_running_loop_degrades_and_calls_callbacks(
    tmp_path, monkeypatch
) -> None:
    """DT-22 MEDIUM progress_tracker.py:103.

    Indexing usually runs as a detached task without an event loop. ``_notify``
    must degrade silently (no raise, no broadcast scheduled) and still deliver
    the progress payload to plain callbacks.
    """
    _force_mode(monkeypatch, mode.RunMode.SERVER)

    scheduled: list[tuple[str, dict]] = []

    async def recorded_broadcast(kb_name: str, progress: dict) -> None:
        scheduled.append((kb_name, progress))

    monkeypatch.setattr(progress_events, "broadcast_progress", recorded_broadcast)

    seen: list[dict] = []
    tracker = ProgressTracker("kb", tmp_path)
    tracker.set_callback(seen.append)

    payload = {"stage": "processing_documents", "progress_percent": 25}
    tracker._notify(payload)  # must not raise despite "no running event loop"

    assert scheduled == []  # nothing could be scheduled without a loop
    assert seen == [payload]


def test_notify_with_missing_broadcast_module_degrades_and_calls_callbacks(
    tmp_path, monkeypatch
) -> None:
    """DT-22 MEDIUM progress_tracker.py:105 (ImportError branch).

    When the broadcast module cannot be imported, notification must degrade to
    the plain callbacks instead of raising out of the indexing task.
    """
    _force_mode(monkeypatch, mode.RunMode.SERVER)
    monkeypatch.setitem(sys.modules, "deeptutor.knowledge.progress_events", None)

    seen: list[dict] = []
    tracker = ProgressTracker("kb", tmp_path)
    tracker.set_callback(seen.append)

    payload = {"stage": "processing_file", "progress_percent": 50}
    tracker._notify(payload)  # must not raise on the ImportError path

    assert seen == [payload]


def test_notify_with_failing_broadcast_degrades_and_calls_callbacks(
    tmp_path, monkeypatch
) -> None:
    """DT-22 MEDIUM progress_tracker.py:105 (broadcast raises, §3 #1612).

    A broadcast that explodes must never take the indexing progress update
    down with it: ``_notify`` returns normally and the plain callbacks still
    observe the payload. The scheduled task failure is drained through a
    recording loop exception handler so nothing is left unretrieved.
    """
    _force_mode(monkeypatch, mode.RunMode.SERVER)

    async def broken_broadcast(kb_name: str, progress: dict) -> None:
        raise RuntimeError("websocket hub unavailable")

    monkeypatch.setattr(progress_events, "broadcast_progress", broken_broadcast)

    seen: list[dict] = []
    tracker = ProgressTracker("kb", tmp_path)
    tracker.set_callback(seen.append)

    async def flow() -> list[object]:
        payload = {"stage": "processing_documents", "progress_percent": 10}
        tracker._notify(payload)  # must not raise when the broadcast dies
        # Retrieve the scheduled task's failure deterministically: the
        # broadcast runs inside the loop, _notify itself returns normally.
        scheduled = [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
        ]
        return list(await asyncio.gather(*scheduled, return_exceptions=True))

    def scenario() -> None:
        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(flow())
            assert seen == [
                {"stage": "processing_documents", "progress_percent": 10}
            ]
            assert any(isinstance(result, RuntimeError) for result in results)
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    scenario()


def test_update_snapshot_survives_out_of_order_timestamps(tmp_path, monkeypatch) -> None:
    """Out-of-order updates keep the persisted snapshot truthful (#1612 theme).

    ``update`` unconditionally overwrites ``.progress.json`` with the latest
    call. Even when a later call carries an *older* wall-clock timestamp (a
    clock jump or a re-queued worker), the write must succeed verbatim — no
    merge with the previous snapshot, no rejection — and readers must get the
    last written state back.
    """

    class FakeDatetime(datetime):
        now_value: datetime = datetime(2026, 10, 5, 12, 0, 0)

        @classmethod
        def now(cls, tz=None):  # noqa: ANN001
            return cls.now_value

    tracker = ProgressTracker("kb", tmp_path)
    monkeypatch.setattr(
        "deeptutor.knowledge.progress_tracker.datetime", FakeDatetime
    )

    later = datetime(2026, 10, 5, 12, 5, 0)
    earlier = datetime(2026, 10, 5, 12, 1, 0)

    FakeDatetime.now_value = later
    tracker.update(
        ProgressStage.PROCESSING_FILE,
        "Embedding: 7/10",
        current=7,
        total=10,
        file_name="chapter-3.pdf",
    )

    FakeDatetime.now_value = earlier  # a later call with an older clock
    tracker.update(
        ProgressStage.PROCESSING_DOCUMENTS,
        "Embedding: 3/10",
        current=3,
        total=10,
    )

    with open(tracker.progress_file, encoding="utf-8") as handle:
        payload = json.load(handle)

    # Last write wins, whole snapshot replaced — no leftover file_name/percent.
    assert payload["stage"] == "processing_documents"
    assert payload["progress_percent"] == 30
    assert payload["message"] == "Embedding: 3/10"
    assert payload["timestamp"] == earlier.isoformat()
    assert payload["file_name"] == ""  # whole snapshot replaced, no leftovers

    # The out-of-order timestamp must not break reads either.
    progress = tracker.get_progress()
    assert progress is not None
    assert progress["stage"] == "processing_documents"
    assert progress["timestamp"] == earlier.isoformat()
    datetime.fromisoformat(progress["timestamp"])


def test_get_progress_tolerates_corrupt_snapshot_and_malformed_timestamp(
    tmp_path,
) -> None:
    """Snapshot readers must survive damaged files (#1612 truthful progress).

    A half-written or invalid ``.progress.json`` falls back to the kb_config
    snapshot instead of raising, and a persisted snapshot with a malformed
    ``timestamp`` is still served verbatim — readers never parse or reject
    timestamps, so an abnormal one cannot hide live progress.
    """
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.update_kb_status(
        name="kb",
        status="processing",
        progress={
            "stage": "processing_documents",
            "message": "Recovered from kb_config",
            "percent": 60,
        },
    )
    tracker = ProgressTracker("kb", tmp_path)

    tracker.kb_dir.mkdir(parents=True, exist_ok=True)
    tracker.progress_file.write_bytes(b"{not json")
    fallback = tracker.get_progress()
    assert fallback is not None
    assert fallback["message"] == "Recovered from kb_config"

    damaged = {
        "kb_name": "kb",
        "stage": "processing_documents",
        "message": "still visible",
        "progress_percent": 40,
        "timestamp": "not-a-timestamp",
    }
    tracker.progress_file.write_text(
        json.dumps(damaged), encoding="utf-8"
    )
    served = tracker.get_progress()
    assert served is not None
    assert served["message"] == "still visible"
    assert served["timestamp"] == "not-a-timestamp"


def test_update_persists_snapshot_even_when_a_callback_raises(tmp_path) -> None:
    """A failing callback must not break progress persistence or peers.

    ``_notify`` isolates callback errors (logged at debug level) so that the
    snapshot on disk and the remaining callbacks still see every update —
    the "degrade without raising, file still correct" pair required by the
    DT-22 follow-up tests for progress_tracker.py:103/105.
    """
    seen: list[dict] = []
    tracker = ProgressTracker("kb", tmp_path)
    tracker.set_callback(lambda progress: (_ for _ in ()).throw(RuntimeError("peer down")))
    tracker.set_callback(seen.append)

    tracker.update(
        ProgressStage.PROCESSING_DOCUMENTS,
        "Embedding: 4/8",
        current=4,
        total=8,
    )

    with open(tracker.progress_file, encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["stage"] == "processing_documents"
    assert payload["progress_percent"] == 50

    assert len(seen) == 1
    assert seen[0]["message"] == "Embedding: 4/8"
