"""Local MarginNote 4 bridge helper and durable journal."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import yaml

from deeptutor.capabilities.marginnote4.automation import (
    AppleScriptProvider,
    AutomationError,
    AutomationProvider,
    ShortcutProvider,
    URLSchemeProvider,
    WriteRequest,
    config_hash,
)
from deeptutor.capabilities.marginnote4.data.export_adapter import ExportAdapter
from deeptutor.capabilities.marginnote4.models import (
    COMMENT,
    DOCUMENT,
    EXCERPT,
    MINDMAP_NODE,
    NOTE,
    MarginNoteObject,
    SyncBatch,
)
from deeptutor.capabilities.marginnote4.store import object_hash


class BridgeError(Exception):
    pass


class BulkDeleteSafety(BridgeError):
    pass


@dataclass(slots=True)
class SyncPlan:
    objects: list[MarginNoteObject]
    deleted_ids: list[str]
    snapshot_hash: str
    pending_deletions: int


class BridgeJournal:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS objects (
                    object_id TEXT PRIMARY KEY,
                    object_hash TEXT NOT NULL,
                    miss_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS sync_receipts (
                    sync_id TEXT PRIMARY KEY,
                    completed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS writeback_receipts (
                    payload_hash TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    external_id TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._chmod()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _chmod(self) -> None:
        try:
            os.chmod(self.path, 0o600)
            for suffix in ("-wal", "-shm"):
                path = Path(str(self.path) + suffix)
                if path.exists():
                    os.chmod(path, 0o600)
        except OSError:
            pass

    def meta(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO meta VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def object_state(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT object_id, COALESCE(object_hash, '') AS object_hash FROM objects"
            ).fetchall()
        return {row["object_id"]: row["object_hash"] for row in rows}

    def prepare_missing(self, missing_ids: list[str]) -> None:
        with self._connect() as conn:
            for object_id in missing_ids:
                conn.execute(
                    """INSERT INTO objects (object_id, object_hash, miss_count)
                       VALUES (?, '', 1)
                       ON CONFLICT(object_id) DO UPDATE SET miss_count = miss_count + 1""",
                    (object_id,),
                )

    def eligible_deletions(self, missing_ids: list[str]) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT object_id FROM objects WHERE miss_count >= 2").fetchall()
        eligible = {row["object_id"] for row in rows}
        return [object_id for object_id in missing_ids if object_id in eligible]

    def commit_sync(
        self,
        *,
        objects: dict[str, str],
        deleted_ids: list[str],
        sequence: int,
        cursor: str,
        sync_id: str,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.executemany(
                """INSERT INTO objects (object_id, object_hash, miss_count)
                   VALUES (?, ?, 0)
                   ON CONFLICT(object_id) DO UPDATE SET
                     object_hash=excluded.object_hash, miss_count=0""",
                objects.items(),
            )
            conn.executemany(
                "DELETE FROM objects WHERE object_id = ?",
                [(object_id,) for object_id in deleted_ids],
            )
            conn.execute(
                """INSERT INTO sync_receipts VALUES (?, ?)
                   ON CONFLICT(sync_id) DO NOTHING""",
                (sync_id, now),
            )
            conn.execute(
                "INSERT INTO meta VALUES ('sequence', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(sequence),),
            )
            conn.execute(
                "INSERT INTO meta VALUES ('cursor', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (cursor,),
            )
        self._chmod()

    def writeback_receipt(self, payload_hash: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM writeback_receipts WHERE payload_hash = ?", (payload_hash,)
            ).fetchone()
        return dict(row) if row else None

    def record_writeback(self, *, payload_hash: str, status: str, external_id: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO writeback_receipts
                   (payload_hash, status, external_id, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(payload_hash) DO UPDATE SET
                     status=excluded.status,
                     external_id=excluded.external_id,
                     updated_at=excluded.updated_at""",
                (payload_hash, status, external_id, datetime.now(UTC).isoformat()),
            )
        self._chmod()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def objects_from_notebook(notebook: Any) -> list[MarginNoteObject]:
    """Normalize ExportAdapter entities into bridge objects."""
    objects: list[MarginNoteObject] = []
    for document in notebook.documents:
        objects.append(
            MarginNoteObject(
                object_id=f"document:{document.id}",
                object_type=DOCUMENT,
                title=document.name,
                content=document.name,
                document_id=document.id,
                document_title=document.name,
                raw=document.to_dict(),
            )
        )
    for highlight in notebook.highlights:
        objects.append(
            MarginNoteObject(
                object_id=f"excerpt:{highlight.id}",
                object_type=EXCERPT,
                title=highlight.document_name,
                content=highlight.text,
                excerpt=highlight.text,
                document_id=highlight.document_id,
                document_title=highlight.document_name,
                page=highlight.page,
                tags=highlight.tags,
                color=highlight.color or None,
                links=[f"note:{highlight.note_id}"] if highlight.note_id else [],
                raw=highlight.to_dict(),
            )
        )
    for note in notebook.notes:
        objects.append(
            MarginNoteObject(
                object_id=f"note:{note.id}",
                object_type=NOTE if not note.highlight_id else COMMENT,
                title=(note.text or "(note)")[:120],
                content=note.text,
                document_id=note.document_id,
                document_title=note.document_name,
                page=note.page,
                tags=note.tags,
                links=[f"excerpt:{note.highlight_id}"] if note.highlight_id else [],
                raw=note.to_dict(),
            )
        )
    for node in notebook.mindmap:
        objects.append(
            MarginNoteObject(
                object_id=f"mindmap:{node.id}",
                object_type=MINDMAP_NODE,
                title=node.title,
                content=node.note,
                document_id=node.document_id or None,
                links=[f"mindmap:{child}" for child in node.children],
                raw=node.to_dict(),
            )
        )
    return objects


