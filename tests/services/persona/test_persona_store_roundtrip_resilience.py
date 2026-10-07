"""PersonaService store-level guarantees: save/read round trips, default
fallbacks, and tolerance of corrupted on-disk persona data."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.persona import service as persona_service_module
from deeptutor.services.persona.service import (
    PERSONA_FILE,
    InvalidPersonaNameError,
    PersonaExistsError,
    PersonaNotFoundError,
    PersonaService,
)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "personas"


@pytest.fixture
def service(root: Path) -> PersonaService:
    return PersonaService(root=root)


# ── save/read round trips ───────────────────────────────────────────────


def test_create_read_roundtrip_preserves_name_and_description(
    service: PersonaService, root: Path
) -> None:
    service.create("teacher", "Patient tutor", "Explain step by step.")

    raw = (root / "teacher" / PERSONA_FILE).read_text(encoding="utf-8")
    meta, body = PersonaService._parse_frontmatter(raw)
    assert meta["name"] == "teacher"
    assert meta["description"] == "Patient tutor"
    assert "Explain step by step." in body

    detail = service.get_detail("teacher")
    assert (detail.name, detail.description, detail.source) == ("teacher", "Patient tutor", "user")


def test_create_normalizes_slug_and_strips_description(service: PersonaService) -> None:
    info = service.create("  Teacher ", "  Padded desc  ", "body")
    assert info.name == "teacher"
    assert info.description == "Padded desc"
    # lookup by any casing of the stored slug finds the same persona
    assert service.get_detail("TEACHER").description == "Padded desc"


def test_update_content_roundtrip_rewrites_frontmatter(service: PersonaService) -> None:
    service.create("coach", "kept desc", "old body")
    service.update(
        "coach",
        content="---\nname: forged\ndescription: forged\ntriggers: [x]\n---\n\nNew body.",
    )
    detail = service.get_detail("coach")
    assert detail.description == "kept desc"
    assert "New body." in detail.content
    # the foreign frontmatter is never carried over into the stored file
    assert "forged" not in detail.content
    assert "triggers" not in detail.content


def test_full_lifecycle_roundtrip(service: PersonaService) -> None:
    info = service.create("writer", "first", "draft one")
    assert info.to_dict() == {
        "name": "writer",
        "description": "first",
        "source": "user",
        "read_only": False,
    }
    assert {p.name for p in service.list_personas()} == {"writer"}

    service.update("writer", description="导学助手 ✅")
    service.update("writer", content="final body", rename_to="author")
    detail = service.get_detail("author")
    assert detail.description == "导学助手 ✅"
    assert "final body" in detail.content
    with pytest.raises(PersonaNotFoundError):
        service.get_detail("writer")

    service.delete("author")
    assert service.list_personas() == []
    with pytest.raises(PersonaNotFoundError):
        service.get_detail("author")


def test_list_descriptions_match_detail(service: PersonaService) -> None:
    service.create("alpha", "Alpha desc", "a")
    service.create("beta", "Beta desc", "b")
    listed = {p.name: p.description for p in service.list_personas()}
    assert listed == {
        "alpha": service.get_detail("alpha").description,
        "beta": service.get_detail("beta").description,
    }


# ── default fallbacks ───────────────────────────────────────────────────


def test_list_on_missing_root_is_empty(service: PersonaService) -> None:
    assert service.list_personas() == []


def test_load_for_context_invalid_name_is_empty(service: PersonaService) -> None:
    service.create("real", "d", "body")
    assert service.load_for_context("Bad Name!") == ""
    assert service.load_for_context("../escape") == ""


def test_load_for_context_empty_body_is_empty(service: PersonaService) -> None:
    service.create("quiet", "Quiet persona", "")
    assert service.get_detail("quiet").description == "Quiet persona"
    assert service.load_for_context("quiet") == ""


def test_persona_without_frontmatter_falls_back_to_defaults(
    service: PersonaService, root: Path
) -> None:
    raw_dir = root / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / PERSONA_FILE).write_text("Just a plain body.\n", encoding="utf-8")

    detail = service.get_detail("raw")
    assert detail.description == ""
    assert "Just a plain body." in detail.content

    rendered = service.load_for_context("raw")
    assert "### Persona: raw" in rendered
    assert "Just a plain body." in rendered


def test_frontmatter_without_description_key_defaults_to_empty(
    service: PersonaService, root: Path
) -> None:
    persona_dir = root / "sparse"
    persona_dir.mkdir(parents=True)
    (persona_dir / PERSONA_FILE).write_text(
        "---\nname: sparse\n---\n\nBody only.\n", encoding="utf-8"
    )
    assert service.get_detail("sparse").description == ""
    assert "Body only." in service.load_for_context("sparse")


def test_seed_presets_missing_presets_dir_returns_empty(
    service: PersonaService, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(persona_service_module, "PRESETS_DIR", tmp_path / "does-not-exist")
    assert service.seed_presets() == []
    assert service.list_personas() == []


# ── corrupted data tolerance ────────────────────────────────────────────


def test_corrupt_yaml_frontmatter_is_tolerated(service: PersonaService, root: Path) -> None:
    persona_dir = root / "broken"
    persona_dir.mkdir(parents=True)
    (persona_dir / PERSONA_FILE).write_text(
        "---\nname: [unclosed\n---\n\nSurviving body.\n", encoding="utf-8"
    )

    assert service.get_detail("broken").description == ""
    assert "Surviving body." in service.load_for_context("broken")
    assert service.list_personas()[0].name == "broken"


def test_non_dict_frontmatter_is_tolerated(service: PersonaService, root: Path) -> None:
    persona_dir = root / "listy"
    persona_dir.mkdir(parents=True)
    (persona_dir / PERSONA_FILE).write_text(
        "---\n- alpha\n- beta\n---\n\nBody intact.\n", encoding="utf-8"
    )
    assert service.get_detail("listy").description == ""
    assert "Body intact." in service.load_for_context("listy")


def test_null_frontmatter_defaults_to_empty(service: PersonaService, root: Path) -> None:
    persona_dir = root / "nully"
    persona_dir.mkdir(parents=True)
    (persona_dir / PERSONA_FILE).write_text("---\nnull\n---\n\nBody.\n", encoding="utf-8")
    assert service.get_detail("nully").description == ""


def test_list_skips_entries_without_persona_file(service: PersonaService, root: Path) -> None:
    service.create("valid", "Valid", "v")
    (root / "hollow").mkdir()  # directory without PERSONA.md
    (root / "stray.txt").write_text("not a persona", encoding="utf-8")

    assert [p.name for p in service.list_personas()] == ["valid"]


def test_list_skips_unreadable_persona_file(service: PersonaService, root: Path) -> None:
    service.create("valid", "Valid", "v")
    broken = root / "broken"
    broken.mkdir()
    (broken / PERSONA_FILE).mkdir()  # PERSONA.md is a directory → read raises OSError

    assert [p.name for p in service.list_personas()] == ["valid"]


def test_empty_persona_file_tolerated(service: PersonaService, root: Path) -> None:
    persona_dir = root / "blank"
    persona_dir.mkdir(parents=True)
    (persona_dir / PERSONA_FILE).write_text("", encoding="utf-8")

    assert service.get_detail("blank").description == ""
    assert service.load_for_context("blank") == ""
    assert [p.name for p in service.list_personas()] == ["blank"]


def test_rename_conflicts_and_missing_delete(service: PersonaService) -> None:
    service.create("one", "d", "b")
    service.create("two", "d", "b")
    with pytest.raises(PersonaExistsError):
        service.update("one", rename_to="two")
    # failed rename leaves the original persona intact
    assert service.get_detail("one").name == "one"
    with pytest.raises(PersonaNotFoundError):
        service.delete("ghost")
    with pytest.raises(InvalidPersonaNameError):
        service.update("one", rename_to="Bad Name")
