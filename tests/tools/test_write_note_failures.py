"""Boundary / failure-path tests for the ``write_note`` tool.

Complements ``tests/tools/test_write_note.py`` (main paths) with:

* invalid inputs and odd argument shapes,
* storage-layer write failures (ENOSPC / permission denied / conflicts),
* repeated-write and concurrent-write semantics against a mocked,
  thread-safe in-memory notebook store (never touches a real user dir).
"""

from __future__ import annotations

import concurrent.futures
import errno
import threading

from deeptutor.tools.write_note import (
    MAX_CONTENT_CHARS,
    MAX_NOTE_CHARS,
    MAX_TITLE_CHARS,
    write_note,
)


class _StoreManager:
    """Thread-safe in-memory stand-in for the notebook file layer.

    Simulates create-record, read-record and update-record semantics,
    plus injectable transient failures, without any real filesystem use.
    """

    def __init__(
        self,
        *,
        add_failures: int = 0,
        add_failure_factory=None,
        fail_get_record: bool = False,
        update_failures: int = 0,
        update_failure_factory=None,
    ):
        self._lock = threading.Lock()
        self._notebooks = [{"id": "nb-1", "name": "N"}]
        self._records: dict[str, list[dict]] = {}
        self._next_id = 0
        self._add_failures = add_failures
        self._add_failure_factory = add_failure_factory
        self._fail_get_record = fail_get_record
        self._update_failures = update_failures
        self._update_failure_factory = update_failure_factory
        self.list_calls = 0
        self.add_calls = 0

    def seed_record(self, record_id: str, **fields) -> None:
        with self._lock:
            self._records.setdefault("nb-1", []).append({"id": record_id, **fields})

    def list_notebooks(self):
        with self._lock:
            self.list_calls += 1
            return [dict(nb) for nb in self._notebooks]

    def get_record(self, notebook_id, record_id):
        with self._lock:
            if self._fail_get_record:
                raise OSError(errno.EIO, "notebook file unreadable")
            for rec in self._records.get(notebook_id, []):
                if rec["id"] == record_id:
                    return dict(rec)
        return None

    def add_record(self, **kwargs):
        with self._lock:
            self.add_calls += 1
            if self._add_failures > 0:
                self._add_failures -= 1
                raise self._add_failure_factory()
            self._next_id += 1
            record = {
                "id": f"rec-{self._next_id}",
                "title": kwargs.get("title", ""),
                "output": kwargs.get("output", ""),
                "summary": kwargs.get("summary", ""),
                "user_query": kwargs.get("user_query", ""),
            }
            for nb_id in kwargs["notebook_ids"]:
                self._records.setdefault(nb_id, []).append(dict(record))
            return {
                "record": {"id": record["id"]},
                "added_to_notebooks": list(kwargs["notebook_ids"]),
            }

    def update_record(self, notebook_id, record_id, **kwargs):
        with self._lock:
            if self._update_failures > 0:
                self._update_failures -= 1
                raise self._update_failure_factory()
            for rec in self._records.get(notebook_id, []):
                if rec["id"] == record_id:
                    rec.update(kwargs)
                    return dict(rec)
        return None

    def records(self, notebook_id="nb-1"):
        with self._lock:
            return [dict(rec) for rec in self._records.get(notebook_id, [])]



_HISTORY = [
    {"role": "user", "content": "What is a vector?"},
    {"role": "assistant", "content": "A vector is..."},
    {"role": "user", "content": "And a tensor?"},
    {"role": "assistant", "content": "A tensor generalises..."},
]


# ---------------------------------------------------------------------------
# Invalid inputs and odd argument shapes
# ---------------------------------------------------------------------------


def test_mode_is_normalised_but_empty_mode_rejected() -> None:
    ok_manager = _StoreManager()
    outcome = write_note(
        mode="  APPEND  ",
        notebook_id="nb-1",
        title="t",
        content="body",
        notebook_manager=ok_manager,
    )
    assert outcome.ok is True
    assert outcome.mode == "append"

    ok_manager = _StoreManager()
    ok_manager.seed_record("r1", title="old")
    outcome = write_note(
        mode=" Edit ",
        notebook_id="nb-1",
        record_id="r1",
        title="new",
        notebook_manager=ok_manager,
    )
    assert outcome.ok is True
    assert outcome.mode == "edit"

    outcome = write_note(mode="   ", notebook_id="nb-1", notebook_manager=_StoreManager())
    assert outcome.ok is False
    assert "Unknown mode" in outcome.error


