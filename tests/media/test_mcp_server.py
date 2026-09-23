from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.media import access, store
from deeptutor.media.access import MediaAccessStore
from deeptutor.media.mcp_server import MediaTokenVerifier, create_media_mcp_server


@pytest.mark.asyncio
async def test_mcp_pat_is_scoped_revocable_and_marks_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(access.user_paths, "SYSTEM_ROOT", tmp_path / "system")
    monkeypatch.setattr(store.user_paths, "SYSTEM_ROOT", tmp_path / "system")
    public, raw = MediaAccessStore().issue_token(
        owner_id="local-admin",
        name="Codex",
        scopes=["media:read", "playlist:read", "playlist:write"],
    )

    verified = await MediaTokenVerifier().verify_token(raw)
    assert verified is not None
    assert verified.subject == "local-admin"
    assert set(verified.scopes) == {"media:read", "playlist:read", "playlist:write"}

    tools = {tool.name: tool for tool in await create_media_mcp_server().list_tools()}
    assert (
        tools["search_media"].annotations and tools["search_media"].annotations.readOnlyHint is True
    )
    assert (
        tools["create_playlist"].annotations
        and tools["create_playlist"].annotations.readOnlyHint is False
    )
    assert (
        tools["remove_playlist_items"].annotations
        and tools["remove_playlist_items"].annotations.destructiveHint is True
    )

    assert MediaAccessStore().revoke_token("local-admin", str(public["token_id"]))
    assert await MediaTokenVerifier().verify_token(raw) is None


@pytest.mark.asyncio
async def test_mcp_and_mobile_tokens_cannot_cross_authenticate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(access.user_paths, "SYSTEM_ROOT", tmp_path / "system")
    credentials = MediaAccessStore()
    mcp_public, mcp_raw = credentials.issue_token(
        owner_id="local-admin", name="MCP", scopes=["media:read"], kind="mcp"
    )
    mobile_public, mobile_raw = credentials.issue_token(
        owner_id="local-admin", name="Phone", scopes=["media:read"], kind="mobile"
    )

    assert await MediaTokenVerifier().verify_token(mcp_raw) is not None
    assert await MediaTokenVerifier().verify_token(mobile_raw) is None
    assert credentials.verify(mcp_raw, allowed_kinds={"mobile"}) is None
    assert credentials.verify(mobile_raw, allowed_kinds={"mcp"}) is None

    assert credentials.revoke_token("local-admin", str(mobile_public["token_id"]))
    assert credentials.verify(mobile_raw, allowed_kinds={"mobile"}) is None
    assert credentials.revoke_token("local-admin", str(mcp_public["token_id"]))
    assert await MediaTokenVerifier().verify_token(mcp_raw) is None
