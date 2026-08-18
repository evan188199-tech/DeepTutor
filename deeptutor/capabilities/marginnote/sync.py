"""Local MarginNote sync coordinator.

The browser talks only to DeepTutor. This process watches an allowed local
export folder, keeps an incremental cursor, and queues writes for import
unless an official write API has been verified.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from deeptutor.capabilities.marginnote.data import AdapterError, WRITEBACK_DIRNAME, open_adapter
from deeptutor.capabilities.marginnote.data.diagnostics import (
    PUBLIC_ADAPTERS,
    SYNC_STATUSES,
    WRITE_MODE_IMPORT_QUEUE,
    display_name_for,
)
from deeptutor.capabilities.marginnote.official import probe_official_write_interface
from deeptutor.capabilities.marginnote.probe import probe_marginnote
from deeptutor.services.file_io import atomic_write_json

logger = logging.getLogger(__name__)

Listener = Callable[[dict[str, Any]], None]

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_coordinators: dict[str, "MarginNoteSyncCoordinator"] = {}
_registry_lock = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_kb_name(name: str) -> str:
    cleaned = _SAFE_NAME.sub("_", (name or "").strip()) or "notebook"
    return cleaned[:80]


def _state_path(kb_name: str) -> Path:
    from deeptutor.services.path_service import get_path_service

    root = get_path_service().get_user_root() / "marginnote_sync"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{_safe_kb_name(kb_name)}.json"


@dataclass
class WriteQueueItem:
    id: str
    rel_path: str
    kind: str
    status: str
    created_at: str
    content_hash: str
    official_write: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SyncConflict:
    id: str
    rel_path: str
    reason: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MarginNoteSyncCoordinator:
    """Watch one connected notebook and expose incremental status."""

    def __init__(
        self,
        kb_name: str,
        notebook_path: str,
        *,
        adapter: str = "export",
        writeback_path: str = "",
        poll_interval: float = 1.5,
    ) -> None:
        self.kb_name = kb_name
        self.notebook_path = notebook_path
        self.adapter_name = (adapter or "export").strip().lower() or "export"
        self.writeback_path = writeback_path
        self.poll_interval = max(0.5, float(poll_interval))
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._listeners: list[Listener] = []
        self._status = "disconnected"
        self._cursor = ""
        self._content_hash = ""
        self._last_synced_at = ""
        self._counts = {
            "documents": 0,
            "highlights": 0,
            "notes": 0,
            "mindmap_nodes": 0,
        }
        self._warnings: list[dict[str, Any]] = []
        self._pending: list[WriteQueueItem] = []
        self._conflicts: list[SyncConflict] = []
        self._known_write_hashes: dict[str, str] = {}
        self._generation = 0
        self._last_error = ""
        self._load_state()

    # --- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name=f"mn-sync-{_safe_kb_name(self.kb_name)}",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._thread = None

    def subscribe(self, listener: Listener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Listener) -> None:
        with self._lock:
            self._listeners = [item for item in self._listeners if item is not listener]

    # --- public ops ---------------------------------------------------------

    def sync_once(self, *, force: bool = False) -> dict[str, Any]:
        with self._lock:
            if self._status == "conflict" and not force:
                return self.status()
            self._status = "syncing"
        event = None
        try:
            if self.adapter_name not in PUBLIC_ADAPTERS:
                raise AdapterError("adapter='realm' is blocked from live sync.")
            adapter = open_adapter(
                self.notebook_path,
                adapter=self.adapter_name,
                writeback_path=self.writeback_path,
            )
            diagnostics = adapter.diagnose()
            notebook = adapter.load()
            new_hash = diagnostics.content_hash
            changed = force or new_hash != self._content_hash
            write_conflicts = self._detect_write_conflicts(adapter)
            with self._lock:
                self._counts = {
                    "documents": len(notebook.documents),
                    "highlights": len(notebook.highlights),
                    "notes": len(notebook.notes),
                    "mindmap_nodes": len(notebook.mindmap),
                }
                self._warnings = [item.to_dict() for item in diagnostics.warnings]
                self._cursor = diagnostics.cursor
                self._content_hash = new_hash
                self._last_synced_at = _utc_now()
                self._last_error = diagnostics.error
                if write_conflicts:
                    self._conflicts.extend(write_conflicts)
                    self._status = "conflict"
                elif diagnostics.error:
                    self._status = "degraded" if diagnostics.compatible else "requires_user_action"
                else:
                    self._status = "ready"
                if changed:
                    self._generation += 1
                    event = {
                        "type": "notebook_changed" if self._status != "conflict" else "conflict",
                        "generation": self._generation,
                    }
                self._persist_state()
        except (AdapterError, OSError) as exc:
            with self._lock:
                self._status = "degraded"
                self._last_error = str(exc)
                self._persist_state()
            event = {"type": "degraded", "error": str(exc)}
        payload = self.status()
        if event:
            event.update({"status": payload})
            self._emit(event)
        return payload

    def status(self) -> dict[str, Any]:
        official = probe_official_write_interface()
        with self._lock:
            recover = []
            if self._status == "conflict":
                recover.append("resolve_conflict")
            if self._status in {"degraded", "requires_user_action"}:
                recover.append("reexport_or_check_folder")
            if not official.write_api_verified:
                recover.append("import_writeback_folder")
            return {
                "kb_name": self.kb_name,
                "notebook_name": display_name_for(self.notebook_path),
                "adapter": self.adapter_name,
                "status": self._status if self._status in SYNC_STATUSES else "degraded",
                "cursor": self._cursor,
                "content_hash": self._content_hash,
                "last_synced_at": self._last_synced_at,
                "counts": dict(self._counts),
                "pending_write_count": sum(
                    1 for item in self._pending if item.status == "awaiting_import"
                ),
                "pending_writes": [item.to_dict() for item in self._pending],
                "conflicts": [item.to_dict() for item in self._conflicts],
                "warnings": list(self._warnings),
                "recover_actions": list(dict.fromkeys(recover)),
                "generation": self._generation,
                "error": self._last_error or None,
                "write_mode": (
                    "official" if official.write_api_verified else WRITE_MODE_IMPORT_QUEUE
                ),
                "official_write": official.to_dict(),
            }

    def notebook_overview(self, *, highlight_limit: int = 200) -> dict[str, Any]:
        adapter = open_adapter(
            self.notebook_path,
            adapter=self.adapter_name,
            writeback_path=self.writeback_path,
        )
        notebook = adapter.load()
        return {
            "notebook_name": display_name_for(self.notebook_path),
            "documents": [item.to_dict() for item in notebook.documents],
            "highlights": [item.to_dict() for item in notebook.highlights[:highlight_limit]],
            "highlight_truncated": len(notebook.highlights) > highlight_limit,
            "mindmap": adapter.mindmap(depth=3),
            "tags": adapter.tags(),
            "counts": {
                "documents": len(notebook.documents),
                "highlights": len(notebook.highlights),
                "notes": len(notebook.notes),
                "mindmap_nodes": len(notebook.mindmap),
            },
        }

    def enqueue_write(
        self,
        rel_path: str,
        *,
        kind: str = "note",
        content: str = "",
    ) -> WriteQueueItem:
        digest = hashlib.sha256((rel_path + "\n" + (content or "")).encode("utf-8")).hexdigest()[:16]
        item = WriteQueueItem(
            id=uuid4().hex[:12],
            rel_path=rel_path,
            kind=kind,
            status="awaiting_import",
            created_at=_utc_now(),
            content_hash=digest,
            official_write=False,
        )
        with self._lock:
            if self._status == "conflict":
                raise AdapterError("Automatic writes are paused until the conflict is resolved.")
            self._pending.append(item)
            self._known_write_hashes[rel_path] = self._hash_writeback(rel_path)
            self._persist_state()
        self._emit({"type": "write_queued", "item": item.to_dict(), "status": self.status()})
        return item

    def mark_imported(self, item_id: str) -> dict[str, Any]:
        with self._lock:
            found = next((item for item in self._pending if item.id == item_id), None)
            if found is None:
                raise AdapterError(f"Write queue item {item_id!r} was not found.")
            found.status = "imported"
            self._persist_state()
        payload = self.status()
        self._emit({"type": "write_imported", "item_id": item_id, "status": payload})
        return payload

    def clear_conflicts(self) -> dict[str, Any]:
        with self._lock:
            self._conflicts = []
            if self._status == "conflict":
                self._status = "ready"
            self._persist_state()
        payload = self.status()
        self._emit({"type": "conflict_cleared", "status": payload})
        return payload

    # --- internals ----------------------------------------------------------

    def _run_loop(self) -> None:
        self.sync_once(force=True)
        while not self._stop.wait(self.poll_interval):
            try:
                self.sync_once()
            except Exception:
                logger.exception("MarginNote sync loop failed for %s", self.kb_name)

    def _detect_write_conflicts(self, adapter: Any) -> list[SyncConflict]:
        conflicts: list[SyncConflict] = []
        write_root = Path(adapter.writeback_path).expanduser() if adapter.writeback_path else Path(
            self.notebook_path
        ).expanduser() / WRITEBACK_DIRNAME
        if not write_root.is_dir():
            return conflicts
        with self._lock:
            watched = dict(self._known_write_hashes)
            pending_paths = {
                item.rel_path for item in self._pending if item.status == "awaiting_import"
            }
        for rel_path, previous in watched.items():
            current = self._file_hash(write_root / rel_path)
            if previous and current and current != previous and rel_path in pending_paths:
                conflicts.append(
                    SyncConflict(
                        id=uuid4().hex[:10],
                        rel_path=rel_path,
                        reason="Writeback file changed outside DeepTutor while a write was pending.",
                        created_at=_utc_now(),
                    )
                )
            elif current:
                with self._lock:
                    self._known_write_hashes[rel_path] = current
        return conflicts

    def _hash_writeback(self, rel_path: str) -> str:
        root = (
            Path(self.writeback_path).expanduser()
            if self.writeback_path
            else Path(self.notebook_path).expanduser() / WRITEBACK_DIRNAME
        )
        return self._file_hash(root / rel_path)

    @staticmethod
    def _file_hash(path: Path) -> str:
        try:
            data = path.read_bytes()
        except OSError:
            return ""
        return hashlib.sha256(data).hexdigest()[:16]

    def _emit(self, event: dict[str, Any]) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                logger.debug("MarginNote sync listener failed", exc_info=True)

    def _load_state(self) -> None:
        path = _state_path(self.kb_name)
        if not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self._cursor = str(payload.get("cursor") or "")
        self._content_hash = str(payload.get("content_hash") or "")
        self._last_synced_at = str(payload.get("last_synced_at") or "")
        self._status = str(payload.get("status") or "disconnected")
        if self._status not in SYNC_STATUSES:
            self._status = "disconnected"
        counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
        self._counts.update({key: int(counts.get(key) or 0) for key in self._counts})
        self._pending = [
            WriteQueueItem(**item)
            for item in payload.get("pending_writes") or []
            if isinstance(item, dict) and item.get("id")
        ]
        self._conflicts = [
            SyncConflict(**item)
            for item in payload.get("conflicts") or []
            if isinstance(item, dict) and item.get("id")
        ]
        known = payload.get("known_write_hashes")
        if isinstance(known, dict):
            self._known_write_hashes = {str(key): str(value) for key, value in known.items()}

    def _persist_state(self) -> None:
        payload = {
            "kb_name": self.kb_name,
            "cursor": self._cursor,
            "content_hash": self._content_hash,
            "last_synced_at": self._last_synced_at,
            "status": self._status,
            "counts": self._counts,
            "pending_writes": [item.to_dict() for item in self._pending],
            "conflicts": [item.to_dict() for item in self._conflicts],
            "known_write_hashes": self._known_write_hashes,
        }
        try:
            atomic_write_json(_state_path(self.kb_name), payload)
        except OSError:
            logger.debug("Could not persist MarginNote sync state", exc_info=True)


def coordinator_for(
    kb_name: str,
    notebook_path: str,
    *,
    adapter: str = "export",
    writeback_path: str = "",
) -> MarginNoteSyncCoordinator:
    with _registry_lock:
        existing = _coordinators.get(kb_name)
        if existing is not None:
            if existing.notebook_path == notebook_path and existing.adapter_name == adapter:
                return existing
            existing.stop()
        coordinator = MarginNoteSyncCoordinator(
            kb_name,
            notebook_path,
            adapter=adapter,
            writeback_path=writeback_path,
        )
        _coordinators[kb_name] = coordinator
        coordinator.start()
        return coordinator


def existing_coordinator(kb_name: str) -> MarginNoteSyncCoordinator | None:
    with _registry_lock:
        return _coordinators.get(kb_name)


def drop_coordinator(kb_name: str) -> None:
    with _registry_lock:
        existing = _coordinators.pop(kb_name, None)
    if existing is not None:
        existing.stop()


__all__ = [
    "MarginNoteSyncCoordinator",
    "coordinator_for",
    "drop_coordinator",
    "existing_coordinator",
    "probe_marginnote",
]
