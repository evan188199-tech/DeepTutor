"""Authenticated bridge for external video renderer remote control."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import re
import secrets
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_learning_surface
from deeptutor.multi_user.paths import current_owner_id
from deeptutor.services.auth import TokenPayload
from deeptutor.services.path_service import PathService
from deeptutor.services.tunnel_handoff import (
    HandoffCookie,
    SessionHandoff,
    create_pairing,
    load_tunnel_state,
)
from deeptutor.video_learning import service
from deeptutor.video_learning.marks import create_mark, delete_mark, marks_list, update_mark
from deeptutor.video_learning.models import Device, PlayerSession
from deeptutor.video_learning.remote import (
    RemoteControlConflict,
    RemoteControlError,
    RemoteControlNotFound,
    RemoteControlStore,
    default_remote_db_path,
)

router = APIRouter()
_auth = [Depends(require_learning_surface)]
_VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
_MATERIAL_ID_RE = re.compile(r"[0-9a-f]{16,64}")


class RendererCreateRequest(BaseModel):
    device_name: str = Field(default="Renderer", max_length=128)
    device_kind: str = Field(default="renderer", max_length=32)
    renderer_origin: str | None = Field(default=None, max_length=2048)
    video_id: str | None = Field(default=None, min_length=11, max_length=11)
    material_id: str | None = Field(default=None, min_length=16, max_length=64)
    position_seconds: int = Field(default=0, ge=0, le=24 * 60 * 60)


class RendererBootstrapRequest(BaseModel):
    ticket: str = Field(min_length=32, max_length=256)


class PlayerSyncRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)
    renderer_origin: str = Field(default="", max_length=2048)
    video_id: str = Field(min_length=11, max_length=11)
    title: str = Field(default="", max_length=512)
    position_ms: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    playback_state: str = Field(default="unknown", max_length=32)
    playback_rate: float = Field(default=1.0, gt=0, le=4)


class CommandRequest(BaseModel):
    command_id: str | None = Field(default=None, max_length=64)
    type: str = Field(max_length=16)
    position_ms: int | None = Field(default=None, ge=0)
    delta_ms: int | None = Field(default=None)
    volume: int | None = Field(default=None, ge=0, le=100)
    muted: bool | None = None
    playback_rate: float | None = Field(default=None, gt=0, le=4)


class CommandAckRequest(BaseModel):
    ok: bool = True
    error: str | None = Field(default=None, max_length=512)


class DeviceCommandRequest(BaseModel):
    type: str = Field(max_length=32)
    video_id: str = Field(min_length=11, max_length=11)


class AnnotationCreateRequest(BaseModel):
    kind: str = Field(default="key_point", max_length=32)
    note: str = Field(default="", max_length=2000)


class AnnotationUpdateRequest(BaseModel):
    note: str = Field(default="", max_length=2000)
    reviewed: bool | None = None


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RemoteControlNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, RemoteControlConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, service.TimedMediaNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, service.TimedMediaError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def _db_path() -> Path:
    return default_remote_db_path()


def _auth_device(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> tuple[Device, RemoteControlStore]:
    scheme, separator, raw = (authorization or "").partition(" ")
    if not separator or scheme != "VideoLearning" or ":" not in raw:
        raise HTTPException(status_code=401, detail="Missing or malformed renderer credentials.")
    device_id, token = raw.split(":", 1)
    store = RemoteControlStore.open_existing(_db_path())
    if store is None:
        raise HTTPException(status_code=403, detail="Invalid renderer credentials.")
    device = store.verify_token(device_id, token)
    if device is None:
        raise HTTPException(status_code=403, detail="Invalid renderer credentials.")
    store.touch_device(device_id)
    return device, store


def _validate_origin(value: str | None) -> str:
    try:
        normalized = service._validate_origin(value)
    except service.TimedMediaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not normalized:
        raise HTTPException(status_code=400, detail="A renderer origin is required.")
    return normalized


def _timed_media_store_for(
    store: RemoteControlStore, workspace_root: str
) -> service.TimedMediaStore:
    if not workspace_root:
        raise HTTPException(status_code=409, detail="Renderer workspace binding is unavailable.")
    return service.TimedMediaStore(
        root=PathService(workspace_root=Path(workspace_root)).get_workspace_feature_dir(
            "timed_media"
        )
    )


def _ensure_material(
    store: RemoteControlStore,
    workspace_root: str,
    video_id: str,
    title: str = "",
    duration_ms: int = 0,
) -> dict[str, Any]:
    timed_store = _timed_media_store_for(store, workspace_root)
    material_id = service.material_id_for(video_id)
    try:
        material = timed_store.get(material_id)
    except service.TimedMediaNotFound:
        material = timed_store.save(
            {
                "version": 1,
                "type": "timed_media",
                "material_id": material_id,
                "created_at": service.datetime.now(service.timezone.utc).isoformat(),
                "source": {
                    "provider": "youtube",
                    "video_id": video_id,
                    "url": f"https://youtu.be/{video_id}",
                    "entry_time_seconds": 0,
                },
                "metadata": {
                    "title": title,
                    "author": "",
                    "duration_seconds": max(0.0, duration_ms / 1000),
                },
                "transcript": {"status": "unavailable", "reason": "remote_renderer", "language": "", "source": "", "cues": []},
                "segments": [],
                "learning": {"last_position": 0},
            }
        )
    return material


def _controller_session(
    store: RemoteControlStore,
    session_id: str,
    controller_cookie: str | None,
    *,
    required: bool = False,
) -> PlayerSession:
    session = store.get_session(session_id, current_owner_id())
    if session is None:
        raise HTTPException(status_code=404, detail="Player session was not found.")
    if session.controller_token_hash and not store.verify_controller(
        current_owner_id(), session_id, controller_cookie
    ):
        raise HTTPException(status_code=403, detail="This phone is not bound to the current player session.")
    if required and not session.controller_token_hash:
        raise HTTPException(status_code=403, detail="Create a phone handoff before using this endpoint.")
    return session


def _session_material(store: RemoteControlStore, session: PlayerSession) -> dict[str, Any]:
    if not session.material_id:
        raise HTTPException(status_code=409, detail="The renderer has not bound a learning material yet.")
    timed_store = _timed_media_store_for(store, store.workspace_for_device(session.device_id))
    try:
        material = timed_store.get(session.material_id)
    except service.TimedMediaNotFound as exc:
        raise HTTPException(status_code=404, detail="The bound learning material is unavailable.") from exc
    source = material.get("source") if isinstance(material.get("source"), dict) else {}
    if str(source.get("video_id") or "") != session.video_id:
        raise HTTPException(status_code=409, detail="The renderer changed videos. Refresh the phone handoff.")
    return material


@router.post("/renderers", dependencies=_auth)
async def create_renderer(
    payload: RendererCreateRequest, response: Response, account: TokenPayload | None = Depends(require_learning_surface)
) -> dict[str, Any]:
    settings = service.load_video_learning_settings()
    configured = settings["invidious"]["public_base_url"] or settings["invidious"]["api_base_url"]
    origin = _validate_origin(payload.renderer_origin or configured)
    video_id = payload.video_id or ""
    material_id = payload.material_id or ""
    if video_id and not _VIDEO_ID_RE.fullmatch(video_id):
        raise HTTPException(status_code=400, detail="Invalid YouTube video id.")
    if material_id and not _MATERIAL_ID_RE.fullmatch(material_id):
        raise HTTPException(status_code=400, detail="Invalid learning material id.")
    if material_id:
        try:
            service.get_timed_media_store().get(material_id)
        except service.TimedMediaNotFound as exc:
            raise HTTPException(status_code=404, detail="Learning material was not found.") from exc
    elif video_id:
        material_id = service.material_id_for(video_id)
    owner_id = current_owner_id()
    bootstrap_id, ticket, expires_at = RemoteControlStore(_db_path()).create_bootstrap(
        owner_id=owner_id,
        username=account.username if account else "local",
        role=account.role if account else "admin",
        token_user_id=account.user_id if account else owner_id,
        device_name=payload.device_name,
        device_kind=payload.device_kind,
        workspace_root=str(service.get_current_path_service().workspace_root),
        renderer_origin=origin,
        material_id=material_id,
        video_id=video_id,
        position_ms=payload.position_seconds * 1000,
    )
    path = "/watch"
    query = ""
    if video_id:
        query = f"?v={quote(video_id, safe='')}"
        if payload.position_seconds > 1:
            query += f"&t={payload.position_seconds}"
    else:
        path = "/feed/popular"
    launch_url = f"{origin}{path}{query}#dt_bootstrap={quote(ticket, safe='')}"
    response.headers["Cache-Control"] = "no-store"
    return {
        "bootstrap_id": bootstrap_id,
        "ticket": ticket,
        "expires_at": expires_at,
        "launch_url": launch_url,
        "renderer_origin": origin,
        "material_id": material_id,
    }


@router.post("/renderers/bootstrap")
async def bootstrap_renderer(payload: RendererBootstrapRequest, response: Response) -> dict[str, Any]:
    store = RemoteControlStore.open_existing(_db_path())
    if store is None:
        raise HTTPException(status_code=404, detail="Renderer bootstrap was not found.")
    try:
        device, token, bootstrap = store.redeem_bootstrap(payload.ticket)
    except RemoteControlError as exc:
        raise _http_error(exc) from exc
    response.headers["Cache-Control"] = "no-store"
    return {
        "device_id": device.device_id,
        "token": token,
        "device_name": device.device_name,
        "device_kind": device.device_kind,
        "renderer_origin": str(bootstrap["renderer_origin"] or ""),
        "material_id": str(bootstrap["material_id"] or ""),
        "video_id": str(bootstrap["video_id"] or ""),
        "position_ms": int(bootstrap["position_ms"] or 0),
    }


@router.get("/devices", dependencies=_auth)
async def list_devices() -> list[dict[str, Any]]:
    store = RemoteControlStore(_db_path())
    return [
        {
            "device_id": device.device_id,
            "device_name": device.device_name,
            "device_kind": device.device_kind,
            "paired_at": device.paired_at,
            "last_seen": device.last_seen,
            "online": store.device_is_online(device),
            "capabilities": ["open_video"],
        }
        for device in store.list_devices(current_owner_id())
    ]


@router.delete("/devices/{device_id}", dependencies=_auth)
async def revoke_device(device_id: str) -> dict[str, str]:
    if not RemoteControlStore(_db_path()).revoke_device(current_owner_id(), device_id):
        raise HTTPException(status_code=404, detail="Renderer device was not found.")
    return {"status": "revoked", "device_id": device_id}


@router.post("/devices/{device_id}/commands", dependencies=_auth)
async def create_device_command(device_id: str, payload: DeviceCommandRequest) -> dict[str, Any]:
    if payload.type != "open_video" or not _VIDEO_ID_RE.fullmatch(payload.video_id):
        raise HTTPException(status_code=400, detail="Invalid open_video command.")
    store = RemoteControlStore(_db_path())
    try:
        command = store.enqueue_device_command(
            owner_id=current_owner_id(), device_id=device_id, video_id=payload.video_id
        )
    except RemoteControlError as exc:
        raise _http_error(exc) from exc
    return asdict(command)


@router.get("/devices/{device_id}/commands/{command_id}", dependencies=_auth)
async def get_device_command(device_id: str, command_id: str) -> dict[str, Any]:
    command = RemoteControlStore(_db_path()).get_device_command(
        current_owner_id(), device_id, command_id
    )
    if command is None:
        raise HTTPException(status_code=404, detail="Device command was not found.")
    return asdict(command)


@router.post("/player/presence")
async def player_presence(auth=Depends(_auth_device)) -> dict[str, Any]:
    device, store = auth
    return {
        "device_id": device.device_id,
        "online": True,
        "commands": [asdict(command) for command in store.pending_device_commands(device.device_id)],
    }


@router.post("/player/device-commands/{command_id}/ack")
async def ack_device_command(
    command_id: str, payload: CommandAckRequest, auth=Depends(_auth_device)
) -> dict[str, Any]:
    device, store = auth
    try:
        command = store.ack_device_command(
            device.device_id, command_id, payload.ok, payload.error
        )
    except RemoteControlError as exc:
        raise _http_error(exc) from exc
    return asdict(command)


@router.post("/player/sync")
async def player_sync(payload: PlayerSyncRequest, auth=Depends(_auth_device)) -> dict[str, Any]:
    device, store = auth
    renderer_origin = _validate_origin(payload.renderer_origin)
    if not _VIDEO_ID_RE.fullmatch(payload.video_id):
        raise HTTPException(status_code=400, detail="Invalid YouTube video id.")
    material = _ensure_material(
        store,
        device.workspace_root,
        payload.video_id,
        payload.title,
        payload.duration_ms,
    )
    material_id = str(material["material_id"])
    try:
        session = store.upsert_session(
            device=device,
            session_id=payload.session_id,
            renderer_origin=renderer_origin,
            video_id=payload.video_id,
            title=payload.title,
            position_ms=payload.position_ms,
            duration_ms=payload.duration_ms,
            playback_state=payload.playback_state,
            playback_rate=payload.playback_rate,
            material_id=material_id,
        )
    except RemoteControlError as exc:
        raise _http_error(exc) from exc
    return {
        "session": {**asdict(session), "online": True},
        "commands": [asdict(command) for command in store.pending_commands(device.device_id, session.session_id)],
    }


@router.post("/player/commands/{command_id}/ack")
async def ack_player_command(
    command_id: str, payload: CommandAckRequest, auth=Depends(_auth_device)
) -> dict[str, Any]:
    device, store = auth
    try:
        command = store.ack_command(device.device_id, command_id, payload.ok, payload.error)
    except RemoteControlError as exc:
        raise _http_error(exc) from exc
    return asdict(command)


@router.post("/player/phone-handoff")
async def create_player_phone_handoff(
    response: Response, auth=Depends(_auth_device)
) -> dict[str, Any]:
    device, store = auth
    session = store.latest_session(device.device_id)
    if session is None or not store.session_is_online(session):
        raise HTTPException(status_code=409, detail="Start playing a video before creating a phone handoff.")
    controller_secret = secrets.token_urlsafe(32)
    session = store.issue_controller(device.owner_id, session.session_id, controller_secret)
    if session is None:
        raise HTTPException(status_code=404, detail="Player session was not found.")
    state = load_tunnel_state()
    if state is None:
        raise HTTPException(status_code=503, detail="No active DeepTutor tunnel is configured.")
    with store._connect() as conn:  # noqa: SLF001 - owner-bound internal reader
        row = conn.execute(
            """SELECT b.username, b.role, b.token_user_id
               FROM renderer_bootstraps AS b
               JOIN devices AS d ON d.bootstrap_id = b.bootstrap_id
               WHERE d.device_id = ? AND d.owner_id = ?""",
            (device.device_id, device.owner_id),
        ).fetchone()
    payload_user = TokenPayload(
        username=str(row["username"] or "local") if row else "local",
        role=str(row["role"] or "user") if row else "user",
        user_id=str(row["token_user_id"] or "") if row else "",
    )
    redirect_path = (
        f"/chat?capability=immersive_watching&viewer_session={quote(session.session_id, safe='')}"
    )
    try:
        pairing_id, expires_in = create_pairing(
            payload_user,
            handoff=SessionHandoff(
                redirect_path=redirect_path,
                cookies=(
                    HandoffCookie(
                        name="dt_video_controller",
                        value=f"{session.session_id}:{controller_secret}",
                        path="/",
                        max_age=12 * 60 * 60,
                    ),
                ),
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Phone handoff could not be created.") from exc
    qr_url = f"{state.url}/access/device?pairing={quote(pairing_id, safe='')}"
    response.headers["Cache-Control"] = "no-store"
    return {"session_id": session.session_id, "qr_url": qr_url, "expires_in": expires_in}


@router.get("/sessions", dependencies=_auth)
async def list_sessions() -> dict[str, Any]:
    return {"sessions": RemoteControlStore(_db_path()).list_sessions(current_owner_id())}


@router.post("/sessions/{session_id}/commands", dependencies=_auth)
async def create_session_command(
    session_id: str,
    payload: CommandRequest,
    dt_video_controller: str | None = Cookie(default=None, alias="dt_video_controller"),
) -> dict[str, Any]:
    store = RemoteControlStore(_db_path())
    session = _controller_session(store, session_id, dt_video_controller)
    body: dict[str, Any] = {}
    if payload.type in {"play", "pause", "fullscreen"}:
        pass
    elif payload.type == "seek":
        if payload.position_ms is not None:
            body["position_ms"] = payload.position_ms
        elif payload.delta_ms is not None:
            body["position_ms"] = max(0, session.position_ms + payload.delta_ms)
        else:
            raise HTTPException(status_code=400, detail="seek requires position_ms or delta_ms.")
    elif payload.type == "volume":
        if payload.volume is None:
            raise HTTPException(status_code=400, detail="volume requires a value from 0 to 100.")
        body["volume"] = payload.volume
    elif payload.type == "mute":
        if payload.muted is None:
            raise HTTPException(status_code=400, detail="mute requires muted.")
        body["muted"] = payload.muted
    elif payload.type == "playback_rate":
        if payload.playback_rate is None:
            raise HTTPException(status_code=400, detail="playback_rate requires a value.")
        body["playback_rate"] = payload.playback_rate
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported command type: {payload.type}")
    try:
        command = store.enqueue_command(
            session=session, command_type=payload.type, payload=body, command_id=payload.command_id
        )
    except RemoteControlError as exc:
        raise _http_error(exc) from exc
    return asdict(command)


@router.get("/sessions/{session_id}/commands/{command_id}", dependencies=_auth)
async def get_session_command(session_id: str, command_id: str) -> dict[str, Any]:
    command = RemoteControlStore(_db_path()).get_command(command_id, current_owner_id())
    if command is None or command.session_id != session_id:
        raise HTTPException(status_code=404, detail="Player command was not found.")
    return asdict(command)


@router.get("/sessions/{session_id}/annotations", dependencies=_auth)
async def list_session_annotations(
    session_id: str,
    dt_video_controller: str | None = Cookie(default=None, alias="dt_video_controller"),
) -> dict[str, Any]:
    store = RemoteControlStore(_db_path())
    session = _controller_session(store, session_id, dt_video_controller, required=True)
    material = _session_material(store, session)
    return {"annotations": marks_list(material)}


@router.post("/sessions/{session_id}/annotations", status_code=201, dependencies=_auth)
async def create_session_annotation(
    session_id: str,
    payload: AnnotationCreateRequest,
    dt_video_controller: str | None = Cookie(default=None, alias="dt_video_controller"),
) -> dict[str, Any]:
    store = RemoteControlStore(_db_path())
    session = _controller_session(store, session_id, dt_video_controller, required=True)
    material = _session_material(store, session)
    timestamp = max(0.0, session.position_ms / 1000)
    timed_store = _timed_media_store_for(store, store.workspace_for_device(session.device_id))
    try:
        with timed_store.lock(str(material["material_id"])):
            material = timed_store.get(str(material["material_id"]))
            mark = create_mark(
                material,
                {
                    "kind": payload.kind,
                    "start_seconds": timestamp,
                    "end_seconds": timestamp,
                    "note": payload.note.strip(),
                    "author": "user",
                    "source": "remote_phone",
                    "metadata": {
                        "session_id": session.session_id,
                        "renderer_origin": session.instance_origin,
                        "video_id": session.video_id,
                    },
                },
            )
            timed_store.save(material)
    except service.TimedMediaError as exc:
        raise _http_error(exc) from exc
    return mark


@router.patch("/sessions/{session_id}/annotations/{mark_id}", dependencies=_auth)
async def update_session_annotation(
    session_id: str,
    mark_id: str,
    payload: AnnotationUpdateRequest,
    dt_video_controller: str | None = Cookie(default=None, alias="dt_video_controller"),
) -> dict[str, Any]:
    store = RemoteControlStore(_db_path())
    session = _controller_session(store, session_id, dt_video_controller, required=True)
    material = _session_material(store, session)
    timed_store = _timed_media_store_for(store, store.workspace_for_device(session.device_id))
    fields: dict[str, Any] = {"note": payload.note.strip()}
    if payload.reviewed is not None:
        fields["reviewed"] = payload.reviewed
    try:
        with timed_store.lock(str(material["material_id"])):
            material = timed_store.get(str(material["material_id"]))
            mark = update_mark(material, mark_id, fields)
            timed_store.save(material)
    except service.TimedMediaError as exc:
        raise _http_error(exc) from exc
    return mark


@router.delete("/sessions/{session_id}/annotations/{mark_id}", dependencies=_auth)
async def delete_session_annotation(
    session_id: str,
    mark_id: str,
    dt_video_controller: str | None = Cookie(default=None, alias="dt_video_controller"),
) -> dict[str, bool]:
    store = RemoteControlStore(_db_path())
    session = _controller_session(store, session_id, dt_video_controller, required=True)
    material = _session_material(store, session)
    timed_store = _timed_media_store_for(store, store.workspace_for_device(session.device_id))
    try:
        with timed_store.lock(str(material["material_id"])):
            material = timed_store.get(str(material["material_id"]))
            delete_mark(material, mark_id)
            timed_store.save(material)
    except service.TimedMediaError as exc:
        raise _http_error(exc) from exc
    return {"deleted": True}


__all__ = ["router"]
