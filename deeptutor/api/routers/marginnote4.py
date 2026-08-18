"""HTTP API for the local MarginNote 4 bridge."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_auth
from deeptutor.capabilities.marginnote4.device_registry import (
    DeviceRegistry,
    DeviceRegistryError,
)
from deeptutor.capabilities.marginnote4.models import (
    MarginNoteObject,
    SyncBatch,
    WritebackPayload,
)
from deeptutor.capabilities.marginnote4.store import (
    BulkDeleteGuard,
    MarginNoteStore,
    MarginNoteStoreError,
    SyncConflict,
    WritebackStateError,
    _default_db_path,
)
from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.knowledge_access import resolve_kb, resolve_kb_metadata

logger = logging.getLogger(__name__)
router = APIRouter()
_auth = [Depends(require_auth)]
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient", "testserver"}


def _transport_allowed(request: Request) -> None:
    host = (request.client.host if request.client else "").lower()
    if request.url.scheme.lower() != "https" and host not in _LOCAL_HOSTS:
        raise HTTPException(
            status_code=426,
            detail="MarginNote bridge requires HTTPS for non-local servers",
        )


def _session_store(kb_name: str) -> tuple[str, str, MarginNoteStore]:
    resource = resolve_kb(kb_name, require_write=True)
    metadata = resolve_kb_metadata(resource.name) or {}
    db_path = str(metadata.get("db_path") or "").strip() or str(_default_db_path(resource.name))
    return get_current_user().id, resource.id, MarginNoteStore(db_path)


def _device_auth(
    request: Request, authorization: str | None
) -> tuple[dict[str, Any], MarginNoteStore]:
    _transport_allowed(request)
    if not authorization or not authorization.startswith("MarginNote "):
        raise HTTPException(401, "Missing or malformed Authorization header")
    raw = authorization[len("MarginNote ") :]
    if ":" not in raw:
        raise HTTPException(401, "Invalid Authorization format")
    device_id, token = raw.split(":", 1)
    try:
        identity = DeviceRegistry().authenticate(device_id, token)
    except DeviceRegistryError as exc:
        raise HTTPException(403, str(exc)) from exc
    store = MarginNoteStore(identity["db_path"])
    store.touch_device(device_id)
    return identity, store


class PairingCodeRequest(BaseModel):
    kb_name: str
    ttl_seconds: int = Field(600, ge=30, le=600)


class PairingCodeResponse(BaseModel):
    code: str
    expires_at: str
    kb_name: str
    command: str


class PairRequest(BaseModel):
    code: str
    device_name: str = ""
    device_kind: str = "macos"


class PairResponse(BaseModel):
    device_id: str
    token: str
    user_id: str
    kb_id: str
    kb_name: str
    device_name: str
    device_kind: str


class DeviceInfo(BaseModel):
    device_id: str
    user_id: str
    kb_id: str
    kb_name: str
    device_name: str
    device_kind: str
    paired_at: str
    last_seen: str
    active: bool = True


class SyncObjectIn(BaseModel):
    object_id: str
    object_type: str
    title: str = ""
    content: str = ""
    excerpt: str | None = None
    document_id: str | None = None
    document_title: str | None = None
    page: int | None = None
    tags: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    color: str | None = None
    created_at: str = ""
    updated_at: str = ""
    synced_at: str = ""
    object_hash: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class SyncRequest(BaseModel):
    sync_id: str
    sequence: int = Field(..., ge=1)
    final: bool = True
    base_cursor: str = ""
    snapshot_hash: str
    objects: list[SyncObjectIn] = Field(default_factory=list)
    deleted_ids: list[str] = Field(default_factory=list)


class SyncResponse(BaseModel):
    stored: int
    updated: int
    deleted: int
    skipped: int
    new_cursor: str


class WritebackCreateRequest(BaseModel):
    kb_name: str
    title: str
    markdown: str
    tags: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    target_notebook: str = ""


class WritebackActionRequest(BaseModel):
    kb_name: str


class LeaseRequest(BaseModel):
    writeback_id: str
    lease_token: str
    ttl_seconds: int = Field(60, ge=15, le=300)


class ReceiptRequest(BaseModel):
    writeback_id: str
    lease_token: str
    payload_hash: str
    delivery_mode: str
    provider: str
    result: str
    external_id: str = ""
    written_at: str = ""
    error: str = ""


class AutomationVerificationRequest(BaseModel):
    provider: str
    bundle_id: str
    app_version: str
    config_hash: str
    test_external_id: str = ""
    verified: bool


@router.post("/pairing-codes", response_model=PairingCodeResponse, dependencies=_auth)
async def create_pairing_code(body: PairingCodeRequest, request: Request) -> PairingCodeResponse:
    _transport_allowed(request)
    user_id, kb_id, store = _session_store(body.kb_name)
    registry = DeviceRegistry()
    from datetime import datetime, timedelta, timezone

    expires = datetime.now(timezone.utc) + timedelta(seconds=body.ttl_seconds)
    code = registry.create_pairing_code(
        user_id=user_id,
        kb_id=kb_id,
        kb_name=body.kb_name.strip(),
        db_path=str(store.db_path),
        ttl_seconds=body.ttl_seconds,
    )
    root = str(request.base_url).rstrip("/")
    return PairingCodeResponse(
        code=code,
        expires_at=expires.isoformat(),
        kb_name=body.kb_name.strip(),
        command=(
            f"deeptutor mn4 bridge pair --server {root} --code {code} "
            "--notebook '~/MarginNote-Exports'"
        ),
    )


@router.post("/devices/pair", response_model=PairResponse)
async def pair_device(body: PairRequest, request: Request) -> PairResponse:
    _transport_allowed(request)
    registry = DeviceRegistry()
    try:
        pairing = registry.consume_pairing_code(body.code)
        device, token = registry.register_device(
            pairing,
            device_name=body.device_name.strip(),
            device_kind=body.device_kind.strip() or "macos",
        )
        MarginNoteStore(pairing["db_path"]).install_device(
            device_id=device["device_id"],
            user_id=device["user_id"],
            kb_id=device["kb_id"],
            kb_name=device["kb_name"],
            device_name=device["device_name"],
            device_kind=device["device_kind"],
            token=token,
            paired_at=device["paired_at"],
        )
    except DeviceRegistryError as exc:
        raise HTTPException(400, str(exc)) from exc
    return PairResponse(
        device_id=device["device_id"],
        token=token,
        user_id=device["user_id"],
        kb_id=device["kb_id"],
        kb_name=device["kb_name"],
        device_name=device["device_name"],
        device_kind=device["device_kind"],
    )


@router.get("/devices", response_model=list[DeviceInfo], dependencies=_auth)
async def list_devices(
    request: Request,
    kb_name: str = Query(...),
    include_inactive: bool = False,
) -> list[DeviceInfo]:
    _transport_allowed(request)
    user_id, kb_id, _store = _session_store(kb_name)
    return [
        DeviceInfo(**item)
        for item in DeviceRegistry().list_devices(
            user_id=user_id, kb_id=kb_id, include_inactive=include_inactive
        )
    ]


@router.delete("/devices/{device_id}", dependencies=_auth)
async def revoke_device(
    device_id: str, request: Request, kb_name: str = Query(...)
) -> dict[str, str]:
    _transport_allowed(request)
    user_id, _kb_id, _store = _session_store(kb_name)
    if not DeviceRegistry().revoke(device_id, user_id=user_id):
        raise HTTPException(404, "Device not found")
    return {"status": "revoked", "device_id": device_id}


@router.get("/status", dependencies=_auth)
async def bridge_status(request: Request, kb_name: str = Query(...)) -> dict[str, Any]:
    _transport_allowed(request)
    _user_id, _kb_id, store = _session_store(kb_name)
    return {
        "status": "ready",
        "object_count": store.count(),
        "pending_writebacks": len(
            store.list_writebacks(user_id=get_current_user().id, status="pending_confirmation")
        ),
    }


@router.post("/sync/batches", response_model=SyncResponse)
async def sync_batch(
    body: SyncRequest,
    request: Request,
    authorization: str | None = Header(None),
) -> SyncResponse:
    identity, store = _device_auth(request, authorization)
    objects = [
        MarginNoteObject(
            **item.model_dump(exclude={"object_hash"}),
            device_id=identity["device_id"],
        )
        for item in body.objects
    ]
    batch = SyncBatch(
        device_id=identity["device_id"],
        sync_id=body.sync_id,
        sequence=body.sequence,
        final=body.final,
        base_cursor=body.base_cursor,
        snapshot_hash=body.snapshot_hash,
        objects=objects,
        deleted_ids=body.deleted_ids,
    )
    try:
        result = store.ingest(batch)
    except BulkDeleteGuard as exc:
        raise HTTPException(409, str(exc)) from exc
    except (SyncConflict, MarginNoteStoreError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return SyncResponse(**result.to_dict())


@router.post("/writebacks", dependencies=_auth)
async def create_writeback(body: WritebackCreateRequest, request: Request) -> dict[str, Any]:
    _transport_allowed(request)
    user_id, kb_id, store = _session_store(body.kb_name)
    try:
        return store.create_writeback(
            user_id=user_id,
            kb_id=kb_id,
            payload=WritebackPayload(
                title=body.title,
                markdown=body.markdown,
                tags=body.tags,
                source_refs=body.source_refs,
                target_notebook=body.target_notebook,
            ),
        )
    except WritebackStateError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/writebacks", dependencies=_auth)
async def list_writebacks(
    request: Request, kb_name: str = Query(...), status: str = ""
) -> dict[str, Any]:
    _transport_allowed(request)
    user_id, kb_id, store = _session_store(kb_name)
    items = store.list_writebacks(user_id=user_id, kb_id=kb_id, status=status)
    return {"count": len(items), "writebacks": items}


@router.post("/writebacks/{writeback_id}/approve", dependencies=_auth)
async def approve_writeback(
    writeback_id: str, body: WritebackActionRequest, request: Request
) -> dict[str, Any]:
    _transport_allowed(request)
    user_id, _kb_id, store = _session_store(body.kb_name)
    try:
        return store.approve_writeback(writeback_id, user_id=user_id)
    except WritebackStateError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/writebacks/{writeback_id}/reject", dependencies=_auth)
async def reject_writeback(
    writeback_id: str, body: WritebackActionRequest, request: Request
) -> dict[str, Any]:
    _transport_allowed(request)
    user_id, _kb_id, store = _session_store(body.kb_name)
    try:
        return store.reject_writeback(writeback_id, user_id=user_id)
    except WritebackStateError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/writebacks/{writeback_id}/imported", dependencies=_auth)
async def mark_writeback_imported(
    writeback_id: str, body: WritebackActionRequest, request: Request
) -> dict[str, Any]:
    _transport_allowed(request)
    user_id, _kb_id, store = _session_store(body.kb_name)
    try:
        return store.mark_imported(writeback_id, user_id=user_id)
    except WritebackStateError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/jobs/claim")
async def claim_job(request: Request, authorization: str | None = Header(None)) -> dict[str, Any]:
    identity, store = _device_auth(request, authorization)
    job = store.claim_writeback(device_id=identity["device_id"])
    return {"job": job}


@router.post("/jobs/renew")
async def renew_job(
    body: LeaseRequest,
    request: Request,
    authorization: str | None = Header(None),
) -> dict[str, Any]:
    identity, store = _device_auth(request, authorization)
    try:
        return store.renew_writeback(
            body.writeback_id,
            device_id=identity["device_id"],
            lease_token=body.lease_token,
            ttl_seconds=body.ttl_seconds,
        )
    except WritebackStateError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/jobs/complete")
async def complete_job(
    body: ReceiptRequest,
    request: Request,
    authorization: str | None = Header(None),
) -> dict[str, Any]:
    identity, store = _device_auth(request, authorization)
    try:
        return store.complete_writeback(
            body.writeback_id,
            device_id=identity["device_id"],
            lease_token=body.lease_token,
            result=body.result,
            payload_hash=body.payload_hash,
            delivery_mode=body.delivery_mode,
            provider=body.provider,
            external_id=body.external_id,
            written_at=body.written_at,
            error=body.error,
        )
    except WritebackStateError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/automation/verification")
async def get_automation_verification(
    request: Request,
    provider: str = Query(...),
    bundle_id: str = Query(""),
    app_version: str = Query(""),
    config_hash: str = Query(...),
    authorization: str | None = Header(None),
) -> dict[str, bool | str]:
    identity, store = _device_auth(request, authorization)
    verified = store.is_automation_verified(
        device_id=identity["device_id"],
        provider=provider,
        bundle_id=bundle_id,
        app_version=app_version,
        config_hash=config_hash,
    )
    return {
        "verified": verified,
        "device_id": identity["device_id"],
        "reason": "" if verified else "Automation verification is missing or stale",
    }


@router.post("/automation/verification")
async def record_automation_verification(
    body: AutomationVerificationRequest,
    request: Request,
    authorization: str | None = Header(None),
) -> dict[str, str]:
    identity, store = _device_auth(request, authorization)
    if body.provider not in {"applescript", "shortcut", "url_scheme"}:
        raise HTTPException(400, "Unknown automation provider")
    if not body.bundle_id.strip() or not body.app_version.strip() or not body.config_hash.strip():
        raise HTTPException(400, "Bundle, version, and config hash are required")
    if body.provider == "url_scheme" and not body.test_external_id.strip():
        raise HTTPException(400, "URL Scheme verification requires the confirmed test note ID")
    if not body.verified:
        raise HTTPException(400, "Automation provider was not verified")
    store.set_automation_verification(
        device_id=identity["device_id"],
        provider=body.provider,
        bundle_id=body.bundle_id,
        app_version=body.app_version,
        config_hash=body.config_hash,
        test_external_id=body.test_external_id,
    )
    return {"status": "verified", "device_id": identity["device_id"]}


__all__ = ["router"]
