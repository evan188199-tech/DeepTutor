"""Builtin skill registry ↔ shipped tree consistency.

The registry side is ``deeptutor/services/skill`` — ``BUILTIN_SKILLS_ROOT``
(service.py), the ``SkillService`` builtin layer, and hub.py's frontmatter
reader / preflight gate. The directory side is the shipped
``deeptutor/skills/builtin/`` tree. The two are checked in both directions:
every directory entry must be visible through the service, and every builtin
the service knows must exist on disk with a complete ``SKILL.md``. Missing,
extra, or duplicate names fail with an explicit diff.

Unlike the synthetic-fixture tests in ``tests/services/skill/`` (layer
merging, taxonomy, plugin loading), these tests pin the real shipped tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.skill.hub import preflight_skill_dir, read_skill_metadata
import deeptutor.services.skill.service as _skill_service_module
from deeptutor.services.skill.service import (
    BUILTIN_SKILLS_ROOT,
    SkillNotFoundError,
    SkillReadOnlyError,
    SkillService,
)

# The builtin skill set shipped with the product. Every name here must exist
# in the tree and be resolvable through SkillService (acceptance: full
# coverage of the five builtin skills).
SHIPPED_BUILTIN_SKILLS = frozenset({"docx", "pdf", "pptx", "skill-creator", "xlsx"})

# Frontmatter keys the runtime understands in ``requires`` (service.py
# ``_availability``); anything else would be silently ignored.
_KNOWN_REQUIRES_KEYS = frozenset({"bins", "env", "sandbox"})

_NAME_RE = _skill_service_module._NAME_RE


def _directory_entries() -> list[Path]:
    """Direct child directories of the shipped builtin tree."""
    assert BUILTIN_SKILLS_ROOT.is_dir(), (
        f"BUILTIN_SKILLS_ROOT does not exist: {BUILTIN_SKILLS_ROOT}"
    )
    return sorted(p for p in BUILTIN_SKILLS_ROOT.iterdir() if p.is_dir())


def _frontmatter(skill_dir: Path) -> dict:
    """Parsed SKILL.md frontmatter via the registry's own parser."""
    meta, _body = SkillService._parse_frontmatter(
        (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    )
    return meta


@pytest.fixture
def service(tmp_path: Path) -> SkillService:
    """Isolated user layer over the real builtin root (nothing shadows)."""
    return SkillService(root=tmp_path / "skills")


# ── registry root ────────────────────────────────────────────────────────


def test_registry_root_points_at_shipped_package_tree() -> None:
    """BUILTIN_SKILLS_ROOT must resolve inside the installed deeptutor package."""
    assert BUILTIN_SKILLS_ROOT.name == "builtin"
    assert BUILTIN_SKILLS_ROOT.parent.name == "skills"
    assert BUILTIN_SKILLS_ROOT.parent.parent.name == "deeptutor"
    assert BUILTIN_SKILLS_ROOT.is_dir()


def test_builtin_directories_use_registry_naming_rule() -> None:
    """A directory violating the name rule is invisible to the service.

    ``SkillService`` skips entries whose name fails ``_NAME_RE`` — an
    inconsistently named directory would ship but never surface, so it must
    fail here instead.
    """
    bad = [p.name for p in _directory_entries() if not _NAME_RE.match(p.name)]
    assert bad == [], f"builtin directories violating the registry name rule: {bad}"


# ── bidirectional name check ─────────────────────────────────────────────


def test_directory_and_service_listing_agree(service: SkillService) -> None:
    """Registry ↔ directory: no missing and no extra names, either way."""
    dir_names = {p.name for p in _directory_entries()}
    service_builtins = {info.name for info in service.list_skills() if info.source == "builtin"}
    missing_in_service = sorted(dir_names - service_builtins)
    extra_in_service = sorted(service_builtins - dir_names)
    assert missing_in_service == [], (
        f"builtin directories the service does not expose: {missing_in_service}"
    )
    assert extra_in_service == [], (
        f"builtin skills the service exposes without a directory: {extra_in_service}"
    )


def test_no_duplicate_builtin_names(service: SkillService) -> None:
    """Duplicate names (after case folding) would make resolution ambiguous."""
    names = [p.name for p in _directory_entries()]
    lowered = [n.lower() for n in names]
    duplicates = sorted({n for n in lowered if lowered.count(n) > 1})
    assert duplicates == [], f"duplicate builtin skill names: {duplicates}"
    listed = [info.name for info in service.list_skills() if info.source == "builtin"]
    assert len(listed) == len(set(listed)), (
        f"service lists duplicate builtin names: {sorted(listed)}"
    )


def test_five_shipped_skills_are_all_covered() -> None:
    """The five skills shipped with the product are all present on disk."""
    dir_names = {p.name for p in _directory_entries()}
    absent = sorted(SHIPPED_BUILTIN_SKILLS - dir_names)
    assert absent == [], f"shipped builtin skills missing from the tree: {absent}"


# ── entry file + metadata completeness ───────────────────────────────────


def test_every_builtin_has_entry_file_with_valid_frontmatter() -> None:
    """Each directory carries a non-empty SKILL.md with complete metadata."""
    for skill_dir in _directory_entries():
        entry = skill_dir / "SKILL.md"
        assert entry.is_file(), f"builtin skill has no SKILL.md entry file: {skill_dir.name}"
        text = entry.read_text(encoding="utf-8")
        assert text.strip(), f"builtin SKILL.md is empty: {skill_dir.name}"

        meta = read_skill_metadata(skill_dir)
        assert isinstance(meta, dict) and meta, (
            f"builtin SKILL.md has no parsable frontmatter: {skill_dir.name}"
        )
        name = str(meta.get("name") or "").strip()
        assert name == skill_dir.name, (
            f"frontmatter name `{name}` does not match directory `{skill_dir.name}`"
        )
        description = str(meta.get("description") or "").strip()
        assert description, f"builtin skill has no description: {skill_dir.name}"


def test_builtin_metadata_tags_and_requires_are_wellformed() -> None:
    """``tags``/``requires`` values must be shaped as the runtime reads them."""
    for skill_dir in _directory_entries():
        meta = _frontmatter(skill_dir)

        tags = meta.get("tags")
        if tags is not None:
            assert isinstance(tags, list) and all(isinstance(t, str) and t.strip() for t in tags), (
                f"malformed tags in builtin skill: {skill_dir.name}: {tags!r}"
            )

        requires = meta.get("requires")
        if requires is not None:
            assert isinstance(requires, dict), (
                f"requires must be a mapping in builtin skill: {skill_dir.name}"
            )
            unknown = sorted(set(requires) - _KNOWN_REQUIRES_KEYS)
            assert unknown == [], (
                f"unknown requires keys in builtin skill {skill_dir.name}: {unknown}"
            )
            for key in ("bins", "env"):
                value = requires.get(key)
                if value is not None:
                    assert isinstance(value, list) and all(
                        isinstance(item, str) and item.strip() for item in value
                    ), f"malformed requires.{key} in builtin skill: {skill_dir.name}"
            sandbox = requires.get("sandbox")
            if sandbox is not None:
                assert isinstance(sandbox, (bool, str)) and (sandbox is not True or sandbox), (
                    f"malformed requires.sandbox in builtin skill: {skill_dir.name}"
                )


def test_builtin_directories_carry_no_entry_files_outside_the_package() -> None:
    """A builtin package is its directory: no stray files at the tree root."""
    strays = [p.name for p in BUILTIN_SKILLS_ROOT.iterdir() if not p.is_dir()]
    assert strays == [], f"stray files inside deeptutor/skills/builtin: {strays}"


# ── service behaviour over the real tree ─────────────────────────────────


def test_service_resolves_every_builtin(service: SkillService) -> None:
    """Every directory entry resolves to detail with builtin provenance."""
    for skill_dir in _directory_entries():
        detail = service.get_detail(skill_dir.name)
        assert detail.source == "builtin", f"unexpected source: {detail.name}"
        assert detail.name == skill_dir.name
        assert detail.content.strip(), f"builtin detail content is empty: {detail.name}"
        assert detail.description.strip(), f"builtin detail description is empty: {detail.name}"


def test_service_read_only_enforcement_covers_every_builtin(service: SkillService) -> None:
    """Writes must be refused for every builtin, not just the first one."""
    for skill_dir in _directory_entries():
        with pytest.raises(SkillReadOnlyError):
            service.update(skill_dir.name, description="hijack")
        with pytest.raises(SkillReadOnlyError):
            service.delete(skill_dir.name)


def test_unknown_builtin_name_raises() -> None:
    """A name absent from the tree must raise, not fall through."""
    with pytest.raises(SkillNotFoundError):
        SkillService(root=Path("/nonexistent-user-skills")).get_detail("not-a-builtin-skill")


def test_summary_manifest_lists_each_builtin_once(service: SkillService) -> None:
    """Manifest rows carry each builtin exactly once with its description."""
    rows = [entry for entry in service.summary_entries() if entry.name in SHIPPED_BUILTIN_SKILLS]
    names = [entry.name for entry in rows]
    assert sorted(names) == sorted(SHIPPED_BUILTIN_SKILLS), (
        f"manifest rows do not cover the shipped set exactly: {sorted(names)}"
    )
    for entry in rows:
        assert entry.description.strip(), f"manifest description empty: {entry.name}"


# ── hub.py gates over the real tree ──────────────────────────────────────


def test_hub_preflight_accepts_every_builtin() -> None:
    """Each builtin passes the hub's structural preflight with no errors."""
    for skill_dir in _directory_entries():
        preflight = preflight_skill_dir(skill_dir)
        assert preflight.errors == [], (
            f"hub preflight rejects builtin skill {skill_dir.name}: {preflight.errors}"
        )


def test_hub_metadata_reader_agrees_with_service_parser() -> None:
    """hub.py and service.py parse the same frontmatter consistently."""
    for skill_dir in _directory_entries():
        via_hub = read_skill_metadata(skill_dir)
        via_service = _frontmatter(skill_dir)
        assert via_hub == via_service, (
            f"frontmatter parsers disagree for builtin skill: {skill_dir.name}"
        )
