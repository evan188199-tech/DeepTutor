"""Bundled persona presets: seeding/validation, fallback chain, fault tolerance,
and the partner-config seam (soul cloning) with the upper layers mocked."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.services.persona.service import (
    PERSONA_FILE,
    PRESETS_DIR,
    PersonaService,
    load_visible_for_context,
)

try:
    from fastapi import HTTPException

    from deeptutor.api.routers.partners import (
        SoulSpec,
        _load_persona_markdown,
        _resolve_soul_content,
    )
    from deeptutor.services.partners.workspace import DEFAULT_SOUL
except Exception:  # pragma: no cover
    HTTPException = None
    SoulSpec = None
    _load_persona_markdown = None
    _resolve_soul_content = None
    DEFAULT_SOUL = None

pytestmark = pytest.mark.skipif(
    HTTPException is None or SoulSpec is None,
    reason="fastapi / partners router not importable",
)

VALID_PRESET_NAMES = ("peer", "teacher", "research-assistant")


def _write_persona(root: Path, name: str, frontmatter: str, body: str) -> None:
    persona_dir = root / name
    persona_dir.mkdir(parents=True, exist_ok=True)
    text = f"---\n{frontmatter}\n---\n\n{body}\n" if frontmatter else f"{body}\n"
    (persona_dir / PERSONA_FILE).write_text(text, encoding="utf-8")


# ── 1. bundled preset loading & validation ──────────────────────────────


def test_bundled_presets_are_consistent() -> None:
    """Every shipped preset has a valid slug, self-consistent frontmatter and a body."""
    assert PRESETS_DIR.is_dir()
    names = {d.name for d in PRESETS_DIR.iterdir() if d.is_dir()}
    assert names == set(VALID_PRESET_NAMES)
    for name in sorted(names):
        text = (PRESETS_DIR / name / PERSONA_FILE).read_text(encoding="utf-8")
        service = PersonaService(root=Path("/nonexistent"))
        meta, body = service._parse_frontmatter(text)
        assert meta.get("name") == name, name
        assert str(meta.get("description") or "").strip(), name
        assert body.strip(), name


def test_seed_presets_write_valid_frontmatter(tmp_path: Path) -> None:
    service = PersonaService(root=tmp_path / "personas")
    seeded = service.seed_presets()
    assert set(seeded) == set(VALID_PRESET_NAMES)
    for name in seeded:
        detail = service.get_detail(name)
        assert detail.description
        rendered = service.load_for_context(name)
        assert "## Active Persona" in rendered
        assert f"### Persona: {name}" in rendered
        assert "Embody the persona below" in rendered


def test_seed_presets_skips_invalid_dir_names(tmp_path: Path, monkeypatch) -> None:
    fake = tmp_path / "presets"
    _write_persona(fake, "ok-preset", "name: ok-preset\ndescription: Fine", "Body.")
    _write_persona(fake, "Bad_Name", "name: Bad_Name\ndescription: x", "Body.")
    (fake / "stray-file.txt").write_text("not a persona dir", encoding="utf-8")
    monkeypatch.setattr("deeptutor.services.persona.service.PRESETS_DIR", fake)
    service = PersonaService(root=tmp_path / "personas")
    assert service.seed_presets() == ["ok-preset"]
    assert {p.name for p in service.list_personas()} == {"ok-preset"}


def test_seed_presets_skips_preset_without_persona_file(tmp_path: Path, monkeypatch) -> None:
    fake = tmp_path / "presets"
    (fake / "empty-preset").mkdir(parents=True)
    _write_persona(fake, "good", "name: good\ndescription: Has file", "Body.")
    monkeypatch.setattr("deeptutor.services.persona.service.PRESETS_DIR", fake)
    service = PersonaService(root=tmp_path / "personas")
    assert service.seed_presets() == ["good"]


def test_seed_presets_skips_unreadable_persona_file(tmp_path: Path, monkeypatch) -> None:
    fake = tmp_path / "presets"
    broken = fake / "broken"
    broken.mkdir(parents=True)
    (broken / PERSONA_FILE).mkdir()  # read_text() raises IsADirectoryError
    _write_persona(fake, "good", "name: good\ndescription: Has file", "Body.")
    monkeypatch.setattr("deeptutor.services.persona.service.PRESETS_DIR", fake)
    service = PersonaService(root=tmp_path / "personas")
    assert service.seed_presets() == ["good"]


def test_seed_presets_missing_presets_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.services.persona.service.PRESETS_DIR",
        tmp_path / "does-not-exist",
    )
    service = PersonaService(root=tmp_path / "personas")
    assert service.seed_presets() == []


# ── 2. default fallback chain ───────────────────────────────────────────


def test_load_visible_empty_workspace_body_falls_through_to_admin(
    tmp_path: Path,
) -> None:
    """A workspace persona with an empty body must not shadow the admin preset."""
    workspace = PersonaService(root=tmp_path / "workspace" / "personas")
    admin = PersonaService(root=tmp_path / "admin" / "personas")
    _write_persona(workspace.root, "teacher", "name: teacher\ndescription: Stale", "")
    admin.seed_presets()

    rendered = load_visible_for_context("teacher", workspace=workspace, admin=admin)
    assert "Teacher Mode" in rendered


def test_load_visible_chain_exhausted_returns_empty(tmp_path: Path) -> None:
    workspace = PersonaService(root=tmp_path / "workspace" / "personas")
    admin = PersonaService(root=tmp_path / "admin" / "personas")
    _write_persona(workspace.root, "teacher", "name: teacher\ndescription: Stale", "")
    assert load_visible_for_context("teacher", workspace=workspace, admin=admin) == ""
    assert load_visible_for_context("", workspace=workspace, admin=admin) == ""


def test_load_for_context_invalid_name_is_empty(tmp_path: Path) -> None:
    service = PersonaService(root=tmp_path / "personas")
    service.seed_presets()
    assert service.load_for_context("Not A Valid Name") == ""
    assert service.load_for_context("../escape") == ""


def test_load_visible_default_admin_resolution(tmp_path: Path, monkeypatch) -> None:
    """admin=None resolves the admin overlay through the admin path service."""
    ws_root = tmp_path / "workspace" / "personas"
    admin_root = tmp_path / "admin"
    admin = PersonaService(root=admin_root / "personas")
    admin.seed_presets()
    monkeypatch.setattr(
        "deeptutor.services.persona.service.get_persona_service",
        lambda: PersonaService(root=ws_root),
    )
    monkeypatch.setattr(
        "deeptutor.multi_user.paths.get_admin_path_service",
        lambda: SimpleNamespace(get_workspace_dir=lambda: admin_root),
    )
    rendered = load_visible_for_context("peer")
    assert "Peer Mode" in rendered


# ── 3. invalid persona-file fault tolerance ─────────────────────────────


def test_broken_yaml_frontmatter_degrades_gracefully(tmp_path: Path) -> None:
    root = tmp_path / "personas"
    (root / "wonky").mkdir(parents=True)
    (root / "wonky" / PERSONA_FILE).write_text(
        "---\nname: [unclosed\ndescription: :broken:\n---\n\nStill readable body.\n",
        encoding="utf-8",
    )
    service = PersonaService(root=root)
    infos = service.list_personas()
    assert [i.name for i in infos] == ["wonky"]
    assert infos[0].description == ""
    assert service.get_detail("wonky").description == ""
    rendered = service.load_for_context("wonky")
    assert "Still readable body." in rendered


def test_non_dict_frontmatter_treated_as_empty(tmp_path: Path) -> None:
    root = tmp_path / "personas"
    (root / "listy").mkdir(parents=True)
    (root / "listy" / PERSONA_FILE).write_text(
        "---\n- just\n- a\n- list\n---\n\nBody after list frontmatter.\n",
        encoding="utf-8",
    )
    service = PersonaService(root=root)
    detail = service.get_detail("listy")
    assert detail.description == ""
    assert "Body after list frontmatter." in detail.content


def test_persona_without_frontmatter_keeps_full_body(tmp_path: Path) -> None:
    root = tmp_path / "personas"
    (root / "plain").mkdir(parents=True)
    (root / "plain" / PERSONA_FILE).write_text(
        "# Just markdown\n\nNo frontmatter here.\n", encoding="utf-8"
    )
    service = PersonaService(root=root)
    detail = service.get_detail("plain")
    assert detail.description == ""
    assert "# Just markdown" in detail.content
    assert "# Just markdown" in service.load_for_context("plain")


def test_list_personas_skips_broken_entries(tmp_path: Path) -> None:
    root = tmp_path / "personas"
    _write_persona(root, "good", "name: good\ndescription: Fine", "Body.")
    (root / "no-file").mkdir(parents=True)
    (root / "unreadable").mkdir()
    (root / "unreadable" / PERSONA_FILE).mkdir()
    (root / "a-plain-file.txt").write_text("not a dir", encoding="utf-8")
    service = PersonaService(root=root)
    assert [p.name for p in service.list_personas()] == ["good"]


def test_load_for_context_frontmatter_only_is_empty(tmp_path: Path) -> None:
    root = tmp_path / "personas"
    _write_persona(root, "empty-body", "name: empty-body\ndescription: D", "")
    service = PersonaService(root=root)
    assert service.load_for_context("empty-body") == ""


# ── 4. partner-config seam (upper layers mocked) ────────────────────────


def _install_persona_layers(
    monkeypatch, ws_root: Path, admin_root: Path
) -> tuple[PersonaService, PersonaService]:
    ws = PersonaService(root=ws_root)
    admin = PersonaService(root=admin_root / "personas")
    monkeypatch.setattr("deeptutor.services.persona.get_persona_service", lambda: ws)
    monkeypatch.setattr(
        "deeptutor.multi_user.paths.get_admin_path_service",
        lambda: SimpleNamespace(get_workspace_dir=lambda: admin_root),
    )
    return ws, admin


def test_load_persona_markdown_prefers_workspace(tmp_path: Path, monkeypatch) -> None:
    ws, admin = _install_persona_layers(monkeypatch, tmp_path / "ws", tmp_path / "admin-root")
    ws.create("teacher", "Ws", "Workspace voice.")
    admin.seed_presets()
    body = _load_persona_markdown("teacher")
    assert "Workspace voice." in body
    assert "name: teacher" not in body


def test_load_persona_markdown_falls_back_to_admin(tmp_path: Path, monkeypatch) -> None:
    _install_persona_layers(monkeypatch, tmp_path / "ws", tmp_path / "admin-root")
    admin = PersonaService(root=tmp_path / "admin-root" / "personas")
    admin.seed_presets()
    body = _load_persona_markdown("teacher")
    assert "Teacher Mode" in body
    assert "name: teacher" not in body  # frontmatter stripped for SOUL.md cloning


def test_load_persona_markdown_missing_returns_empty(tmp_path: Path, monkeypatch) -> None:
    _install_persona_layers(monkeypatch, tmp_path / "ws", tmp_path / "admin-root")
    assert _load_persona_markdown("ghost") == ""


def test_resolve_soul_content_persona_source(tmp_path: Path, monkeypatch) -> None:
    ws, _ = _install_persona_layers(monkeypatch, tmp_path / "ws", tmp_path / "admin-root")
    ws.create("teacher", "Ws", "Workspace voice.")
    content, origin = _resolve_soul_content(SoulSpec(source="persona", id="teacher"))
    assert "Workspace voice." in content
    assert "name: teacher" not in content
    assert origin == {"type": "persona", "id": "teacher"}


def test_resolve_soul_content_persona_missing_raises_404(tmp_path: Path, monkeypatch) -> None:
    _install_persona_layers(monkeypatch, tmp_path / "ws", tmp_path / "admin-root")
    with pytest.raises(HTTPException) as exc:
        _resolve_soul_content(SoulSpec(source="persona", id="ghost"))
    assert exc.value.status_code == 404


def test_resolve_soul_content_persona_blank_id_raises_422(tmp_path: Path, monkeypatch) -> None:
    _install_persona_layers(monkeypatch, tmp_path / "ws", tmp_path / "admin-root")
    with pytest.raises(HTTPException) as exc:
        _resolve_soul_content(SoulSpec(source="persona", id="  "))
    assert exc.value.status_code == 422


def test_resolve_soul_content_default_sources() -> None:
    content, origin = _resolve_soul_content(None)
    assert content == DEFAULT_SOUL
    assert origin == {"type": "default", "id": ""}
    content, origin = _resolve_soul_content(SoulSpec(source="default"))
    assert content == DEFAULT_SOUL


def test_resolve_soul_content_custom_blank_raises_422() -> None:
    with pytest.raises(HTTPException) as exc:
        _resolve_soul_content(SoulSpec(source="custom", content="   "))
    assert exc.value.status_code == 422


def test_resolve_soul_content_library_sources(monkeypatch) -> None:
    manager = SimpleNamespace(
        get_soul=lambda soul_id: {"content": "# Library soul"} if soul_id == "math-tutor" else None
    )
    monkeypatch.setattr(
        "deeptutor.api.routers.partners.get_partner_manager",
        lambda: manager,
    )
    content, origin = _resolve_soul_content(SoulSpec(source="library", id="math-tutor"))
    assert content == "# Library soul"
    assert origin == {"type": "library", "id": "math-tutor"}
    with pytest.raises(HTTPException) as exc:
        _resolve_soul_content(SoulSpec(source="library", id="nope"))
    assert exc.value.status_code == 404