def plan_sync(
    notebook_path: str | Path,
    journal: BridgeJournal,
    *,
    confirm_bulk_delete: bool = False,
) -> SyncPlan:
    adapter = ExportAdapter(str(notebook_path))
    notebook = adapter.load()
    objects = objects_from_notebook(notebook)
    current = {obj.object_id: object_hash(obj) for obj in objects}
    previous = journal.object_state()
    missing = sorted(set(previous) - set(current))
    if missing and previous and len(missing) > len(previous) * 0.25 and not confirm_bulk_delete:
        raise BulkDeleteSafety(
            f"Refusing to delete {len(missing)} of {len(previous)} objects without confirmation"
        )
    if missing:
        journal.prepare_missing(missing)
    deleted = journal.eligible_deletions(missing)
    changed = [obj for obj in objects if current[obj.object_id] != previous.get(obj.object_id)]
    snapshot_hash = _sha(_canonical(sorted(current.items())))
    return SyncPlan(changed, deleted, snapshot_hash, len(missing))


class BridgeClient:
    def __init__(self, server_url: str, timeout: int = 30) -> None:
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self.server_url}/api/v1/marginnote4{path}"

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        device_id: str = "",
        token: str = "",
    ) -> dict[str, Any]:
        body = None if payload is None else _canonical(payload).encode("utf-8")
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if device_id:
            headers["Authorization"] = f"MarginNote {device_id}:{token}"
        request = Request(self._url(path), data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                message = json.loads(detail).get("detail", detail)
            except json.JSONDecodeError:
                message = detail
            raise BridgeError(f"HTTP {exc.code}: {message}") from exc
        except URLError as exc:
            raise BridgeError(f"Cannot reach DeepTutor: {exc.reason}") from exc
        if not raw:
            return {}
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BridgeError("DeepTutor returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise BridgeError("DeepTutor returned an unexpected response")
        return decoded

    def pair(self, code: str, *, device_name: str, device_kind: str = "macos") -> dict[str, Any]:
        return self.request(
            "POST",
            "/devices/pair",
            {
                "code": code,
                "device_name": device_name,
                "device_kind": device_kind,
            },
        )

    def sync(self, batch: SyncBatch, token: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "sync_id": batch.sync_id,
            "sequence": batch.sequence,
            "final": batch.final,
            "base_cursor": batch.base_cursor,
            "snapshot_hash": batch.snapshot_hash,
            "deleted_ids": batch.deleted_ids,
            "objects": [obj.to_dict() for obj in batch.objects],
        }
        return self.request(
            "POST", "/sync/batches", payload, device_id=batch.device_id, token=token
        )

    def claim(self, device_id: str, token: str) -> dict[str, Any] | None:
        result = self.request("POST", "/jobs/claim", {}, device_id=device_id, token=token)
        return result.get("job")

    def renew(
        self, device_id: str, token: str, writeback_id: str, lease_token: str
    ) -> dict[str, Any]:
        return self.request(
            "POST",
            "/jobs/renew",
            {"writeback_id": writeback_id, "lease_token": lease_token},
            device_id=device_id,
            token=token,
        )

    def complete(self, device_id: str, token: str, receipt: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/jobs/complete", receipt, device_id=device_id, token=token)

    def verify_automation(
        self, device_id: str, token: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self.request(
            "POST", "/automation/verification", payload, device_id=device_id, token=token
        )

    def automation_status(
        self,
        device_id: str,
        token: str,
        *,
        provider: str,
        bundle_id: str,
        app_version: str,
        config_hash: str,
    ) -> dict[str, Any]:
        query = urlencode(
            {
                "provider": provider,
                "bundle_id": bundle_id,
                "app_version": app_version,
                "config_hash": config_hash,
            }
        )
        return self.request(
            "GET",
            f"/automation/verification?{query}",
            device_id=device_id,
            token=token,
        )


class BridgeConfig:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            raise BridgeError(f"Bridge config not found: {self.path}")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not data.get("server_url") or not data.get("notebook_path"):
            raise BridgeError("Bridge config needs server_url and notebook_path")
        return data

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)

    def journal_path(self) -> Path:
        data = self.load()
        configured = data.get("journal_path")
        return Path(configured or self.path.with_suffix(".sqlite")).expanduser()

    def token_path(self) -> Path:
        return self.path.with_suffix(".token")


def _keychain_service() -> str:
    return "com.deeptutor.marginnote4.bridge"


def _keychain_account(config: dict[str, Any]) -> str:
    return _sha(f"{config.get('server_url', '')}:{config.get('device_id', '')}")


def save_token(config: BridgeConfig, token: str, storage: str = "") -> None:
    data = config.load()
    mode = (
        storage or data.get("token_storage") or ("keychain" if sys.platform == "darwin" else "file")
    )
    data["token_storage"] = mode
    config.save(data)
    if mode == "keychain":
        if sys.platform != "darwin":
            raise BridgeError("Keychain storage is only available on macOS")
        security = shutil.which("security")
        if not security:
            raise BridgeError("macOS security command is unavailable")
        completed = shutil.which("osascript")  # keep import surface small; not used
        _ = completed
        result = subprocess_run(
            [
                security,
                "add-generic-password",
                "-U",
                "-s",
                _keychain_service(),
                "-a",
                _keychain_account(data),
                "-w",
                token,
            ]
        )
        if result.returncode:
            raise BridgeError("Could not store the device token in Keychain")
        return
    config.token_path().write_text(token, encoding="utf-8")
    os.chmod(config.token_path(), 0o600)


def load_token(config: BridgeConfig) -> str:
    data = config.load()
    mode = data.get("token_storage") or ("keychain" if sys.platform == "darwin" else "file")
    if mode == "keychain":
        if sys.platform != "darwin":
            raise BridgeError("Keychain storage is only available on macOS")
        security = shutil.which("security")
        if not security:
            raise BridgeError("macOS security command is unavailable")
        result = subprocess_run(
            [
                "security",
                "find-generic-password",
                "-w",
                "-s",
                _keychain_service(),
                "-a",
                _keychain_account(data),
            ]
        )
        if result.returncode:
            raise BridgeError("Device token is missing from Keychain")
        return result.stdout.strip()
    path = config.token_path()
    if not path.exists():
        raise BridgeError("Device token file is missing")
    return path.read_text(encoding="utf-8").strip()


def subprocess_run(command: list[str]) -> Any:
    import subprocess

    return subprocess.run(command, check=False, capture_output=True, text=True)


def _provider_from_config(data: dict[str, Any]) -> AutomationProvider | None:
    provider = str(data.get("automation_provider") or "").lower()
    if provider == "applescript":
        return AppleScriptProvider(
            app_path=data.get("app_path", "/Applications/MarginNote 4.app"),
            script_template=data.get("applescript_template", ""),
        )
    if provider == "shortcut":
        return ShortcutProvider(str(data.get("shortcut_name") or ""))
    if provider == "url_scheme":
        return URLSchemeProvider(str(data.get("url_action_template") or ""))
    return None


def _safe_name(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return slug[:100] or "writeback"


def _frontmatter(job: dict[str, Any]) -> str:
    data = {
        "title": job.get("title", ""),
        "tags": job.get("tags", []),
        "source_refs": job.get("source_refs", []),
        "target_notebook": job.get("target_notebook", ""),
        "payload_hash": job.get("payload_hash", ""),
        "created_by": "deeptutor",
    }
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False).strip()


def _write_import(notebook_path: Path, job: dict[str, Any]) -> tuple[str, str]:
    root = notebook_path / "deeptutor-notes"
    root.mkdir(parents=True, exist_ok=True)
    path = (
        root
        / f"{_safe_name(str(job.get('writeback_id', 'job')))}-{_safe_name(str(job.get('title', 'note')))}.md"
    )
    content = f"---\n{_frontmatter(job)}\n---\n\n{job.get('markdown', '').rstrip()}\n"
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == content:
                return "awaiting_import", str(path)
        except OSError:
            pass
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        conflict = path.with_name(f"{path.stem}.conflict-{timestamp}.md")
        with conflict.open("x", encoding="utf-8") as handle:
            handle.write(content)
        return "conflicted", str(conflict)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(content)
    return "awaiting_import", str(path)


class BridgeRunner:
    def __init__(self, config_path: str | Path, *, timeout: int = 30) -> None:
        self.config_path = Path(config_path).expanduser()
        self.config = BridgeConfig(self.config_path)
        self.data = self.config.load()
        self.journal = BridgeJournal(self.config.journal_path())
        self.client = BridgeClient(self.data["server_url"], timeout=timeout)
        self.device_id = str(self.data["device_id"])

    def sync_once(self, *, confirm_bulk_delete: bool = False) -> dict[str, Any]:
        token = load_token(self.config)
        plan = plan_sync(
            self.data["notebook_path"], self.journal, confirm_bulk_delete=confirm_bulk_delete
        )
        if not plan.objects and not plan.deleted_ids:
            return {
                "changed": 0,
                "deleted": 0,
                "snapshot_hash": plan.snapshot_hash,
                "pending_deletions": plan.pending_deletions,
            }
        base_sequence = int(self.journal.meta("sequence", "0") or 0)
        base_cursor = self.journal.meta("cursor")
        batches: list[SyncBatch] = []
        chunk_size = 100
        new_cursor = base_cursor
        remaining = plan.objects
        total_sequence = base_sequence
        deletions = plan.deleted_ids
        while remaining or not total_sequence or deletions:
            sequence = total_sequence + 1
            chunk = remaining[:chunk_size]
            remaining = remaining[chunk_size:]
            final = not remaining
            batch = SyncBatch(
                device_id=self.device_id,
                sync_id=_sha(f"{self.device_id}:{sequence}:{plan.snapshot_hash}"),
                sequence=sequence,
                final=final,
                base_cursor=new_cursor,
                snapshot_hash=plan.snapshot_hash,
                objects=chunk,
                deleted_ids=deletions if final else [],
            )
            response = self.client.sync(batch, token)
            new_cursor = str(response["new_cursor"])
            total_sequence = sequence
            if final:
                final_batch = batch
                break
        current_hashes = {obj.object_id: object_hash(obj) for obj in plan.objects}
        # Preserve hashes for unchanged objects while removing eligible tombstones.
        previous = self.journal.object_state()
        state = {**previous, **current_hashes}
        for object_id in deletions:
            state.pop(object_id, None)
        self.journal.commit_sync(
            objects=state,
            deleted_ids=deletions,
            sequence=total_sequence,
            cursor=new_cursor,
            sync_id=final_batch.sync_id,
        )
        return {
            "changed": len(plan.objects),
            "deleted": len(deletions),
            "snapshot_hash": plan.snapshot_hash,
            "pending_deletions": plan.pending_deletions,
        }

    def writebacks_once(self) -> dict[str, Any]:
        token = load_token(self.config)
        job = self.client.claim(self.device_id, token)
        if not job:
            return {"claimed": 0}
        payload_hash = str(job["payload_hash"])
        receipt = self.journal.writeback_receipt(payload_hash)
        result = str(receipt["status"]) if receipt else ""
        external_id = str(receipt.get("external_id") or "") if receipt else ""
        if not result:
            if job.get("delivery_mode") == "automation":
                provider = _provider_from_config(self.data)
                if provider is None:
                    result = "failed"
                    external_id = ""
                    job["last_error"] = "Automation provider is not configured"
                else:
                    try:
                        probe = provider.probe()
                        verification = self.client.automation_status(
                            self.device_id,
                            token,
                            provider=provider.name,
                            bundle_id=probe.bundle_id or "unknown",
                            app_version=probe.app_version or "unknown",
                            config_hash=config_hash(provider),
                        )
                        if verification.get("verified") is not True:
                            result = "failed"
                            job["last_error"] = str(
                                verification.get("reason")
                                or "Automation provider is not verified for this device"
                            )
                        else:
                            external_id = provider.apply(
                                WriteRequest(
                                    title=job["title"],
                                    markdown=job["markdown"],
                                    tags=job.get("tags", []),
                                    target_notebook=job.get("target_notebook", ""),
                                )
                            )
                            result = "applied"
                    except AutomationError as exc:
                        result = "failed"
                        job["last_error"] = str(exc)
            else:
                result, external_id = _write_import(
                    Path(self.data["notebook_path"]).expanduser(), job
                )
            if result != "failed":
                self.journal.record_writeback(
                    payload_hash=payload_hash, status=result, external_id=external_id
                )
        provider_name = (
            str(self.data.get("automation_provider") or "import_queue")
            if job.get("delivery_mode") == "automation"
            else "import_queue"
        )
        complete_receipt = {
            "writeback_id": job["writeback_id"],
            "lease_token": job["lease"]["token"],
            "payload_hash": payload_hash,
            "delivery_mode": job["delivery_mode"],
            "provider": provider_name,
            "result": result,
            "external_id": external_id,
            "written_at": datetime.now(UTC).isoformat(),
            "error": job.get("last_error", ""),
        }
        self.client.complete(self.device_id, token, complete_receipt)
        return {
            "claimed": 1,
            "writeback_id": job["writeback_id"],
            "result": result,
            "external_id": external_id,
        }

    def run_once(self, *, confirm_bulk_delete: bool = False) -> dict[str, Any]:
        sync = self.sync_once(confirm_bulk_delete=confirm_bulk_delete)
        writeback = self.writebacks_once()
        return {"sync": sync, "writeback": writeback}

    def run_forever(self, interval: float = 1.5) -> None:
        while True:
            try:
                result = self.run_once()
                print(_canonical(result), flush=True)
            except Exception as exc:
                print(_canonical({"error": str(exc)}), flush=True)
            delay = max(1.0, interval) * (0.9 + secrets.randbits(8) / 1280.0)
            time.sleep(delay)


def pair_bridge(
    *,
    server_url: str,
    code: str,
    notebook_path: str,
    config_path: str | Path,
    device_name: str = "",
    token_storage: str = "",
) -> dict[str, Any]:
    config = BridgeConfig(config_path)
    client = BridgeClient(server_url)
    device = client.pair(
        code,
        device_name=device_name or f"{Path.home().name}-Mac",
        device_kind="macos",
    )
    journal_path = Path(config_path).expanduser().with_suffix(".sqlite")
    data = {
        "server_url": server_url.rstrip("/"),
        "notebook_path": str(Path(notebook_path).expanduser()),
        "device_id": device["device_id"],
        "journal_path": str(journal_path),
        "token_storage": token_storage or ("keychain" if sys.platform == "darwin" else "file"),
        "interval_seconds": 1.5,
    }
    config.save(data)
    save_token(config, device["token"], token_storage)
    BridgeJournal(journal_path)
    return data


__all__ = [
    "BridgeClient",
    "BridgeConfig",
    "BridgeError",
    "BridgeJournal",
    "BridgeRunner",
    "BulkDeleteSafety",
    "SyncPlan",
    "objects_from_notebook",
    "pair_bridge",
    "plan_sync",
]
