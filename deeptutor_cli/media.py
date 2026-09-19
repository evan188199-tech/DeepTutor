"""Composable local commands for the LinguaWave media domain."""

from __future__ import annotations

import json
import uuid

import typer

from deeptutor.media.service import MediaService
from deeptutor.media.store import MediaStoreError

from .common import console


def _print(payload: object) -> None:
    console.print_json(json.dumps(payload, ensure_ascii=False, default=str))


def register(app: typer.Typer) -> None:
    playlist_app = typer.Typer(help="Manage LinguaWave playlists.")
    app.add_typer(playlist_app, name="playlist")

    @app.command("search")
    def search_media(
        query: str = typer.Argument(..., help="Title, artist, podcast or topic."),
        limit: int = typer.Option(20, "--limit", min=1, max=100),
    ) -> None:
        """Search the local media library and cached catalog."""
        _print({"items": MediaService().search(query, limit=limit)})

    @playlist_app.command("list")
    def list_playlists() -> None:
        """List manual, imported, smart and system playlists."""
        _print({"playlists": MediaService().store.list_playlists()})

    @playlist_app.command("create")
    def create_playlist(
        name: str = typer.Argument(..., help="Playlist name."),
        description: str = typer.Option("", "--description"),
        smart: bool = typer.Option(False, "--smart", help="Create a rule-backed smart playlist."),
        rule_json: str = typer.Option("{}", "--rule-json", help="SmartPlaylistRule JSON."),
    ) -> None:
        """Create a manual or smart playlist."""
        try:
            rule = json.loads(rule_json) if smart else None
        except json.JSONDecodeError as exc:
            console.print(f"[red]Invalid smart-playlist JSON:[/] {exc}")
            raise typer.Exit(code=2) from exc
        try:
            _print(
                MediaService().create_playlist(
                    {
                        "name": name,
                        "description": description,
                        "kind": "smart" if smart else "manual",
                        "rule": rule,
                    }
                )
            )
        except MediaStoreError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(code=1) from exc

    @app.command("import")
    def import_media(
        source: list[str] = typer.Argument(
            ..., help="URL, MusicBrainz id, RSS, OPML/M3U path contents, or title - artist."
        ),
        preview: bool = typer.Option(
            False, "--preview", help="Only parse and display the preview."
        ),
        playlist: str = typer.Option("", "--playlist", help="Existing playlist id."),
        playlist_name: str = typer.Option(
            "", "--playlist-name", help="Name when a new imported playlist is needed."
        ),
        candidate: list[str] = typer.Option([], "--candidate", help="Candidate id(s) to confirm."),
    ) -> None:
        """Preview an import, or apply a newly generated preview in one local command."""
        service = MediaService()
        try:
            result = service.preview_import(
                source, target_playlist_id=playlist or None, playlist_name=playlist_name
            )
            if preview:
                _print(result)
                return
            applied = service.apply_import(
                preview_token=str(result["preview_token"]),
                selected_candidate_ids=candidate or None,
                target_playlist_id=playlist or None,
                playlist_name=playlist_name,
                idempotency_key=f"cli-{uuid.uuid4().hex}",
            )
            _print(applied.payload)
        except MediaStoreError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(code=1) from exc
