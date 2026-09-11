"""LinguaWave media API.

The router owns HTTP translation only.  REST, MCP and CLI call the same
``MediaService`` so validation, import preview semantics, idempotency and
playlist mutations cannot drift between transports.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from deeptutor.api.routers.media_auth import require_media_auth, require_scope
from deeptutor.media.access import MEDIA_SCOPES, MediaAccessStore
from deeptutor.media.auth import MediaRequestPrincipal
from deeptutor.media.models import (
    ImportApplyRequest,
    ImportPreviewRequest,
    PlaybackProgress,
    PlaylistCreate,
    PlaylistItemsCreate,
    PlaylistOrder,
    PlaylistUpdate,
    SourceMappingRequest,
    SubscriptionRequest,
    SyncEnvelope,
    TokenCreate,
)
from deeptutor.media.service import MediaService
from deeptutor.media.store import (
    ImportPreviewNotFound,
    MediaNotFound,
    MediaStoreError,
    PlaylistNotFound,
    new_id,
)
from deeptutor.multi_user.audit import log_usage
from deeptutor.multi_user.context import get_current_user

router = APIRouter()
public_router = APIRouter()


class LocalItemRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    creator: str = Field(default="", max_length=300)
    source_url: str = Field(default="", max_length=2_048)
    canonical_id: str = Field(default="", max_length=512)
    duration_seconds: float = Field(default=0, ge=0)
    language: str = Field(default="", max_length=32)


class FeedResolveRequest(BaseModel):
    source_url: str = Field(min_length=1, max_length=2_048)
    title: str = Field(default="", max_length=300)
    language: str = Field(default="", max_length=32)


class PairingSessionRequest(BaseModel):
    device_name: str = Field(default="LinguaWave", max_length=80)


class PairingConfirmRequest(BaseModel):
    pairing_code: str = Field(min_length=16, max_length=128)


class PairingExchangeRequest(PairingConfirmRequest):
    pass


def _service() -> MediaService:
    return MediaService()


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, (MediaNotFound, PlaylistNotFound, ImportPreviewNotFound)):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, MediaStoreError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="Media request could not complete.")


def _require(principal: MediaRequestPrincipal, scope: str) -> None:
    require_scope(principal, scope)


def _session_only(principal: MediaRequestPrincipal) -> None:
    if not principal.is_session:
        raise HTTPException(status_code=403, detail="This action requires a DeepTutor web session.")


def _audit(action: str, resource_id: str) -> None:
    log_usage("media", resource_id, action)


@router.get("/bootstrap")
async def media_bootstrap(
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "media:read")
    return _service().bootstrap()


@router.get("/home")
async def media_home(
    content_filter: str = Query(default="all", alias="filter"),
    offline: bool = Query(default=False),
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "media:read")
    try:
        return {"sections": _service().home(content_filter=content_filter, offline=offline)}
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/discover")
async def media_discover(
    category: str = Query(default="recommended"),
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "media:read")
    try:
        return {"shelves": _service().discover(category=category)}
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/search")
async def media_search(
    q: str = Query(min_length=1, max_length=300),
    limit: int = Query(default=30, ge=1, le=100),
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "media:read")
    return {"items": _service().search(q, limit=limit)}


@router.get("/library")
async def media_library(
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "media:read")
    return _service().library()


@router.post("/local-items", status_code=status.HTTP_201_CREATED)
async def create_local_media_item(
    payload: LocalItemRequest,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "playlist:write")
    try:
        item = _service().add_local_item(payload.model_dump())
        _audit("local_item_created", item.item_id)
        return {"item": item}
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/feeds/resolve")
async def resolve_podcast_feed(
    payload: FeedResolveRequest,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "media:read")
    try:
        return _service().resolve_feed(**payload.model_dump())
    except Exception as exc:
        raise _error(exc) from exc


@router.put("/subscriptions/{feed_id}")
async def subscribe_podcast(
    feed_id: str,
    payload: SubscriptionRequest,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "subscription:write")
    try:
        result = _service().store.upsert_subscription(feed_id, **payload.model_dump())
        _audit("podcast_subscribed", feed_id)
        return result
    except Exception as exc:
        raise _error(exc) from exc


@router.delete("/subscriptions/{feed_id}")
async def unsubscribe_podcast(
    feed_id: str,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, str]:
    _require(principal, "subscription:write")
    _service().store.remove_subscription(feed_id)
    _audit("podcast_unsubscribed", feed_id)
    return {"status": "deleted"}


@router.get("/playlists")
async def list_playlists(
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "playlist:read")
    return {"playlists": _service().store.list_playlists()}


@router.post("/playlists", status_code=status.HTTP_201_CREATED)
async def create_playlist(
    payload: PlaylistCreate,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "playlist:write")
    try:
        playlist = _service().create_playlist(payload.model_dump(mode="json"))
        _audit("playlist_created", str(playlist["playlist_id"]))
        return playlist
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/playlists/{playlist_id}")
async def get_playlist(
    playlist_id: str,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "playlist:read")
    try:
        return _service().playlist_detail(playlist_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.patch("/playlists/{playlist_id}")
async def update_playlist(
    playlist_id: str,
    payload: PlaylistUpdate,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "playlist:write")
    try:
        result = _service().update_playlist(
            playlist_id, payload.model_dump(exclude_unset=True, mode="json")
        )
        _audit("playlist_updated", playlist_id)
        return result
    except Exception as exc:
        raise _error(exc) from exc


@router.delete("/playlists/{playlist_id}")
async def delete_playlist(
    playlist_id: str,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, str]:
    _require(principal, "playlist:write")
    try:
        _service().store.delete_playlist(playlist_id)
        _audit("playlist_deleted", playlist_id)
        return {"status": "deleted"}
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/playlists/{playlist_id}/items")
async def add_playlist_items(
    playlist_id: str,
    payload: PlaylistItemsCreate,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "playlist:write")
    try:
        items = _service().add_playlist_items(
            playlist_id, payload.canonical_ids, added_from=payload.added_from, note=payload.note
        )
        _audit("playlist_items_added", playlist_id)
        return {"items": items}
    except Exception as exc:
        raise _error(exc) from exc


@router.delete("/playlists/{playlist_id}/items/{item_id}")
async def remove_playlist_item(
    playlist_id: str,
    item_id: str,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, str]:
    _require(principal, "playlist:write")
    try:
        if not _service().store.remove_playlist_item(playlist_id, item_id):
            raise MediaNotFound("Playlist item was not found.")
        _audit("playlist_item_removed", item_id)
        return {"status": "deleted"}
    except Exception as exc:
        raise _error(exc) from exc


@router.put("/playlists/{playlist_id}/order")
async def reorder_playlist_items(
    playlist_id: str,
    payload: PlaylistOrder,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "playlist:write")
    try:
        return {"items": _service().store.reorder_playlist_items(playlist_id, payload.item_ids)}
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/imports/preview")
async def preview_media_import(
    payload: ImportPreviewRequest,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "import:write")
    try:
        return _service().preview_import(
            payload.raw_inputs(),
            target_playlist_id=payload.target_playlist_id,
            playlist_name=payload.playlist_name,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/imports")
async def apply_media_import(
    payload: ImportApplyRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=256),
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "import:write")
    try:
        service = _service()
        result = service.apply_import(
            preview_token=payload.preview_token,
            selected_candidate_ids=payload.selected_candidate_ids,
            target_playlist_id=payload.target_playlist_id,
            playlist_name=payload.playlist_name,
            idempotency_key=idempotency_key,
        )
        if result.is_background:
            background_tasks.add_task(
                service.run_import_job,
                str(result.payload["job_id"]),
                target_playlist_id=payload.target_playlist_id,
                playlist_name=payload.playlist_name,
            )
            return result.payload
        _audit("media_import_applied", str(result.payload.get("playlist_id") or ""))
        return result.payload
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/imports/{job_id}")
async def get_import_job(
    job_id: str,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "import:write")
    try:
        return _service().store.get_import_job(job_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/recordings/{mbid}/resolve")
async def resolve_recording(
    mbid: str,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "media:read")
    try:
        return _service().resolve_recording(mbid)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/recordings/{mbid}/sources")
async def list_recording_sources(
    mbid: str,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "media:read")
    if not mbid:
        raise HTTPException(status_code=400, detail="MusicBrainz Recording MBID is required.")
    return {"sources": _service().store.list_source_mappings(f"mbid:recording:{mbid.lower()}")}


@router.put("/recordings/{mbid}/preferred-source")
async def set_preferred_source(
    mbid: str,
    payload: SourceMappingRequest,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "playlist:write")
    try:
        return _service().store.put_source_mapping(
            f"mbid:recording:{mbid.lower()}",
            provider=payload.provider,
            source_id=payload.source_id,
            source_url=payload.source_url,
            confirmed=payload.confirmed,
            preferred=True,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.delete("/recordings/{mbid}/preferred-source")
async def delete_preferred_source(
    mbid: str,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, str]:
    _require(principal, "playlist:write")
    _service().store.delete_preferred_source(f"mbid:recording:{mbid.lower()}")
    return {"status": "deleted"}


@router.post("/items/{item_id}/playback")
async def save_playback_progress(
    item_id: str,
    payload: PlaybackProgress,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "media:read")
    try:
        item = _service().store.set_playback(
            item_id,
            position_seconds=payload.position_seconds,
            duration_seconds=payload.duration_seconds,
            completed=payload.completed,
        )
        return {"item": item}
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/items/{item_id}/playback")
async def get_playback_descriptor(
    item_id: str,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "media:read")
    try:
        return {"playback": _service().playback(item_id)}
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/items/{item_id}/timed-text")
async def get_timed_text(
    item_id: str,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "media:read")
    try:
        return _service().store.get_timed_text(item_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/items/{item_id}/transcription-jobs", status_code=status.HTTP_202_ACCEPTED)
async def request_transcription(
    item_id: str,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "playlist:write")
    try:
        _service().store.get_media(item_id)
        return {
            "job_id": new_id("transcription"),
            "item_id": item_id,
            "status": "queued",
            "provider": "server_asr",
        }
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/items/{item_id}/segments/{segment_id}/learning")
async def save_learning_artifact(
    item_id: str,
    segment_id: str,
    payload: dict[str, Any],
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "playlist:write")
    try:
        return _service().store.create_learning_artifact(
            item_id,
            segment_id,
            completed=bool(payload.get("completed")),
            note=str(payload.get("note") or "")[:2_000],
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/sync/push")
async def push_sync_mutations(
    payload: SyncEnvelope,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "playlist:write")
    try:
        return {
            "cursor": _service().store.push_mutations(
                [mutation.model_dump() for mutation in payload.mutations]
            )
        }
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/sync/pull")
async def pull_sync_mutations(
    cursor: str = Query(default=""),
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _require(principal, "media:read")
    try:
        return _service().store.pull_mutations(cursor)
    except Exception as exc:
        raise _error(exc) from exc


# Web-only management of MCP PATs and independent phone pairing credentials.
@router.post("/tokens", status_code=status.HTTP_201_CREATED)
async def create_media_token(
    payload: TokenCreate,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _session_only(principal)
    try:
        public, token = MediaAccessStore().issue_token(
            owner_id=get_current_user().id, name=payload.name, scopes=payload.scopes, kind="mcp"
        )
        return {"token": token, "access_token": public}
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/tokens")
async def list_media_tokens(
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, Any]:
    _session_only(principal)
    return {
        "tokens": MediaAccessStore().list_tokens(get_current_user().id, kind="mcp"),
        "available_scopes": sorted(MEDIA_SCOPES),
    }


@router.delete("/tokens/{token_id}")
async def revoke_media_token(
    token_id: str,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, str]:
    _session_only(principal)
    return {
        "status": "revoked"
        if MediaAccessStore().revoke_token(get_current_user().id, token_id)
        else "missing"
    }


@public_router.post("/pairing/sessions", status_code=status.HTTP_201_CREATED)
async def create_pairing_session(payload: PairingSessionRequest) -> dict[str, str]:
    return MediaAccessStore().create_pairing_session(device_name=payload.device_name)


@router.post("/pairing/sessions/{pairing_id}/confirm")
async def confirm_pairing_session(
    pairing_id: str,
    payload: PairingConfirmRequest,
    principal: MediaRequestPrincipal = Depends(require_media_auth),
) -> dict[str, str]:
    _session_only(principal)
    try:
        return MediaAccessStore().confirm_pairing(
            pairing_id, payload.pairing_code, owner_id=get_current_user().id
        )
    except Exception as exc:
        raise _error(exc) from exc


@public_router.post("/pairing/sessions/{pairing_id}/exchange")
async def exchange_pairing_session(
    pairing_id: str, payload: PairingExchangeRequest
) -> dict[str, Any]:
    try:
        public, token = MediaAccessStore().exchange_pairing(pairing_id, payload.pairing_code)
        return {"mobile_token": token, "access_token": public}
    except Exception as exc:
        raise _error(exc) from exc
