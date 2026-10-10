"""CLI tests for ``deeptutor memory show`` / ``deeptutor memory clear``.

The real :class:`~deeptutor.services.memory.store.MemoryStore` is exercised;
only path resolution is redirected to ``tmp_path`` via
``monkeypatch`` on ``deeptutor.services.memory.paths.memory_root``, so both
the command module and the store read/write the same isolated tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from deeptutor.services.memory import L3_SLOTS, SURFACES
from deeptutor_cli.main import app

runner = CliRunner()


@pytest.fixture()
def mem_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the per-user memory root to a temp directory."""
    monkeypatch.setattr("deeptutor.services.memory.paths.memory_root", lambda: tmp_path)
    return tmp_path


def _write_doc(root: Path, layer: str, key: str, text: str) -> Path:
    doc = root / layer / f"{key}.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(text, encoding="utf-8")
    return doc


def _write_trace(root: Path, surface: str, name: str = "2026-10-10.jsonl") -> Path:
    trace = root / "trace" / surface / name
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text('{"event": "x"}\n', encoding="utf-8")
    return trace


# ── memory show ───────────────────────────────────────────────────────────


def test_show_l3_concatenates_populated_slots(mem_root: Path) -> None:
    _write_doc(mem_root, "L3", "profile", "User prefers dark mode.")
    _write_doc(mem_root, "L3", "preferences", "Keep answers concise.")

    result = runner.invoke(app, ["memory", "show", "L3"])

    assert result.exit_code == 0
    assert "L3 (concatenated)" in result.output
    assert "User prefers dark mode." in result.output
    assert "Keep answers concise." in result.output


def test_show_l3_empty_tree_prints_no_memory_hint(mem_root: Path) -> None:
    result = runner.invoke(app, ["memory", "show", "L3"])

    assert result.exit_code == 0
    assert "(No memory available" in result.output


def test_show_l2_lists_every_surface_with_empty_markers(mem_root: Path) -> None:
    _write_doc(mem_root, "L2", "chat", "Discussed KB alpha.")

    result = runner.invoke(app, ["memory", "show", "L2"])

    assert result.exit_code == 0
    assert "Discussed KB alpha." in result.output
    for surface in SURFACES:
        if surface == "chat":
            continue
        assert f"L2/{surface}.md: (empty)" in result.output


def test_show_single_l3_slot_by_name(mem_root: Path) -> None:
    _write_doc(mem_root, "L3", "profile", "User prefers dark mode.")

    result = runner.invoke(app, ["memory", "show", "profile"])

    assert result.exit_code == 0
    assert "L3/profile.md" in result.output
    assert "User prefers dark mode." in result.output


def test_show_single_l3_slot_without_file_prints_empty(mem_root: Path) -> None:
    result = runner.invoke(app, ["memory", "show", "scope"])

    assert result.exit_code == 0
    assert "L3/scope.md: (empty)" in result.output


def test_show_single_l2_surface_by_name(mem_root: Path) -> None:
    _write_doc(mem_root, "L2", "book", "Book beta summary.")

    result = runner.invoke(app, ["memory", "show", "book"])

    assert result.exit_code == 0
    assert "L2/book.md" in result.output
    assert "Book beta summary." in result.output


def test_show_unknown_doc_exits_1(mem_root: Path) -> None:
    result = runner.invoke(app, ["memory", "show", "bogus"])

    assert result.exit_code == 1
    assert "Unknown doc: bogus" in result.output


# ── memory clear ──────────────────────────────────────────────────────────


def _seed_full_tree(root: Path) -> list[Path]:
    files = [
        _write_doc(root, "L3", "profile", "User prefers dark mode."),
        _write_doc(root, "L2", "chat", "Discussed KB alpha."),
        _write_trace(root, "chat"),
        _write_trace(root, "book"),
        root / "notes.json",
    ]
    files[-1].write_text("{}", encoding="utf-8")
    return files


def test_clear_all_without_force_declined_aborts(mem_root: Path) -> None:
    seeded = _seed_full_tree(mem_root)

    result = runner.invoke(app, ["memory", "clear"], input="n\n")

    assert result.exit_code == 1
    for path in seeded:
        assert path.exists()


def test_clear_all_confirmed_removes_memory_files(mem_root: Path) -> None:
    seeded = _seed_full_tree(mem_root)

    result = runner.invoke(app, ["memory", "clear"], input="y\n")

    assert result.exit_code == 0
    assert "Cleared all memory." in result.output
    for path in seeded:
        assert not path.exists()


def test_clear_all_force_skips_prompt_and_keeps_other_dirs(mem_root: Path) -> None:
    seeded = _seed_full_tree(mem_root)
    backup = mem_root / "backup" / "20261010" / "keep.txt"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text("archived", encoding="utf-8")

    # "n" would abort if a confirm prompt were shown — proves --force skips it.
    result = runner.invoke(app, ["memory", "clear", "all", "--force"], input="n\n")

    assert result.exit_code == 0
    assert "Cleared all memory." in result.output
    for path in seeded:
        assert not path.exists()
    assert backup.exists()


def test_clear_trace_removes_all_surfaces_and_keeps_documents(
    mem_root: Path,
) -> None:
    l3_doc = _write_doc(mem_root, "L3", "profile", "User prefers dark mode.")
    l2_doc = _write_doc(mem_root, "L2", "chat", "Discussed KB alpha.")
    traces = [_write_trace(root=mem_root, surface=s) for s in SURFACES]

    result = runner.invoke(app, ["memory", "clear", "trace", "--force"])

    assert result.exit_code == 0
    assert "Cleared all L1 trace." in result.output
    for trace in traces:
        assert not trace.exists()
    assert l3_doc.exists()
    assert l2_doc.exists()


def test_clear_surface_removes_only_that_surface_trace(mem_root: Path) -> None:
    chat_trace = _write_trace(mem_root, "chat")
    book_trace = _write_trace(mem_root, "book")

    result = runner.invoke(app, ["memory", "clear", "chat", "--force"])

    assert result.exit_code == 0
    assert "Cleared L1 trace for chat." in result.output
    assert not chat_trace.exists()
    assert book_trace.exists()


def test_clear_surface_confirmed_removes_trace(mem_root: Path) -> None:
    chat_trace = _write_trace(mem_root, "chat")

    result = runner.invoke(app, ["memory", "clear", "chat"], input="y\n")

    assert result.exit_code == 0
    assert "Cleared L1 trace for chat." in result.output
    assert not chat_trace.exists()


def test_clear_unknown_target_exits_1_without_deleting(mem_root: Path) -> None:
    chat_trace = _write_trace(mem_root, "chat")

    result = runner.invoke(app, ["memory", "clear", "bogus", "--force"])

    assert result.exit_code == 1
    assert "Unknown target: bogus" in result.output
    assert chat_trace.exists()


# Sanity: the constants the command validates against did not drift.
def test_surfaces_and_slots_nonempty() -> None:
    assert SURFACES and L3_SLOTS