def test_blank_notebook_id_rejected_before_listing_notebooks() -> None:
    manager = _StoreManager()
    for blank in ("", "   ", None):
        outcome = write_note(
            mode="append",
            notebook_id=blank,
            title="t",
            content="body",
            notebook_manager=manager,
        )
        assert outcome.ok is False
        assert outcome.error == "notebook_id is required."
    assert manager.list_calls == 0


def test_append_renders_multimodal_history_and_skips_empty_entries() -> None:
    manager = _StoreManager()
    history = [
        {"role": "system", "content": "be helpful"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "hello"},
                {"type": "image_url", "image_url": "http://example/img.png"},
            ],
        },
        {"role": "assistant", "content": ""},
        {"role": "assistant", "content": [{"type": "text", "text": "hi there"}]},
        {"role": "user", "content": "second question"},
    ]
    outcome = write_note(
        mode="append",
        notebook_id="nb-1",
        title="t",
        conversation_history=history,
        current_user_message="",
        notebook_manager=manager,
    )
    assert outcome.ok is True
    add = manager.records()[0]
    body = add["output"]
    assert "hello" in body
    assert "hi there" in body
    assert "be helpful" not in body
    assert "http://example/img.png" not in body
    # user_query falls back to the last non-empty user message when the
    # current message is empty.
    assert add["user_query"] == "second question"


def test_append_turns_coercion_edge_values() -> None:
    manager = _StoreManager()
    outcome = write_note(
        mode="append",
        notebook_id="nb-1",
        title="latest only",
        turns_to_include=0,
        conversation_history=_HISTORY,
        notebook_manager=manager,
    )
    assert outcome.ok is True
    body = manager.records()[0]["output"]
    assert "And a tensor?" in body
    assert "What is a vector?" not in body

    manager = _StoreManager()
    outcome = write_note(
        mode="append",
        notebook_id="nb-1",
        title="garbage falls back to default",
        turns_to_include="not-a-number",
        conversation_history=_HISTORY,
        notebook_manager=manager,
    )
    assert outcome.ok is True
    body = manager.records()[0]["output"]
    assert "What is a vector?" in body
    assert "And a tensor?" in body

    manager = _StoreManager()
    outcome = write_note(
        mode="append",
        notebook_id="nb-1",
        title="case-insensitive sentinel",
        turns_to_include="ALL",
        conversation_history=_HISTORY,
        current_user_message="current question",
        notebook_manager=manager,
    )
    assert outcome.ok is True
    body = manager.records()[0]["output"]
    assert "What is a vector?" in body
    assert "current question" in body


def test_append_truncates_oversized_body_with_marker() -> None:
    manager = _StoreManager()
    oversized = "x" * (MAX_CONTENT_CHARS + 10)
    outcome = write_note(
        mode="append",
        notebook_id="nb-1",
        title="t",
        content=oversized,
        notebook_manager=manager,
    )
    assert outcome.ok is True
    body = manager.records()[0]["output"]
    assert body.endswith("\n…[truncated]")
    assert len(body) <= MAX_CONTENT_CHARS + len("\n…[truncated]")


def test_edit_truncates_each_oversized_field() -> None:
    manager = _StoreManager()
    manager.seed_record("r1", title="old", output="old body")
    outcome = write_note(
        mode="edit",
        notebook_id="nb-1",
        record_id="r1",
        title="t" * (MAX_TITLE_CHARS + 50),
        content="c" * (MAX_CONTENT_CHARS + 10),
        note="n" * (MAX_NOTE_CHARS + 100),
        notebook_manager=manager,
    )
    assert outcome.ok is True
    stored = manager.get_record("nb-1", "r1")
    assert stored["title"].endswith("…")
    assert len(stored["title"]) <= MAX_TITLE_CHARS + 1
    assert stored["output"].endswith("\n…[truncated]")
    assert len(stored["output"]) <= MAX_CONTENT_CHARS + len("\n…[truncated]")
    assert stored["summary"].endswith("…")
    assert len(stored["summary"]) <= MAX_NOTE_CHARS + 1


# ---------------------------------------------------------------------------
# Storage write failures
# ---------------------------------------------------------------------------


def test_append_enospc_maps_to_save_failed_outcome() -> None:
    manager = _StoreManager(
        add_failures=1,
        add_failure_factory=lambda: OSError(errno.ENOSPC, "No space left on device"),
    )
    outcome = write_note(
        mode="append",
        notebook_id="nb-1",
        title="t",
        content="body",
        notebook_manager=manager,
    )
    assert outcome.ok is False
    assert outcome.mode == "append"
    assert outcome.record_id == ""
    assert "Save failed" in outcome.error
    assert "No space left on device" in outcome.error
    assert manager.records() == []


