"""HTTP contract for the MarginNote 4 connected-learning bridge.

Session routes use the normal DeepTutor account context. Device routes use a
revocable bearer token and resolve user/library exclusively from the stored
device binding. No route accepts a client-selected MN4 database identifier.
"""

from __future__ import annotations

from dataclasses import asdict
import ipaddress
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_auth
from deeptutor.multi_user.context import get_current_user
from deeptutor.services.marginnote4.models import MARGINNOTE4_PROTOCOL_VERSION
from deeptutor.services.marginnote4.service import (
    InvalidRequest,
    MarginNote4Service,
    OperationConflict,
    UnauthorizedDevice,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def get_marginnote4_service(request: Request) -> MarginNote4Service:
    existing = getattr(request.app.state, "marginnote4_service", None)
    if existing is not None:
        return existing
    from deeptutor.services.config import PROJECT_ROOT

    root = PROJECT_ROOT / "data" / "system" / "marginnote4" / "bridge.sqlite3"
    service = MarginNote4Service(root)
    request.app.state.marginnote4_service = service
    return service


def _current_user_id() -> str:
    return get_current_user().id


def _fields(value: object) -> dict[str, object]:
    return asdict(value)


def _assert_device_transport(request: Request) -> None:
    if getattr(request.app.state, "marginnote4_allow_test_transport", False):
        return
    host = request.client.host if request.client else ""
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if loopback:
        return
    trusted_headers = bool(getattr(request.app.state, "marginnote4_trust_forwarded_proto", False))
    proto = request.headers.get("x-forwarded-proto") if trusted_headers else None
    scheme = (proto or request.url.scheme).lower()
    if scheme != "https":
        raise HTTPException(
            status_code=403,
            detail="Non-loopback MarginNote 4 devices must use HTTPS or a trusted HTTPS tunnel",
        )


def _device(request: Request, authorization: str | None, service: MarginNote4Service):
    _assert_device_transport(request)
    scheme, separator, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not separator or not token:
        raise HTTPException(status_code=401, detail="Missing MN4 device bearer token")
    try:
        return service.authenticate_device(token)
    except UnauthorizedDevice as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, (InvalidRequest, ValueError)):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, UnauthorizedDevice):
        return HTTPException(status_code=401, detail=str(exc))
    if isinstance(exc, OperationConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=500, detail="MarginNote 4 bridge error")


class CreatePairingRequest(BaseModel):
    library_id: str = Field(min_length=1, max_length=256)
    library_name: str = Field(default="", max_length=512)
    ttl_minutes: int = Field(default=10, ge=1, le=60)


class PairingSessionResponse(BaseModel):
    session_id: str
    status: str
    library_id: str
    library_name: str
    device_id: str | None = None
    device_name: str = ""
    device_kind: str = "macos"
    created_at: str
    updated_at: str
    expires_at: str


class PairingCodeResponse(BaseModel):
    session: PairingSessionResponse
    pairing_code: str
    protocol_version: int


class ClaimRequest(BaseModel):
    pairing_code: str = Field(min_length=1, max_length=64)
    device_name: str = Field(min_length=1, max_length=200)
    device_kind: str = Field(pattern="^(macos|ipados)$")


class ClaimResponse(BaseModel):
    session_id: str
    device_id: str
    claim_secret: str
    status: str
    protocol_version: int


class CompleteClaimRequest(BaseModel):
    claim_secret: str = Field(min_length=1)


class DeviceTokenResponse(BaseModel):
    device_id: str
    token: str
    token_type: str = "Bearer"
    protocol_version: int


class SyncObject(BaseModel):
    object_id: str = Field(min_length=1, max_length=256)
    object_type: str
    revision: int = Field(gt=0)
    title: str = ""
    content: str = ""
    excerpt: str | None = None
    document_id: str | None = None
    document_title: str | None = None
    page: int | None = None
    tags: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    color: str | None = None
    source_locator: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class SyncDeletion(BaseModel):
    object_id: str = Field(min_length=1, max_length=256)
    revision: int = Field(gt=0)


class PushRequest(BaseModel):
    protocol_version: int
    operation_id: str = Field(min_length=1, max_length=128)
    objects: list[SyncObject] = Field(default_factory=list)
    deletions: list[SyncDeletion] = Field(default_factory=list)


class PushResponse(BaseModel):
    operation_id: str
    cursor: str
    accepted: int
    updated: int
    deleted: int
    ignored_stale: int
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    replayed: bool = False
    protocol_version: int = MARGINNOTE4_PROTOCOL_VERSION


class PullResponse(BaseModel):
    cursor: str
    has_more: bool
    changes: list[dict[str, Any]]
    protocol_version: int = MARGINNOTE4_PROTOCOL_VERSION


@router.post("/pairing-sessions", response_model=PairingCodeResponse)
async def create_pairing_session(
    payload: CreatePairingRequest,
    service: MarginNote4Service = Depends(get_marginnote4_service),
    _: object = Depends(require_auth),
) -> PairingCodeResponse:
    try:
        session, code = service.create_pairing_session(
            user_id=_current_user_id(),
            library_id=payload.library_id,
            library_name=payload.library_name,
            ttl_minutes=payload.ttl_minutes,
        )
    except Exception as exc:
        raise _error(exc) from exc
    return PairingCodeResponse(
        session=PairingSessionResponse(**_fields(session)),
        pairing_code=code,
        protocol_version=MARGINNOTE4_PROTOCOL_VERSION,
    )


