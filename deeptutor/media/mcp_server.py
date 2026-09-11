"""Streamable HTTP MCP surface for LinguaWave automation.

The server uses scoped DeepTutor-issued PATs.  It never accepts a browser JWT
and every tool re-enters the owning user's workspace before invoking the same
``MediaService`` used by REST.  Tool annotations deliberately distinguish
read-only lookup from writes so Codex can request approval for mutations.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from deeptutor.multi_user.context import user_from_token_payload
from deeptutor.multi_user.identity import get_user_by_id
from deeptutor.multi_user.models import CurrentUser
from deeptutor.multi_user.paths import local_admin_user, user_context

from .access import MediaAccessStore
from .models import PlaylistKind
from .service import MediaService

T = TypeVar("T")


class MediaTokenVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        principal = MediaAccessStore().verify(token, allowed_kinds={"mcp"})
        if principal is None:
            return None
        return AccessToken(
            token=token,
            client_id=principal.token_id,
            scopes=sorted(principal.scopes),
            subject=principal.owner_id,
            claims={"iss": "LinguaWave"},
        )


def _user_for_owner(owner_id: str) -> CurrentUser:
    if owner_id == local_admin_user().id:
        return local_admin_user()
    record = get_user_by_id(owner_id)
    if record is None:
        raise PermissionError("The owner of this media token no longer exists.")
    username, values = record
    return user_from_token_payload(
        type(
            "TokenPayload",
            (),
            {"username": username, "role": str(values.get("role") or "user"), "user_id": owner_id},
        )()
    )


def _with_service(required_scope: str, action: Callable[[MediaService], T]) -> T:
    token = get_access_token()
    if token is None or not token.subject:
        raise PermissionError("LinguaWave MCP token is missing.")
    if required_scope not in token.scopes:
        raise PermissionError(f"Media token lacks required scope: {required_scope}")
    with user_context(_user_for_owner(token.subject)):
        return action(MediaService())


_read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
_write = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
)
_delete = ToolAnnotations(
    readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False
)


def create_media_mcp_server() -> FastMCP:
    server = FastMCP(
        "LinguaWave Media",
        instructions=(
            "Search, organize and import the user's LinguaWave music and podcasts. "
            "Preview imports before applying them. Write tools require the user's configured approval policy."
        ),
        token_verifier=MediaTokenVerifier(),
        auth=AuthSettings(
            issuer_url="https://linguawave.invalid",
            resource_server_url="https://linguawave.invalid/mcp/media",
        ),
        # The parent FastAPI service may be deployed behind a user-selected
        # reverse-proxy hostname.  FastMCP's localhost preset would reject all
        # of those Host headers; this bearer-only endpoint has no ambient
        # browser credential, so the proxy remains the correct host boundary.
        host="0.0.0.0",
        streamable_http_path="/media",
        json_response=True,
        stateless_http=True,
    )

    @server.tool(
        description="Search the user's library and cached public catalog.", annotations=_read
    )
    def search_media(query: str, limit: int = 20) -> dict[str, Any]:
        return _with_service(
            "media:read",
            lambda service: {"items": service.search(query, limit=max(1, min(limit, 100)))},
        )

    @server.tool(
        description="Resolve a MusicBrainz Recording MBID without changing the user's library.",
        annotations=_read,
    )
    def resolve_media(recording_mbid: str) -> dict[str, Any]:
        return _with_service(
            "media:read", lambda service: service.resolve_recording(recording_mbid, persist=False)
        )

    @server.tool(
        description="List manual, imported, smart and system playlists.", annotations=_read
    )
    def list_playlists() -> dict[str, Any]:
        return _with_service(
            "playlist:read", lambda service: {"playlists": service.store.list_playlists()}
        )

    @server.tool(description="Get a playlist and its resolved items.", annotations=_read)
    def get_playlist(playlist_id: str) -> dict[str, Any]:
        return _with_service("playlist:read", lambda service: service.playlist_detail(playlist_id))

    @server.tool(description="Create a manual or rule-backed smart playlist.", annotations=_write)
    def create_playlist(
        name: str, description: str = "", smart_rule: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        def action(service: MediaService) -> dict[str, Any]:
            kind = PlaylistKind.SMART.value if smart_rule is not None else PlaylistKind.MANUAL.value
            return service.create_playlist(
                {"name": name, "description": description, "kind": kind, "rule": smart_rule or {}}
            )

        return _with_service("playlist:write", action)

    @server.tool(
        description="Parse an import and return matches, duplicates and failures without adding anything.",
        annotations=_write,
    )
    def preview_playlist_import(
        sources: list[str], playlist_id: str | None = None, playlist_name: str = ""
    ) -> dict[str, Any]:
        return _with_service(
            "import:write",
            lambda service: service.preview_import(
                sources, target_playlist_id=playlist_id, playlist_name=playlist_name
            ),
        )

    @server.tool(
        description="Apply a previously reviewed import preview exactly once when given a new idempotency key.",
        annotations=_write,
    )
    def apply_playlist_import(
        preview_token: str,
        idempotency_key: str,
        selected_candidate_ids: list[str] | None = None,
        playlist_id: str | None = None,
        playlist_name: str = "",
    ) -> dict[str, Any]:
        def action(service: MediaService) -> dict[str, Any]:
            result = service.apply_import(
                preview_token=preview_token,
                selected_candidate_ids=selected_candidate_ids,
                target_playlist_id=playlist_id,
                playlist_name=playlist_name,
                idempotency_key=idempotency_key,
            )
            return result.payload

        return _with_service("import:write", action)

    @server.tool(
        description="Add existing canonical media ids to a manual playlist.", annotations=_write
    )
    def add_playlist_items(playlist_id: str, canonical_ids: list[str]) -> dict[str, Any]:
        return _with_service(
            "playlist:write",
            lambda service: {
                "items": service.add_playlist_items(playlist_id, canonical_ids, added_from="mcp")
            },
        )

    @server.tool(description="Remove one stored item from a manual playlist.", annotations=_delete)
    def remove_playlist_items(playlist_id: str, item_id: str) -> dict[str, Any]:
        return _with_service(
            "playlist:write",
            lambda service: {"removed": service.store.remove_playlist_item(playlist_id, item_id)},
        )

    @server.tool(
        description="Set the complete item ordering of a manual playlist.", annotations=_write
    )
    def reorder_playlist_items(playlist_id: str, item_ids: list[str]) -> dict[str, Any]:
        return _with_service(
            "playlist:write",
            lambda service: {"items": service.store.reorder_playlist_items(playlist_id, item_ids)},
        )

    @server.tool(
        description="Subscribe to a podcast RSS feed after it has been resolved or confirmed.",
        annotations=_write,
    )
    def subscribe_podcast(
        feed_id: str, title: str = "", source_url: str = "", language: str = ""
    ) -> dict[str, Any]:
        return _with_service(
            "subscription:write",
            lambda service: service.store.upsert_subscription(
                feed_id, title=title, source_url=source_url, language=language
            ),
        )

    @server.tool(description="Read the status of an import job.", annotations=_read)
    def get_import_job(job_id: str) -> dict[str, Any]:
        return _with_service("media:read", lambda service: service.store.get_import_job(job_id))

    return server


_media_mcp_server: FastMCP | None = None
_media_mcp_app: Any | None = None


def get_media_mcp_app() -> Any:
    global _media_mcp_server, _media_mcp_app
    if _media_mcp_app is None:
        _media_mcp_server = create_media_mcp_server()
        _media_mcp_app = _media_mcp_server.streamable_http_app()
    return _media_mcp_app


__all__ = ["MediaTokenVerifier", "create_media_mcp_server", "get_media_mcp_app"]
