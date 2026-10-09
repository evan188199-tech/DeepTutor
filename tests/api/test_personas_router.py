"""Personas API: which read-only presets a workspace-scoped read sees (#1534)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import HTTPException
import pytest

from deeptutor.api.routers import personas as router
from deeptutor.services.persona import PersonaService


def _seed_presets(root: Path) -> PersonaService:
    service = PersonaService(root=root)
    service.create("socratic", "Asks questions", "Answer with a question.")
    return service


def _route_roots(monkeypatch: pytest.MonkeyPatch, *, presets: Path, active: Path) -> None:
    monkeypatch.setattr(router, "_admin_persona_service", lambda: PersonaService(root=presets))
    monkeypatch.setattr(router, "get_persona_service", lambda: PersonaService(root=active))


def test_admin_inside_a_workspace_still_sees_the_account_presets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reporter's picker: the admin's own workspaces offered no persona.

    Presets live in the account-level workspace, so any read rooted elsewhere —
    including the admin's, once each workspace got its own personas directory —
    has to merge them. Gating that on the role made an admin inside a workspace
    the only user who saw fewer presets than the account holds (#1534).
    """
    presets, workspace = tmp_path / "account" / "personas", tmp_path / "ws-1" / "personas"
    _seed_presets(presets)
    _route_roots(monkeypatch, presets=presets, active=workspace)

    listed = asyncio.run(router.list_personas())["personas"]
    assert [(p["name"], p["source"], p["read_only"]) for p in listed] == [
        ("socratic", "admin", True)
    ]
    assert asyncio.run(router.get_persona("socratic"))["read_only"] is True


def test_reading_the_preset_directory_itself_lists_each_persona_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unchanged behaviour for the account-level read: no self-merge, editable."""
    presets = tmp_path / "account" / "personas"
    _seed_presets(presets)
    _route_roots(monkeypatch, presets=presets, active=presets)

    listed = asyncio.run(router.list_personas())["personas"]
    assert [(p["name"], p["source"]) for p in listed] == [("socratic", "user")]


def test_get_persona_falls_back_to_admin_preset_with_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The workspace miss on the preset fallback path must leave a trace."""
    presets, workspace = tmp_path / "account" / "personas", tmp_path / "ws-1" / "personas"
    _seed_presets(presets)
    _route_roots(monkeypatch, presets=presets, active=workspace)

    with caplog.at_level(logging.WARNING, logger=router.logger.name):
        detail = asyncio.run(router.get_persona("socratic"))

    assert detail["read_only"] is True
    assert "socratic" in caplog.text
    assert "falling back to admin presets" in caplog.text
    assert str(workspace) in caplog.text


def test_get_persona_missing_everywhere_warns_before_404(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    presets, workspace = tmp_path / "account" / "personas", tmp_path / "ws-1" / "personas"
    presets.mkdir(parents=True)
    workspace.mkdir(parents=True)
    _route_roots(monkeypatch, presets=presets, active=workspace)

    with caplog.at_level(logging.WARNING, logger=router.logger.name):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(router.get_persona("ghost"))

    assert exc_info.value.status_code == 404
    assert "ghost" in caplog.text
    assert "returning 404" in caplog.text
    assert str(presets) in caplog.text
