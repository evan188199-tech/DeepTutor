from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.tools.file_tools import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool


def _ctx(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return {"_workspace_dir": str(workspace), "_allowed_dir": str(workspace)}, workspace


@pytest.mark.asyncio
async def test_file_tools_round_trip_and_pagination(tmp_path) -> None:
    kwargs, workspace = _ctx(tmp_path)
    write = await WriteFileTool().execute(path="notes/a.txt", content="one\ntwo\nthree", **kwargs)
    assert write.success

    read = await ReadFileTool().execute(path="notes/a.txt", offset=2, limit=1, **kwargs)
    assert read.success
    assert "2| two" in read.content
    assert "use offset=3" in read.content

    listed = await ListDirTool().execute(path=".", recursive=True, **kwargs)
    assert listed.success
    assert "notes/" in listed.content
    assert "notes/a.txt" in listed.content
    assert (workspace / "notes" / "a.txt").read_text(encoding="utf-8") == "one\ntwo\nthree"


@pytest.mark.asyncio
async def test_edit_file_requires_unique_match_unless_replace_all(tmp_path) -> None:
    kwargs, workspace = _ctx(tmp_path)
    (workspace / "a.txt").write_text("x\nx\n", encoding="utf-8")

    ambiguous = await EditFileTool().execute(path="a.txt", old_text="x", new_text="y", **kwargs)
    assert not ambiguous.success
    assert "appears 2 times" in ambiguous.content

    edited = await EditFileTool().execute(
        path="a.txt",
        old_text="x",
        new_text="y",
        replace_all=True,
        **kwargs,
    )
    assert edited.success
    assert (workspace / "a.txt").read_text(encoding="utf-8") == "y\ny\n"


@pytest.mark.asyncio
async def test_file_tools_block_paths_outside_workspace(tmp_path) -> None:
    kwargs, _workspace = _ctx(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    result = await ReadFileTool().execute(path=str(outside), **kwargs)
    assert not result.success
    assert "outside the turn workspace" in result.content

    blocked_write = await WriteFileTool().execute(path=str(outside), content="x", **kwargs)
    assert not blocked_write.success
    assert "outside the turn workspace" in blocked_write.content

    blocked_edit = await EditFileTool().execute(
        path=str(outside), old_text="secret", new_text="x", **kwargs
    )
    assert not blocked_edit.success
    assert "outside the turn workspace" in blocked_edit.content

    blocked_list = await ListDirTool().execute(path=str(tmp_path), **kwargs)
    assert not blocked_list.success
    assert "outside the turn workspace" in blocked_list.content


@pytest.mark.asyncio
async def test_read_file_accepts_absolute_path_inside_workspace(tmp_path) -> None:
    kwargs, workspace = _ctx(tmp_path)
    (workspace / "a.txt").write_text("alpha\nbeta\n", encoding="utf-8")

    read = await ReadFileTool().execute(path=str(workspace / "a.txt"), **kwargs)
    assert read.success
    assert "1| alpha" in read.content
    assert "2| beta" in read.content


@pytest.mark.asyncio
async def test_read_file_reports_end_of_file_suffix(tmp_path) -> None:
    kwargs, _workspace = _ctx(tmp_path)
    write = await WriteFileTool().execute(path="doc.txt", content="l1\nl2\nl3", **kwargs)
    assert write.success
    read = await ReadFileTool().execute(path="doc.txt", **kwargs)
    assert read.success
    for marker in ("1| l1", "2| l2", "3| l3", "(end of file; 3 lines total)"):
        assert marker in read.content


@pytest.mark.asyncio
async def test_edit_file_single_match_replaces_first_occurrence(tmp_path) -> None:
    kwargs, workspace = _ctx(tmp_path)
    (workspace / "a.txt").write_text("abc\nxyz\n", encoding="utf-8")

    edited = await EditFileTool().execute(path="a.txt", old_text="b", new_text="B", **kwargs)
    assert edited.success
    assert "Successfully edited" in edited.content
    assert (workspace / "a.txt").read_text(encoding="utf-8") == "aBc\nxyz\n"


@pytest.mark.asyncio
async def test_list_dir_reports_empty_directory(tmp_path) -> None:
    kwargs, workspace = _ctx(tmp_path)
    (workspace / "sub").mkdir()

    listed = await ListDirTool().execute(path="sub", **kwargs)
    assert listed.success
    assert listed.content == "Directory sub is empty"

    (workspace / "sub" / "deep.txt").write_text("x", encoding="utf-8")
    flat = await ListDirTool().execute(path=".", **kwargs)
    assert flat.success
    assert "sub/" in flat.content
    assert "deep.txt" not in flat.content


@pytest.mark.asyncio
async def test_read_file_coerces_bad_offset_and_limit(tmp_path) -> None:
    kwargs, workspace = _ctx(tmp_path)
    (workspace / "a.txt").write_text("1\n2\n3\n4\n5\n", encoding="utf-8")

    bad = await ReadFileTool().execute(path="a.txt", offset="abc", limit="xyz", **kwargs)
    assert bad.success
    assert "(end of file; 5 lines total)" in bad.content

    zero_offset = await ReadFileTool().execute(path="a.txt", offset=0, **kwargs)
    assert zero_offset.success
    assert zero_offset.content.startswith("1| 1\n")

    zero_limit = await ReadFileTool().execute(path="a.txt", limit=0, **kwargs)
    assert zero_limit.success
    assert "1| 1" in zero_limit.content
    assert "5| 5" in zero_limit.content

    beyond = await ReadFileTool().execute(path="a.txt", offset=10, **kwargs)
    assert not beyond.success
    assert "offset 10 is beyond end of file (5 lines)" in beyond.content


@pytest.mark.asyncio
async def test_read_file_reports_empty_file(tmp_path) -> None:
    kwargs, workspace = _ctx(tmp_path)
    (workspace / "empty.txt").write_text("", encoding="utf-8")

    read = await ReadFileTool().execute(path="empty.txt", **kwargs)
    assert read.success
    assert read.content == "(empty file: empty.txt)"


@pytest.mark.asyncio
async def test_read_file_replaces_invalid_utf8(tmp_path) -> None:
    kwargs, workspace = _ctx(tmp_path)
    (workspace / "bin.txt").write_bytes(b"\xff\xfe ok \x80tail")

    read = await ReadFileTool().execute(path="bin.txt", **kwargs)
    assert read.success
    assert "\ufffd" in read.content
    assert "ok" in read.content


@pytest.mark.asyncio
async def test_read_file_caps_output_length(tmp_path) -> None:
    kwargs, workspace = _ctx(tmp_path)
    (workspace / "big.txt").write_text("\n".join("x" * 200 for _ in range(800)), encoding="utf-8")

    read = await ReadFileTool().execute(path="big.txt", **kwargs)
    assert read.success
    assert "...[truncated]" in read.content
    assert len(read.content) <= 130_000


@pytest.mark.asyncio
async def test_read_file_default_limit_paginates_large_file(tmp_path) -> None:
    kwargs, workspace = _ctx(tmp_path)
    (workspace / "wide.txt").write_text(
        "\n".join(f"line-{i:04d}" for i in range(2500)), encoding="utf-8"
    )

    read = await ReadFileTool().execute(path="wide.txt", **kwargs)
    assert read.success
    assert "1| line-0000" in read.content
    assert "2000| line-1999" in read.content
    assert "2001| line-2000" not in read.content
    assert "(showing lines 1-2000 of 2500; use offset=2001 to continue)" in read.content

    resume = await ReadFileTool().execute(path="wide.txt", offset=2001, **kwargs)
    assert resume.success
    assert "2001| line-2000" in resume.content
    assert "(end of file; 2500 lines total)" in resume.content


@pytest.mark.asyncio
async def test_list_dir_ignores_noise_and_truncates(tmp_path) -> None:
    kwargs, workspace = _ctx(tmp_path)
    for noise in ("__pycache__", ".git", ".pytest_cache"):
        (workspace / noise).mkdir()
        (workspace / noise / "ignored.txt").write_text("x", encoding="utf-8")
    (workspace / "keep.txt").write_text("x", encoding="utf-8")

    listed = await ListDirTool().execute(path=".", recursive=True, **kwargs)
    assert listed.success
    assert "keep.txt" in listed.content
    for noise in ("__pycache__", ".git", ".pytest_cache", "ignored.txt"):
        assert noise not in listed.content

    for i in range(250):
        (workspace / f"f{i:03d}.txt").write_text("x", encoding="utf-8")
    truncated = await ListDirTool().execute(path=".", max_entries="bogus", **kwargs)
    assert truncated.success
    assert "(truncated, showing first 200 of 251 entries)" in truncated.content

    minimal = await ListDirTool().execute(path=".", max_entries=1, **kwargs)
    assert minimal.success
    assert minimal.content.startswith("f000.txt")
    assert "(truncated, showing first 1 of 251 entries)" in minimal.content


@pytest.mark.asyncio
async def test_list_dir_reports_missing_and_non_directory(tmp_path) -> None:
    kwargs, workspace = _ctx(tmp_path)
    (workspace / "plain.txt").write_text("x", encoding="utf-8")

    missing = await ListDirTool().execute(path="nope", **kwargs)
    assert not missing.success
    assert "directory not found: nope" in missing.content

    not_dir = await ListDirTool().execute(path="plain.txt", **kwargs)
    assert not not_dir.success
    assert "not a directory: plain.txt" in not_dir.content


@pytest.mark.asyncio
async def test_read_file_reports_missing_and_non_file(tmp_path) -> None:
    kwargs, workspace = _ctx(tmp_path)
    (workspace / "plain.txt").write_text("x", encoding="utf-8")

    missing = await ReadFileTool().execute(path="ghost.txt", **kwargs)
    assert not missing.success
    assert "file not found: ghost.txt" in missing.content

    dir_read = await ReadFileTool().execute(path=".", **kwargs)
    assert not dir_read.success
    assert "not a file" in dir_read.content


@pytest.mark.asyncio
async def test_edit_file_reports_close_match_diff_and_plain_miss(tmp_path) -> None:
    kwargs, workspace = _ctx(tmp_path)
    (workspace / "a.txt").write_text("aaa\nbbb\nccc\n", encoding="utf-8")

    close = await EditFileTool().execute(
        path="a.txt", old_text="aaa\nbbb\nccx\n", new_text="z", **kwargs
    )
    assert not close.success
    assert "Best match" in close.content
    assert "%" in close.content
    assert "old_text" in close.content

    (workspace / "b.txt").write_text("alpha\n", encoding="utf-8")
    far = await EditFileTool().execute(path="b.txt", old_text="zzz", new_text="y", **kwargs)
    assert not far.success
    assert far.content == "Error: old_text not found. Verify the file content."


@pytest.mark.asyncio
async def test_edit_file_reports_missing_file(tmp_path) -> None:
    kwargs, _workspace = _ctx(tmp_path)

    missing = await EditFileTool().execute(path="ghost.txt", old_text="a", new_text="b", **kwargs)
    assert not missing.success
    assert "file not found: ghost.txt" in missing.content


@pytest.mark.asyncio
async def test_workspace_tools_degrade_when_context_missing() -> None:
    kwargs = {"_workspace_dir": "", "_allowed_dir": ""}

    read = await ReadFileTool().execute(path="a.txt", **kwargs)
    assert not read.success
    assert "not available for this turn" in read.content

    write = await WriteFileTool().execute(path="a.txt", content="x", **kwargs)
    assert not write.success
    assert "not available for this turn" in write.content

    edit = await EditFileTool().execute(path="a.txt", old_text="x", new_text="y", **kwargs)
    assert not edit.success
    assert "not available for this turn" in edit.content

    listed = await ListDirTool().execute(path=".", **kwargs)
    assert not listed.success
    assert "not available for this turn" in listed.content


@pytest.mark.asyncio
async def test_write_file_reports_parent_conflict(tmp_path) -> None:
    kwargs, workspace = _ctx(tmp_path)
    (workspace / "blocker.txt").write_text("x", encoding="utf-8")

    conflict = await WriteFileTool().execute(path="blocker.txt/child.txt", content="x", **kwargs)
    assert not conflict.success
    assert "Error writing file:" in conflict.content


@pytest.mark.asyncio
async def test_read_file_blocks_symlink_pointing_outside_workspace(tmp_path) -> None:
    kwargs, workspace = _ctx(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (workspace / "link.txt").symlink_to(outside)

    read = await ReadFileTool().execute(path="link.txt", **kwargs)
    assert not read.success
    assert "outside the turn workspace" in read.content

    edited = await EditFileTool().execute(
        path="link.txt", old_text="secret", new_text="x", **kwargs
    )
    assert not edited.success
    assert "outside the turn workspace" in edited.content

    listed = await ListDirTool().execute(path="link.txt", **kwargs)
    assert not listed.success
    assert "outside the turn workspace" in listed.content


def test_file_tools_expose_definitions_and_prompt_hints() -> None:
    expected = {
        ReadFileTool: ("read_file", {"path", "offset", "limit"}),
        WriteFileTool: ("write_file", {"path", "content"}),
        EditFileTool: ("edit_file", {"path", "old_text", "new_text", "replace_all"}),
        ListDirTool: ("list_dir", {"path", "recursive", "max_entries"}),
    }
    for tool_cls, (name, params) in expected.items():
        tool = tool_cls()
        definition = tool.get_definition()
        assert definition.name == name
        assert {p.name for p in definition.parameters} == params
        hints = tool.get_prompt_hints(language="en")
        assert hints.short_description == ""


@pytest.mark.asyncio
async def test_file_tools_report_unexpected_io_failures(tmp_path, monkeypatch) -> None:
    kwargs, workspace = _ctx(tmp_path)
    (workspace / "a.txt").write_text("x\n", encoding="utf-8")

    def boom(*args, **kwargs2):
        raise OSError("disk unavailable")

    monkeypatch.setattr(Path, "read_text", boom)
    read = await ReadFileTool().execute(path="a.txt", **kwargs)
    assert not read.success
    assert "Error reading file: disk unavailable" in read.content

    edit = await EditFileTool().execute(path="a.txt", old_text="x", new_text="y", **kwargs)
    assert not edit.success
    assert "Error editing file: disk unavailable" in edit.content

    monkeypatch.setattr(Path, "write_text", boom)
    write = await WriteFileTool().execute(path="b.txt", content="x", **kwargs)
    assert not write.success
    assert "Error writing file: disk unavailable" in write.content

    monkeypatch.setattr(Path, "read_text", Path.read_text)
    monkeypatch.setattr(Path, "iterdir", boom)
    listed = await ListDirTool().execute(path=".", **kwargs)
    assert not listed.success
    assert "Error listing directory: disk unavailable" in listed.content