def test_append_permission_error_maps_to_save_failed_outcome() -> None:
    manager = _StoreManager(
        add_failures=1,
        add_failure_factory=lambda: PermissionError(errno.EACCES, "Permission denied"),
    )
    outcome = write_note(
        mode="append",
        notebook_id="nb-1",
        title="t",
        content="body",
        notebook_manager=manager,
    )
    assert outcome.ok is False
    assert "Save failed" in outcome.error
    assert "Permission denied" in outcome.error
    assert manager.records() == []


def test_edit_update_enospc_maps_to_edit_failed_outcome() -> None:
    manager = _StoreManager(
        update_failures=1,
        update_failure_factory=lambda: OSError(errno.ENOSPC, "No space left on device"),
    )
    manager.seed_record("r1", title="old")
    outcome = write_note(
        mode="edit",
        notebook_id="nb-1",
        record_id="r1",
        title="new",
        notebook_manager=manager,
    )
    assert outcome.ok is False
    assert "Edit failed" in outcome.error
    assert "No space left on device" in outcome.error
    assert manager.get_record("nb-1", "r1")["title"] == "old"


def test_edit_unreadable_notebook_maps_to_could_not_read_outcome() -> None:
    manager = _StoreManager(fail_get_record=True)
    manager.seed_record("r1", title="old")
    outcome = write_note(
        mode="edit",
        notebook_id="nb-1",
        record_id="r1",
        title="new",
        notebook_manager=manager,
    )
    assert outcome.ok is False
    assert "Could not read notebook" in outcome.error
    assert outcome.record_id == ""


def test_append_recovers_after_transient_write_failure() -> None:
    manager = _StoreManager(
        add_failures=1,
        add_failure_factory=lambda: OSError(errno.ENOSPC, "No space left on device"),
    )
    first = write_note(
        mode="append",
        notebook_id="nb-1",
        title="first try",
        content="body",
        notebook_manager=manager,
    )
    second = write_note(
        mode="append",
        notebook_id="nb-1",
        title="second try",
        content="body",
        notebook_manager=manager,
    )
    assert first.ok is False
    assert second.ok is True
    assert second.record_id != ""
    stored = manager.records()
    assert [rec["title"] for rec in stored] == ["second try"]


# ---------------------------------------------------------------------------
# Repeated / concurrent writes (mocked store semantics)
# ---------------------------------------------------------------------------


def test_repeated_append_same_payload_creates_distinct_records() -> None:
    """Append mode is create-only: a duplicate call never upserts."""
    manager = _StoreManager()
    for _ in range(2):
        outcome = write_note(
            mode="append",
            notebook_id="nb-1",
            title="same title",
            content="same body",
            notebook_manager=manager,
        )
        assert outcome.ok is True
    stored = manager.records()
    assert len(stored) == 2
    assert stored[0]["id"] != stored[1]["id"]


def test_append_duplicate_key_conflict_surfaces_as_save_failed() -> None:
    manager = _StoreManager(
        add_failures=1,
        add_failure_factory=lambda: ValueError("duplicate record key"),
    )
    outcome = write_note(
        mode="append",
        notebook_id="nb-1",
        title="dup",
        content="body",
        notebook_manager=manager,
    )
    assert outcome.ok is False
    assert "Save failed" in outcome.error
    assert manager.records() == []


def test_concurrent_appends_all_land_with_unique_ids() -> None:
    manager = _StoreManager()

    def _append(i: int):
        return write_note(
            mode="append",
            notebook_id="nb-1",
            title=f"concurrent-{i}",
            content=f"body-{i}",
            notebook_manager=manager,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(_append, range(8)))

    assert len(outcomes) == 8
    assert all(o.ok for o in outcomes)
    record_ids = {o.record_id for o in outcomes}
    assert len(record_ids) == 8
    stored = manager.records()
    assert {rec["id"] for rec in stored} == record_ids
    assert {rec["title"] for rec in stored} == {f"concurrent-{i}" for i in range(8)}


def test_concurrent_edits_of_same_record_last_writer_wins() -> None:
    manager = _StoreManager()
    manager.seed_record("r1", title="original")

    def _edit(i: int):
        return write_note(
            mode="edit",
            notebook_id="nb-1",
            record_id="r1",
            title=f"edited-{i}",
            notebook_manager=manager,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(_edit, range(8)))

    assert len(outcomes) == 8
    assert all(o.ok for o in outcomes)
    stored = manager.get_record("nb-1", "r1")
    assert stored["title"] in {f"edited-{i}" for i in range(8)}
    assert stored["title"] != "original"