@router.get("/pairing-sessions", response_model=list[PairingSessionResponse])
async def list_pairing_sessions(
    service: MarginNote4Service = Depends(get_marginnote4_service),
    _: object = Depends(require_auth),
) -> list[PairingSessionResponse]:
    return [
        PairingSessionResponse(**_fields(session))
        for session in service.list_pairing_sessions(_current_user_id())
    ]


@router.post("/pairing-sessions/{session_id}/confirm", response_model=PairingSessionResponse)
async def confirm_pairing_session(
    session_id: str,
    service: MarginNote4Service = Depends(get_marginnote4_service),
    _: object = Depends(require_auth),
) -> PairingSessionResponse:
    try:
        session = service.confirm_pairing_session(user_id=_current_user_id(), session_id=session_id)
    except Exception as exc:
        raise _error(exc) from exc
    return PairingSessionResponse(**_fields(session))


@router.post("/pairing-sessions/{session_id}/cancel", response_model=PairingSessionResponse)
async def cancel_pairing_session(
    session_id: str,
    service: MarginNote4Service = Depends(get_marginnote4_service),
    _: object = Depends(require_auth),
) -> PairingSessionResponse:
    try:
        session = service.cancel_pairing_session(user_id=_current_user_id(), session_id=session_id)
    except Exception as exc:
        raise _error(exc) from exc
    return PairingSessionResponse(**_fields(session))


@router.post("/device/claim", response_model=ClaimResponse)
async def claim_pairing_session(
    payload: ClaimRequest,
    request: Request,
    service: MarginNote4Service = Depends(get_marginnote4_service),
) -> ClaimResponse:
    _assert_device_transport(request)
    try:
        result = service.claim_pairing_session(
            pairing_code=payload.pairing_code,
            device_name=payload.device_name,
            device_kind=payload.device_kind,
        )
    except Exception as exc:
        raise _error(exc) from exc
    return ClaimResponse(**result, protocol_version=MARGINNOTE4_PROTOCOL_VERSION)


@router.post("/device/{device_id}/token", response_model=DeviceTokenResponse)
async def complete_device_pairing(
    device_id: str,
    payload: CompleteClaimRequest,
    request: Request,
    service: MarginNote4Service = Depends(get_marginnote4_service),
) -> DeviceTokenResponse:
    _assert_device_transport(request)
    try:
        token, _status = service.complete_pairing(
            device_id=device_id, claim_secret=payload.claim_secret
        )
    except Exception as exc:
        raise _error(exc) from exc
    if not token:
        raise HTTPException(status_code=409, detail="Pairing is claimed but not confirmed yet")
    return DeviceTokenResponse(
        device_id=device_id,
        token=token,
        protocol_version=MARGINNOTE4_PROTOCOL_VERSION,
    )


@router.post("/device/sync", response_model=PushResponse)
async def push_objects(
    payload: PushRequest,
    request: Request,
    service: MarginNote4Service = Depends(get_marginnote4_service),
    authorization: str | None = Header(default=None),
) -> PushResponse:
    device = _device(request, authorization, service)
    try:
        result = service.push(
            device,
            protocol_version=payload.protocol_version,
            operation_id=payload.operation_id,
            objects=[item.model_dump() for item in payload.objects],
            deletions=[item.model_dump() for item in payload.deletions],
        )
    except Exception as exc:
        raise _error(exc) from exc
    return PushResponse(**_fields(result))


@router.get("/device/changes", response_model=PullResponse)
async def pull_changes(
    request: Request,
    cursor: str = Query(default="0"),
    limit: int = Query(default=500, ge=1, le=1000),
    service: MarginNote4Service = Depends(get_marginnote4_service),
    authorization: str | None = Header(default=None),
) -> PullResponse:
    device = _device(request, authorization, service)
    try:
        result = service.pull(device, cursor=cursor, limit=limit)
    except Exception as exc:
        raise _error(exc) from exc
    return PullResponse(**_fields(result))


@router.post("/device/heartbeat")
async def device_heartbeat(
    request: Request,
    service: MarginNote4Service = Depends(get_marginnote4_service),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    device = _device(request, authorization, service)
    return service.heartbeat(device)


@router.get("/devices")
async def list_devices(
    service: MarginNote4Service = Depends(get_marginnote4_service),
    _: object = Depends(require_auth),
) -> list[dict[str, Any]]:
    return [_fields(device) for device in service.list_devices(_current_user_id())]


@router.post("/devices/{device_id}/rotate-token", response_model=DeviceTokenResponse)
async def rotate_device_token(
    device_id: str,
    service: MarginNote4Service = Depends(get_marginnote4_service),
    _: object = Depends(require_auth),
) -> DeviceTokenResponse:
    try:
        token = service.rotate_device_token(user_id=_current_user_id(), device_id=device_id)
    except Exception as exc:
        raise _error(exc) from exc
    return DeviceTokenResponse(
        device_id=device_id,
        token=token,
        protocol_version=MARGINNOTE4_PROTOCOL_VERSION,
    )


@router.delete("/devices/{device_id}")
async def revoke_device(
    device_id: str,
    service: MarginNote4Service = Depends(get_marginnote4_service),
    _: object = Depends(require_auth),
) -> dict[str, str]:
    try:
        service.revoke_device(user_id=_current_user_id(), device_id=device_id)
    except Exception as exc:
        raise _error(exc) from exc
    return {"status": "revoked", "device_id": device_id}


@router.get("/status")
async def bridge_status(
    library_id: str = "",
    service: MarginNote4Service = Depends(get_marginnote4_service),
    _: object = Depends(require_auth),
) -> dict[str, Any]:
    return service.status(user_id=_current_user_id(), library_id=library_id)
