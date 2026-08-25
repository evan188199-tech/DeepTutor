"""HTTP bridge for Invidious player remote control and iPhone notes."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_auth
from deeptutor.multi_user.context import get_current_user
from deeptutor.services.path_service import PathService, get_path_service
from deeptutor.video_learning import notebook_notes
from deeptutor.video_learning.store import (
    VideoLearningConflict,
    VideoLearningNotFound,
    VideoLearningStore,
    default_db_path,
)

logger = logging.getLogger(__name__)
router = APIRouter()
_auth = [Depends(require_auth)]


def _session_db_path() -> Path:
    return default_db_path(path_service=get_path_service())


def _device_db_path() -> Path:
    return default_db_path(path_service=PathService.get_instance())


def _store_for_session() -> VideoLearningStore:
    if _session_db_path() != _device_db_path():
        raise HTTPException(
            501,
            "Video learning remote control is not available for this account yet: "
            "pairing and device sync would resolve different workspaces.",
        )
    return VideoLearningStore(_session_db_path())


def _owner_id() -> str:
    return get_current_user().id


def _auth_device(
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    if not authorization or not authorization.startswith("VideoLearning "):
        raise HTTPException(401, "Missing or malformed Authorization header.")
    raw = authorization[len("VideoLearning ") :]
    if ":" not in raw:
        raise HTTPException(401, "Invalid Authorization format.")
    device_id, token = raw.split(":", 1)
    store = VideoLearningStore.open_existing(_device_db_path())
    if store is None:
        raise HTTPException(403, "Invalid device credentials.")
    device = store.verify_token(device_id, token)
    if device is None:
        raise HTTPException(403, "Invalid device credentials.")
    store.touch_device(device_id)
    return device, store


def _validate_origin(value: str) -> str:
    raw = (value or "").strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, "instance_origin must be an absolute http(s) origin.")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise HTTPException(400, "instance_origin must not include a path or query.")
    return f"{parsed.scheme}://{parsed.netloc}"


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, VideoLearningNotFound):
        return HTTPException(404, str(exc))
    if isinstance(exc, VideoLearningConflict):
        return HTTPException(409, str(exc))
    return HTTPException(400, str(exc))


class ClaimPairingRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=12)
    device_name: str = Field("iPad", max_length=128)
    device_kind: str = Field("ipad", max_length=32)


class PlayerSyncRequest(BaseModel):
    session_id: str | None = Field(None, max_length=64)
    instance_origin: str = Field(..., max_length=256)
    video_id: str = Field(..., min_length=1, max_length=64)
    title: str = Field("", max_length=512)
    position_ms: int = Field(0, ge=0)
    duration_ms: int = Field(0, ge=0)
    playback_state: str = Field("unknown", max_length=32)
    playback_rate: float = Field(1.0, gt=0, le=4)


class CommandRequest(BaseModel):
    command_id: str | None = Field(None, max_length=64)
    type: str = Field(..., max_length=16)
    position_ms: int | None = Field(None, ge=0)
    delta_ms: int | None = None


class CommandAckRequest(BaseModel):
    ok: bool = True
    error: str | None = Field(None, max_length=512)


class NoteCreateRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=8000)
    position_ms: int | None = Field(None, ge=0)
    title: str = Field("", max_length=512)
    source: str = Field("invidious", max_length=64)
    instance_origin: str = Field("", max_length=256)
    video_id: str | None = Field(None, max_length=64)
    session_id: str | None = Field(None, max_length=64)
    notebook_id: str | None = Field(None, max_length=64)
    capture: bool = False


class NoteUpdateRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=8000)


async def _await_command_ack(
    store: VideoLearningStore,
    *,
    owner_id: str,
    session_id: str,
    command_id: str,
    timeout_s: float = 5.0,
):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        command = store.get_command(command_id, owner_id)
        if command is None:
            raise VideoLearningNotFound("Command not found.")
        if command.session_id != session_id:
            raise VideoLearningNotFound("Command not found.")
        if command.status in {"acked", "failed", "expired"}:
            return command
        await asyncio.sleep(0.25)
    raise VideoLearningConflict("Timed out waiting for iPad acknowledgement.")


async def _refresh_session_after_pause(
    store: VideoLearningStore,
    *,
    session_id: str,
    owner_id: str,
    previous_updated_at: str,
    timeout_s: float = 2.0,
):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        session = store.get_session(session_id, owner_id)
        if session is None:
            return None
        if session.playback_state == "paused" or session.updated_at != previous_updated_at:
            return session
        await asyncio.sleep(0.2)
    return store.get_session(session_id, owner_id)


async def _capture_session_timestamp(
    store: VideoLearningStore,
    *,
    session_id: str,
    owner_id: str,
) -> dict[str, Any]:
    session = store.get_session(session_id, owner_id)
    if session is None:
        raise VideoLearningNotFound("Session not found.")
    if not store.session_is_online(session):
        raise VideoLearningConflict(
            "iPad session is offline; cannot capture the current timestamp."
        )
    previous_updated_at = session.updated_at
    command = store.enqueue_command(session=session, command_type="pause")
    acked = await _await_command_ack(
        store,
        owner_id=owner_id,
        session_id=session_id,
        command_id=command.command_id,
    )
    if acked.status != "acked":
        raise VideoLearningConflict(acked.error or f"Pause command {acked.status}.")
    refreshed = await _refresh_session_after_pause(
        store,
        session_id=session_id,
        owner_id=owner_id,
        previous_updated_at=previous_updated_at,
    )
    if refreshed is None:
        raise VideoLearningNotFound("Session not found.")
    return {
        "session_id": refreshed.session_id,
        "video_id": refreshed.video_id,
        "title": refreshed.title,
        "instance_origin": refreshed.instance_origin,
        "position_ms": int(refreshed.position_ms),
        "duration_ms": int(refreshed.duration_ms),
        "playback_state": refreshed.playback_state,
        "online": store.session_is_online(refreshed),
    }


def _serialize_note(note: dict[str, Any]) -> dict[str, Any]:
    return {
        "notebook_id": note["notebook_id"],
        "record_id": note["record_id"],
        "video_id": note.get("video_id") or "",
        "title": note.get("title") or "",
        "position_ms": int(note.get("position_ms") or 0),
        "body": note.get("body") or "",
        "source": note.get("source") or "invidious",
        "instance_origin": note.get("instance_origin") or "",
        "source_url": note.get("source_url") or "",
        "created_at": note.get("created_at"),
        "updated_at": note.get("updated_at"),
    }


@router.post("/pairings")
async def create_pairing() -> dict[str, Any]:
    """Create a short-lived pairing code for an Invidious player tab."""
    store = VideoLearningStore(_device_db_path())
    pairing = store.create_pairing()
    return {
        "pairing_id": pairing.pairing_id,
        "code": pairing.code,
        "claim_secret": pairing.claim_secret,
        "expires_at": pairing.expires_at,
    }


@router.get("/pairings/{pairing_id}/status")
async def pairing_status(
    pairing_id: str,
    claim_secret: str,
) -> dict[str, Any]:
    store = VideoLearningStore.open_existing(_device_db_path())
    if store is None:
        raise HTTPException(404, "Pairing not found.")
    try:
        return store.pairing_status(pairing_id, claim_secret)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc


@router.post("/pairings/claim", dependencies=_auth)
async def claim_pairing(body: ClaimPairingRequest) -> dict[str, Any]:
    store = _store_for_session()
    try:
        pairing, device, _token = store.claim_pairing(
            code=body.code,
            owner_id=_owner_id(),
            device_name=body.device_name,
            device_kind=body.device_kind,
        )
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc
    return {
        "pairing_id": pairing.pairing_id,
        "device_id": device.device_id,
        "device_name": device.device_name,
        "device_kind": device.device_kind,
        "owner_id": device.owner_id,
        "status": "claimed",
    }


@router.get("/devices", dependencies=_auth)
async def list_devices() -> list[dict[str, Any]]:
    store = _store_for_session()
    return [
        {
            "device_id": d.device_id,
            "device_name": d.device_name,
            "device_kind": d.device_kind,
            "paired_at": d.paired_at,
            "last_seen": d.last_seen,
            "active": d.active,
        }
        for d in store.list_devices(_owner_id())
    ]


@router.delete("/devices/{device_id}", dependencies=_auth)
async def revoke_device(device_id: str) -> dict[str, str]:
    store = _store_for_session()
    if not store.revoke_device(_owner_id(), device_id):
        raise HTTPException(404, "Device not found.")
    return {"status": "revoked", "device_id": device_id}


@router.post("/player/sync")
async def player_sync(
    body: PlayerSyncRequest,
    auth=Depends(_auth_device),
) -> dict[str, Any]:
    device, store = auth
    origin = _validate_origin(body.instance_origin)
    session = store.upsert_session(
        device=device,
        session_id=body.session_id,
        instance_origin=origin,
        video_id=body.video_id.strip(),
        title=body.title,
        position_ms=body.position_ms,
        duration_ms=body.duration_ms,
        playback_state=body.playback_state,
        playback_rate=body.playback_rate,
    )
    commands = store.pending_commands(device.device_id, session.session_id)
    return {
        "session": {
            "session_id": session.session_id,
            "video_id": session.video_id,
            "title": session.title,
            "position_ms": session.position_ms,
            "duration_ms": session.duration_ms,
            "playback_state": session.playback_state,
            "playback_rate": session.playback_rate,
            "updated_at": session.updated_at,
            "online": True,
        },
        "commands": [
            {
                "command_id": c.command_id,
                "type": c.command_type,
                "payload": c.payload,
                "created_at": c.created_at,
            }
            for c in commands
        ],
    }


@router.post("/player/commands/{command_id}/ack")
async def ack_player_command(
    command_id: str,
    body: CommandAckRequest,
    auth=Depends(_auth_device),
) -> dict[str, Any]:
    device, store = auth
    try:
        command = store.ack_command(
            device_id=device.device_id,
            command_id=command_id,
            ok=body.ok,
            error=body.error,
        )
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc
    return {
        "command_id": command.command_id,
        "status": command.status,
        "acked_at": command.acked_at,
        "error": command.error,
    }


@router.get("/sessions", dependencies=_auth)
async def list_sessions() -> dict[str, Any]:
    store = _store_for_session()
    return {"sessions": store.list_sessions(_owner_id())}


@router.post("/sessions/{session_id}/commands", dependencies=_auth)
async def create_session_command(session_id: str, body: CommandRequest) -> dict[str, Any]:
    store = _store_for_session()
    session = store.get_session(session_id, _owner_id())
    if session is None:
        raise HTTPException(404, "Session not found.")
    payload: dict[str, Any] = {}
    command_type = body.type
    if command_type == "seek":
        if body.position_ms is not None:
            payload["position_ms"] = body.position_ms
        elif body.delta_ms is not None:
            payload["position_ms"] = max(0, session.position_ms + int(body.delta_ms))
        else:
            raise HTTPException(400, "seek requires position_ms or delta_ms.")
        command_type = "seek"
    try:
        command = store.enqueue_command(
            session=session,
            command_type=command_type,
            payload=payload,
            command_id=body.command_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc
    return {
        "command_id": command.command_id,
        "type": command.command_type,
        "payload": command.payload,
        "status": command.status,
        "created_at": command.created_at,
    }


@router.get("/sessions/{session_id}/commands/{command_id}", dependencies=_auth)
async def get_session_command(session_id: str, command_id: str) -> dict[str, Any]:
    store = _store_for_session()
    command = store.get_command(command_id, _owner_id())
    if command is None or command.session_id != session_id:
        raise HTTPException(404, "Command not found.")
    return {
        "command_id": command.command_id,
        "type": command.command_type,
        "payload": command.payload,
        "status": command.status,
        "created_at": command.created_at,
        "acked_at": command.acked_at,
        "error": command.error,
    }


@router.post("/sessions/{session_id}/capture-timestamp", dependencies=_auth)
async def capture_timestamp(session_id: str) -> dict[str, Any]:
    """Pause the iPad player and return the authoritative timestamp."""
    store = _store_for_session()
    try:
        return await _capture_session_timestamp(
            store,
            session_id=session_id,
            owner_id=_owner_id(),
        )
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc


@router.get("/videos/{video_id}/notes", dependencies=_auth)
async def list_video_notes(
    video_id: str,
    notebook_id: str | None = None,
) -> dict[str, Any]:
    notes = notebook_notes.list_video_notes(video_id, notebook_id=notebook_id)
    return {"notes": [_serialize_note(note) for note in notes]}


@router.post("/videos/{video_id}/notes", dependencies=_auth, status_code=201)
async def create_video_note(video_id: str, body: NoteCreateRequest) -> dict[str, Any]:
    store = _store_for_session()
    position_ms = body.position_ms
    title = body.title
    instance_origin = body.instance_origin
    needs_capture = body.capture or (body.session_id and position_ms is None)

    if needs_capture:
        if not body.session_id:
            raise HTTPException(400, "session_id is required to capture the current timestamp.")
        try:
            captured = await _capture_session_timestamp(
                store,
                session_id=body.session_id,
                owner_id=_owner_id(),
            )
        except Exception as exc:  # noqa: BLE001
            raise _http_error(exc) from exc
        if captured["video_id"] != video_id:
            raise HTTPException(409, "session video_id mismatch.")
        position_ms = int(captured["position_ms"])
        title = title or str(captured.get("title") or "")
        instance_origin = instance_origin or str(captured.get("instance_origin") or "")
    elif body.session_id:
        session = store.get_session(body.session_id, _owner_id())
        if session is None:
            raise HTTPException(404, "Session not found.")
        if session.video_id != video_id:
            raise HTTPException(409, "session video_id mismatch.")
        title = title or session.title
        instance_origin = instance_origin or session.instance_origin

    if position_ms is None:
        raise HTTPException(
            400,
            "position_ms is required when no live capture is requested.",
        )

    try:
        note = notebook_notes.create_video_note(
            video_id=video_id,
            position_ms=int(position_ms),
            body=body.body,
            title=title,
            instance_origin=instance_origin,
            source=body.source,
            notebook_id=body.notebook_id,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _serialize_note(note)


@router.patch("/notes/{notebook_id}/{record_id}", dependencies=_auth)
async def update_note(
    notebook_id: str,
    record_id: str,
    body: NoteUpdateRequest,
) -> dict[str, Any]:
    try:
        note = notebook_notes.update_video_note(notebook_id, record_id, body.body)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _serialize_note(note)


@router.delete("/notes/{notebook_id}/{record_id}", dependencies=_auth)
async def delete_note(notebook_id: str, record_id: str) -> dict[str, bool]:
    if not notebook_notes.delete_video_note(notebook_id, record_id):
        raise HTTPException(404, "Note not found.")
    return {"deleted": True}
