"""Focused unit tests for the pure vault filesystem layer.

Covers path parsing/normalization, note read/write round-trips, frontmatter
handling (including malformed input), and rejection branches for invalid
paths or arguments. Complements ``test_obsidian_capability.py`` without
duplicating its cases.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.capabilities.obsidian import vault as V


def _seed(root: Path) -> None:
    (root / "notes").mkdir(parents=True, exist_ok=True)
    (root / "notes" / "Alpha.md").write_text("---\ntitle: Alpha\n---\nbody one\n", encoding="utf-8")
    (root / "Beta.md").write_text("no frontmatter here\n", encoding="utf-8")


# ---- path parsing & normalization ---------------------------------------------


def test_resolve_note_strips_heading_and_alias_suffixes(tmp_path: Path) -> None:
    _seed(tmp_path)
    assert V.resolve_note(tmp_path, "Alpha#Section") == tmp_path / "notes" / "Alpha.md"
    assert V.resolve_note(tmp_path, "Alpha|display text") == tmp_path / "notes" / "Alpha.md"
    assert V.resolve_note(tmp_path, "notes/Alpha.md#h|alias") == tmp_path / "notes" / "Alpha.md"


def test_resolve_note_bare_name_falls_back_to_case_insensitive_match(
    tmp_path: Path,
) -> None:
    (tmp_path / "My Note.md").write_text("x\n", encoding="utf-8")
    assert V.resolve_note(tmp_path, "my note") == tmp_path / "My Note.md"
    # Exact stem still wins over the case-insensitive fallback.
    (tmp_path / "Sub").mkdir()
    (tmp_path / "Sub" / "MY NOTE.md").write_text("y\n", encoding="utf-8")
    assert V.resolve_note(tmp_path, "MY NOTE") == tmp_path / "Sub" / "MY NOTE.md"


def test_resolve_note_returns_none_for_missing_or_blank_refs(tmp_path: Path) -> None:
    _seed(tmp_path)
    assert V.resolve_note(tmp_path, "notes/DoesNotExist.md") is None
    assert V.resolve_note(tmp_path, "DoesNotExist") is None
    assert V.resolve_note(tmp_path, "") is None
    assert V.resolve_note(tmp_path, "   ") is None
    assert V.resolve_note(tmp_path, "#only-a-heading") is None


def test_create_note_normalizes_relative_paths_and_md_suffix(tmp_path: Path) -> None:
    assert V.create_note(tmp_path, "./deep/dir/Page", "hello") == "deep/dir/Page.md"
    assert (tmp_path / "deep" / "dir" / "Page.md").read_text(encoding="utf-8") == "hello"
    assert V.create_note(tmp_path, "UPPER.MD", "x") == "UPPER.MD"


def test_create_note_treats_absolute_looking_input_as_vault_relative(
    tmp_path: Path,
) -> None:
    # A leading slash is stripped; the note stays inside the vault.
    assert V.create_note(tmp_path, "/etc/target.md", "x") == "etc/target.md"
    assert (tmp_path / "etc" / "target.md").is_file()


@pytest.mark.parametrize(
    "rel",
    ["../outside.md", "notes/../../outside.md", "", "   "],
)
def test_create_note_rejects_paths_outside_or_empty(tmp_path: Path, rel: str) -> None:
    with pytest.raises(V.VaultError):
        V.create_note(tmp_path, rel, "x")


# ---- frontmatter handling ------------------------------------------------------


def test_split_frontmatter_without_fence_returns_body_unchanged() -> None:
    text = "plain note\nsecond line\n"
    fm, body = V.split_frontmatter(text)
    assert fm == {} and body == text


def test_split_frontmatter_malformed_yaml_degrades_to_empty() -> None:
    text = "---\ntitle: [unclosed\n---\nbody\n"
    fm, body = V.split_frontmatter(text)
    assert fm == {} and body == text


@pytest.mark.parametrize("payload", ["- a\n- b\n", "just a scalar\n", "42\n"])
def test_split_frontmatter_non_dict_yaml_is_ignored(payload: str) -> None:
    text = f"---\n{payload}---\nbody\n"
    fm, body = V.split_frontmatter(text)
    assert fm == {} and body == text


def test_split_frontmatter_round_trip_via_set_property(tmp_path: Path) -> None:
    _seed(tmp_path)
    V.set_property(tmp_path, "Alpha", "status", "reviewed")
    V.set_property(tmp_path, "Alpha", "count", 3)
    note = V.read_note(tmp_path, "Alpha")
    assert note["frontmatter"] == {"title": "Alpha", "status": "reviewed", "count": 3}
    assert note["body"].startswith("body one")


def test_split_frontmatter_empty_fence_is_not_frontmatter() -> None:
    # An ``---\n---`` pair with no body between the fences does not parse as
    # frontmatter; the whole text is returned as body.
    text = "---\n---\nbody\n"
    fm, body = V.split_frontmatter(text)
    assert fm == {} and body == text


# ---- read/write rejection branches ----------------------------------------------


def test_read_note_missing_raises(tmp_path: Path) -> None:
    _seed(tmp_path)
    with pytest.raises(V.VaultError):
        V.read_note(tmp_path, "Ghost")


def test_append_note_missing_raises(tmp_path: Path) -> None:
    _seed(tmp_path)
    with pytest.raises(V.VaultError):
        V.append_note(tmp_path, "Ghost", "x")


def test_append_note_inserts_separator_when_file_lacks_trailing_newline(
    tmp_path: Path,
) -> None:
    (tmp_path / "Tight.md").write_text("no newline at end", encoding="utf-8")
    V.append_note(tmp_path, "Tight.md", "appended")
    text = (tmp_path / "Tight.md").read_text(encoding="utf-8")
    assert text == "no newline at end\nappended"


def test_append_note_refuses_non_utf8_note(tmp_path: Path) -> None:
    # Writes must not launder undecodable bytes back onto disk.
    (tmp_path / "legacy.md").write_bytes(b"cafe \xff ok")
    with pytest.raises(V.VaultError):
        V.append_note(tmp_path, "legacy.md", "x")


def test_set_property_rejects_empty_key_or_missing_note(tmp_path: Path) -> None:
    _seed(tmp_path)
    with pytest.raises(V.VaultError):
        V.set_property(tmp_path, "Alpha", "  ", "v")
    with pytest.raises(V.VaultError):
        V.set_property(tmp_path, "Ghost", "k", "v")


# ---- listing / search edges ------------------------------------------------------


def test_search_notes_empty_query_returns_empty_list(tmp_path: Path) -> None:
    _seed(tmp_path)
    assert V.search_notes(tmp_path, "") == []
    assert V.search_notes(tmp_path, "   ") == []


def test_list_notes_missing_folder_returns_empty(tmp_path: Path) -> None:
    _seed(tmp_path)
    assert V.list_notes(tmp_path, "no/such/folder") == []


def test_list_notes_and_search_skip_ignored_dirs(tmp_path: Path) -> None:
    for name in V.IGNORED_DIRS:
        (tmp_path / name).mkdir()
        (tmp_path / name / "Hidden.md").write_text("secret needle\n", encoding="utf-8")
    assert V.list_notes(tmp_path) == []
    assert V.search_notes(tmp_path, "needle") == []
