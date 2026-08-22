"""Production HTTP bridge for MarginNote 4 Add-on devices."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import logging
from pathlib import Path
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator

from deeptutor.api.routers.auth import require_auth
from deeptutor.capabilities.marginnote4.models import (
    DeletedMarginNoteObject,
    MarginNoteObject,
    MarginNoteSyncConflict,
    SyncBatch,
)
from deeptutor.capabilities.marginnote4.registry import (
    ActiveDeviceError,
    MarginNoteDeviceRegistry,
    PairingCodeError,
    RegisteredDevice,
)
from deeptutor.capabilities.marginnote4.store import MarginNoteStore
from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.knowledge_access import manager_for_resource, resolve_kb
from deeptutor.multi_user.paths import get_current_path_service
from deeptutor.runtime.home import get_runtime_data_root

logger = logging.getLogger(__name__)
router = APIRouter()
_auth = [Depends(require_auth)]

_MAX_BATCH_OBJECTS = 250
_MAX_REQUEST_BYTES = 4 * 1024 * 1024
_MAX_OBJECT_BYTES = 512 * 1024


def _system_registry() -> MarginNoteDeviceRegistry:
    path = get_runtime_data_root() / "user" / "marginnote4" / "registry.db"
    return MarginNoteDeviceRegistry(path)


def _session_scope() -> tuple[str, str, str]:
    user = get_current_user()
    service = get_current_path_service()
    return user.id, str(service.workspace_root.resolve()), str(service.user_data_dir)


def _writable_library(kb_ref: str) -> str:
    try:
        resource = resolve_kb(kb_ref, require_write=True)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to resolve library") from exc
    metadata = manager_for_resource(resource).get_metadata(resource.name)
    if metadata.type != "marginnote4":
        raise HTTPException(status_code=400, detail="Knowledge base is not a MarginNote 4 library")
    return resource.name


def _store_for_device(device: RegisteredDevice) -> MarginNoteStore:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in device.kb_name)
    path = Path(device.workspace_root) / "user" / "marginnote4" / f"{safe}.db"
    return MarginNoteStore(path)


def _device_from_header(authorization: str | None) -> RegisteredDevice:
    if not authorization or not authorization.startswith("Bearer MN4 "):
        raise HTTPException(status_code=401, detail="Missing MarginNote device token")
    token = authorization[len("Bearer MN4 ") :].strip()
    try:
        return _system_registry().authenticate(token)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


async def _bounded_request(request: Request) -> None:
    raw_size = request.headers.get("content-length")
    if raw_size:
        try:
            size = int(raw_size)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length")
        if size > _MAX_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="Request body exceeds 4 MiB")


class PairingCodeRequest(BaseModel):
    kb_ref: str = Field(min_length=1, max_length=255)


class PairingCodeResponse(BaseModel):
    code: str
    expires_at: str


class ClaimRequest(BaseModel):
    code: str = Field(min_length=8, max_length=64)
    device_name: str = Field(default="", max_length=120)
    device_kind: str = Field(default="macos", pattern="^(macos|ipados)$")
    protocol_version: int = Field(default=1, ge=1, le=1)


class ClaimResponse(BaseModel):
    device_id: str
    token: str
    kb_name: str
    protocol_version: int


class DeletedObjectIn(BaseModel):
    object_id: str = Field(min_length=1, max_length=255)
    updated_at: str = Field(default="", max_length=64)


class SyncObjectIn(BaseModel):
    object_id: str = Field(min_length=1, max_length=255)
    object_type: str = Field(pattern="^(note|excerpt|card|mindmap_node|document|comment)$")
    title: str = Field(default="", max_length=8192)
    content: str = Field(default="", max_length=262144)
    excerpt: str | None = Field(default=None, max_length=262144)
    document_id: str | None = Field(default=None, max_length=255)
    document_title: str | None = Field(default=None, max_length=2048)
    page: int | None = Field(default=None, ge=0, le=1_000_000)
    tags: list[str] = Field(default_factory=list, max_length=128)
    links: list[str] = Field(default_factory=list, max_length=512)
    color: str | None = Field(default=None, max_length=64)
    created_at: str = Field(default="", max_length=64)
    updated_at: str = Field(default="", max_length=64)
    revision: int = Field(default=1, ge=1)
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tags")
    @classmethod
    def bounded_tags(cls, value: list[str]) -> list[str]:
        if any(len(tag) > 512 for tag in value):
            raise ValueError("tag exceeds 512 characters")
        return value

    @field_validator("links")
    @classmethod
    def bounded_links(cls, value: list[str]) -> list[str]:
        if any(len(link) > 255 for link in value):
            raise ValueError("link exceeds 255 characters")
        return value

    @model_validator(mode="after")
    def bounded_object(self) -> "SyncObjectIn":
        if len(self.model_dump_json().encode("utf-8")) > _MAX_OBJECT_BYTES:
            raise ValueError("object exceeds 512 KiB")
        return self

    def to_domain(self, device_id: str) -> MarginNoteObject:
        return MarginNoteObject(
            object_id=self.object_id,
            object_type=self.object_type,
            title=self.title,
            content=self.content,
            excerpt=self.excerpt,
            document_id=self.document_id,
            document_title=self.document_title,
            page=self.page,
            tags=self.tags,
            links=self.links,
            color=self.color,
            created_at=self.created_at,
            updated_at=self.updated_at,
            device_id=device_id,
            revision=self.revision,
            raw=self.raw,
        )


class SyncRequest(BaseModel):
    protocol_version: int = Field(ge=1, le=1)
    batch_id: str = Field(min_length=8, max_length=128)
    cursor: str = Field(max_length=256)
    objects: list[SyncObjectIn] = Field(default_factory=list, max_length=_MAX_BATCH_OBJECTS)
    deleted_objects: list[DeletedObjectIn] = Field(
        default_factory=list, max_length=_MAX_BATCH_OBJECTS
    )

    @model_validator(mode="after")
    def bounded_request(self) -> "SyncRequest":
        if len(self.model_dump_json().encode("utf-8")) > _MAX_REQUEST_BYTES:
            raise ValueError("request exceeds 4 MiB")
        return self


class SyncResponse(BaseModel):
    stored: int
    updated: int
    deleted: int
    skipped: int = 0
    new_cursor: str
    duplicate: bool = False


class SnapshotCreateRequest(BaseModel):
    protocol_version: int = Field(ge=1, le=1)
    total_batches: int = Field(ge=1, le=100_000)


class SnapshotBatchRequest(BaseModel):
    protocol_version: int = Field(ge=1, le=1)
    batch_id: str = Field(min_length=8, max_length=128)
    objects: list[SyncObjectIn] = Field(default_factory=list, max_length=_MAX_BATCH_OBJECTS)

    @model_validator(mode="after")
    def bounded_request(self) -> "SnapshotBatchRequest":
        if len(self.model_dump_json().encode("utf-8")) > _MAX_REQUEST_BYTES:
            raise ValueError("request exceeds 4 MiB")
        return self


class DeviceInfo(BaseModel):
    device_id: str
    device_name: str
    device_kind: str
    protocol_version: int
    paired_at: str
    last_seen: str
    active: bool


@router.post("/pairing-codes", response_model=PairingCodeResponse, dependencies=_auth)
async def create_pairing_code(body: PairingCodeRequest) -> PairingCodeResponse:
    kb_name = _writable_library(body.kb_ref)
    owner_id, workspace_root, _ = _session_scope()
    code = await asyncio.to_thread(
        _system_registry().create_pairing_code,
        owner_id=owner_id,
        kb_name=kb_name,
        workspace_root=workspace_root,
    )
    logger.info(
        "MN4 pairing code created owner=%s kb=%s expires=%s",
        owner_id,
        kb_name,
        code.expires_at,
    )
    return PairingCodeResponse(code=code.code, expires_at=code.expires_at)


@router.post("/pair/claim", response_model=ClaimResponse)
async def claim_device(body: ClaimRequest) -> ClaimResponse:
    started = time.perf_counter()
    try:
        device, token = await asyncio.to_thread(
            _system_registry().claim,
            body.code,
            device_name=body.device_name,
            device_kind=body.device_kind,
            protocol_version=body.protocol_version,
        )
    except PairingCodeError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except ActiveDeviceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logger.info(
        "MN4 device paired device=%s owner=%s kb=%s elapsed_ms=%.1f",
        device.device_id,
        device.owner_id,
        device.kb_name,
        (time.perf_counter() - started) * 1000,
    )
    return ClaimResponse(
        device_id=device.device_id,
        token=token,
        kb_name=device.kb_name,
        protocol_version=device.protocol_version,
    )


@router.get(
    "/libraries/{kb_ref}/devices",
    response_model=list[DeviceInfo],
    dependencies=_auth,
)
async def list_devices(kb_ref: str) -> list[DeviceInfo]:
    kb_name = _writable_library(kb_ref)
    owner_id, workspace_root, _ = _session_scope()
    devices = await asyncio.to_thread(
        _system_registry().list_devices,
        owner_id=owner_id,
        kb_name=kb_name,
        workspace_root=workspace_root,
    )
    return [
        DeviceInfo(
            device_id=d.device_id,
            device_name=d.device_name,
            device_kind=d.device_kind,
            protocol_version=d.protocol_version,
            paired_at=d.paired_at,
            last_seen=d.last_seen,
            active=d.active,
        )
        for d in devices
    ]


@router.delete("/devices/{device_id}", dependencies=_auth)
async def revoke_device(device_id: str) -> dict[str, str]:
    owner_id, workspace_root, _ = _session_scope()
    try:
        device = await asyncio.to_thread(
            _system_registry().revoke,
            owner_id=owner_id,
            device_id=device_id,
            workspace_root=workspace_root,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Device not found")
    logger.warning("MN4 device revoked owner=%s device=%s", owner_id, device.device_id)
    return {"status": "revoked", "device_id": device.device_id}


@router.post(
    "/sync",
    response_model=SyncResponse,
    dependencies=[Depends(_bounded_request)],
)
async def sync_objects(
    body: SyncRequest,
    authorization: str | None = Header(None, alias="Authorization"),
) -> SyncResponse:
    device = _device_from_header(authorization)
    store = _store_for_device(device)
    batch = SyncBatch(
        device_id=device.device_id,
        batch_id=body.batch_id,
        protocol_version=body.protocol_version,
        cursor=body.cursor,
        objects=[item.to_domain(device.device_id) for item in body.objects],
        deleted_objects=[
            DeletedMarginNoteObject(object_id=item.object_id, updated_at=item.updated_at)
            for item in body.deleted_objects
        ],
    )
    started = time.perf_counter()
    try:
        result = await asyncio.to_thread(store.ingest, batch)
    except MarginNoteSyncConflict as exc:
        logger.warning(
            "MN4 cursor conflict device=%s client_cursor=%s",
            device.device_id,
            body.cursor,
        )
        raise HTTPException(
            status_code=409,
            detail={"error": "cursor_conflict", "server_cursor": exc.server_cursor},
        ) from exc
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "MN4 sync device=%s objects=%d deleted=%d duplicate=%s elapsed_ms=%.1f",
        device.device_id,
        len(body.objects),
        len(body.deleted_objects),
        result.duplicate,
        elapsed_ms,
    )
    await asyncio.to_thread(_system_registry().touch, device.device_id)
    return SyncResponse(**asdict(result))


@router.post(
    "/snapshots",
    dependencies=[Depends(_bounded_request)],
)
async def create_snapshot(
    body: SnapshotCreateRequest,
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    device = _device_from_header(authorization)
    store = _store_for_device(device)
    result = await asyncio.to_thread(
        store.create_snapshot,
        device_id=device.device_id,
        total_batches=body.total_batches,
    )
    logger.info(
        "MN4 snapshot created device=%s snapshot=%s total_batches=%d",
        device.device_id,
        result["snapshot_id"],
        body.total_batches,
    )
    return result


@router.put(
    "/snapshots/{snapshot_id}/batches/{sequence}",
    dependencies=[Depends(_bounded_request)],
)
async def append_snapshot(
    snapshot_id: str,
    sequence: int,
    body: SnapshotBatchRequest,
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    device = _device_from_header(authorization)
    store = _store_for_device(device)
    objects = [item.to_domain(device.device_id) for item in body.objects]
    started = time.perf_counter()
    try:
        result = await asyncio.to_thread(
            store.append_snapshot,
            snapshot_id,
            sequence=sequence,
            batch_id=body.batch_id,
            objects=objects,
        )
    except MarginNoteSyncConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "sequence_conflict", "server_cursor": exc.server_cursor},
        ) from exc
    except KeyError:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    logger.info(
        "MN4 snapshot batch device=%s snapshot=%s sequence=%d objects=%d "
        "duplicate=%s elapsed_ms=%.1f",
        device.device_id,
        snapshot_id,
        sequence,
        len(objects),
        result.get("duplicate", False),
        (time.perf_counter() - started) * 1000,
    )
    await asyncio.to_thread(_system_registry().touch, device.device_id)
    return result


@router.post("/snapshots/{snapshot_id}/commit")
async def commit_snapshot(
    snapshot_id: str,
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    device = _device_from_header(authorization)
    store = _store_for_device(device)
    try:
        result = await asyncio.to_thread(store.commit_snapshot, snapshot_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    logger.info(
        "MN4 snapshot committed device=%s snapshot=%s objects=%d duplicate=%s",
        device.device_id,
        snapshot_id,
        result["object_count"],
        result["duplicate"],
    )
    await asyncio.to_thread(_system_registry().touch, device.device_id)
    return result


@router.post("/heartbeat")
async def heartbeat(
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    device = _device_from_header(authorization)
    store = _store_for_device(device)
    object_count = await asyncio.to_thread(store.count)
    await asyncio.to_thread(_system_registry().touch, device.device_id)
    return {
        "status": "ok",
        "device_id": device.device_id,
        "kb_name": device.kb_name,
        "object_count": object_count,
        "server_cursor": await asyncio.to_thread(store.server_cursor),
    }
