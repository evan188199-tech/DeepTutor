"""Tests for the safe ZIP extractor (``deeptutor.utils.archive_extractor``).

These lock in the security guards that a naive ``extractall`` lacks: Zip Slip
defusal, extension whitelisting, nested-archive rejection, duplicate handling,
and the zip-bomb size/count/ratio limits.
"""

from __future__ import annotations

from pathlib import Path
import zipfile

import pytest

from deeptutor.utils.archive_extractor import (
    ArchiveTooLargeError,
    ZipExtractionLimits,
    safe_extract_zip,
)
from deeptutor.utils.document_validator import DocumentValidator

DOC_EXTS = {".txt", ".md", ".pdf", ".zip"}  # .zip is intentionally never extracted


def _make_zip(path: Path, entries: list[tuple[str, bytes]], *, deflate: bool = False) -> Path:
    mode = zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED
    with zipfile.ZipFile(path, "w", compression=mode) as zf:
        for name, data in entries:
            # A ZipInfo carries its own compress_type, so set it explicitly —
            # otherwise writestr(ZipInfo, ...) ignores the archive's mode.
            info = zipfile.ZipInfo(name)
            info.compress_type = mode
            zf.writestr(info, data)
    return path


def test_extracts_allowed_files_flat(tmp_path: Path) -> None:
    src = _make_zip(tmp_path / "a.zip", [("notes.txt", b"hello"), ("paper.md", b"# title")])
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    names = sorted(p.name for p in result.extracted)
    assert names == ["notes.txt", "paper.md"]
    assert (out / "notes.txt").read_bytes() == b"hello"
    assert result.skipped == []


def test_zip_slip_is_defused(tmp_path: Path) -> None:
    # Member names that try to escape via traversal or absolute paths.
    src = _make_zip(
        tmp_path / "evil.zip",
        [("../../escape.txt", b"x"), ("/abs/secret.txt", b"y"), ("a/b/deep.txt", b"z")],
    )
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    # Everything is flattened into the target; nothing escapes it.
    for p in result.extracted:
        assert out.resolve() in p.resolve().parents
    assert not (tmp_path / "escape.txt").exists()
    assert not Path("/abs/secret.txt").exists()
    assert sorted(p.name for p in result.extracted) == ["deep.txt", "escape.txt", "secret.txt"]


def test_disallowed_extension_is_skipped(tmp_path: Path) -> None:
    src = _make_zip(tmp_path / "a.zip", [("ok.txt", b"x"), ("malware.exe", b"x"), ("run.sh", b"x")])
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    assert [p.name for p in result.extracted] == ["ok.txt"]
    skipped_names = {member for member, _ in result.skipped}
    assert "malware.exe" in skipped_names
    assert "run.sh" in skipped_names


def test_nested_zip_is_never_extracted(tmp_path: Path) -> None:
    src = _make_zip(tmp_path / "a.zip", [("inner.zip", b"PK\x03\x04"), ("ok.txt", b"x")])
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    assert [p.name for p in result.extracted] == ["ok.txt"]
    assert any(member == "inner.zip" for member, _ in result.skipped)


def test_unbounded_parser_policy_still_rejects_nested_zip(tmp_path: Path) -> None:
    src = _make_zip(
        tmp_path / "a.zip",
        [("vendor.custom", b"payload"), ("inner.zip", b"PK\x03\x04")],
    )
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=set())

    assert [p.name for p in result.extracted] == ["vendor.custom"]
    assert any(
        member == "inner.zip" and reason == "nested archive" for member, reason in result.skipped
    )


def test_macosx_and_dotfiles_are_skipped(tmp_path: Path) -> None:
    src = _make_zip(
        tmp_path / "a.zip",
        [("__MACOSX/._notes.txt", b"junk"), (".hidden.txt", b"junk"), ("real.txt", b"ok")],
    )
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    assert [p.name for p in result.extracted] == ["real.txt"]


def test_duplicate_basenames_after_flattening(tmp_path: Path) -> None:
    src = _make_zip(tmp_path / "a.zip", [("chap1/notes.txt", b"one"), ("chap2/notes.txt", b"two")])
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    assert [p.name for p in result.extracted] == ["notes.txt"]
    assert (out / "notes.txt").read_bytes() == b"one"  # first wins
    assert any("duplicate" in reason for _, reason in result.skipped)


def test_per_entry_size_cap_raises(tmp_path: Path) -> None:
    src = _make_zip(tmp_path / "a.zip", [("big.txt", b"x" * 100)])
    out = tmp_path / "out"

    with pytest.raises(ArchiveTooLargeError):
        safe_extract_zip(
            src, out, allowed_extensions=DOC_EXTS, limits=ZipExtractionLimits(max_entry_bytes=10)
        )


def test_too_many_entries_raises(tmp_path: Path) -> None:
    src = _make_zip(tmp_path / "a.zip", [(f"f{i}.txt", b"x") for i in range(5)])
    out = tmp_path / "out"

    with pytest.raises(ArchiveTooLargeError):
        safe_extract_zip(
            src, out, allowed_extensions=DOC_EXTS, limits=ZipExtractionLimits(max_entries=3)
        )


def test_total_size_cap_raises(tmp_path: Path) -> None:
    src = _make_zip(tmp_path / "a.zip", [("a.txt", b"x" * 60), ("b.txt", b"x" * 60)])
    out = tmp_path / "out"

    with pytest.raises(ArchiveTooLargeError):
        safe_extract_zip(
            src,
            out,
            allowed_extensions=DOC_EXTS,
            limits=ZipExtractionLimits(max_total_bytes=100, max_entry_bytes=100),
        )


def test_compression_ratio_guard_raises(tmp_path: Path) -> None:
    # 50 KB of identical bytes compresses to a few hundred bytes -> very high ratio.
    src = _make_zip(tmp_path / "bomb.zip", [("a.txt", b"A" * 50_000)], deflate=True)
    out = tmp_path / "out"

    with pytest.raises(ArchiveTooLargeError):
        safe_extract_zip(
            src,
            out,
            allowed_extensions=DOC_EXTS,
            limits=ZipExtractionLimits(max_compression_ratio=10.0),
        )


def test_bad_zip_raises(tmp_path: Path) -> None:
    bogus = tmp_path / "not.zip"
    bogus.write_bytes(b"this is not a zip")
    with pytest.raises(zipfile.BadZipFile):
        safe_extract_zip(bogus, tmp_path / "out", allowed_extensions=DOC_EXTS)


# ---------------------------------------------------------------------------
# Edge-case and fault-tolerance behavior
# ---------------------------------------------------------------------------


class _PaddedStream:
    """Read wrapper whose byte stream is longer than the entry declared."""

    def __init__(self, inner, pad: bytes) -> None:
        self._inner = inner
        self._pad = pad

    def read(self, n: int = -1) -> bytes:
        data = self._inner.read(n)
        if not data and self._pad:
            pad, self._pad = self._pad, b""
            return pad
        return data

    def __enter__(self):
        self._inner.__enter__()
        return self

    def __exit__(self, *exc_info) -> bool:
        return self._inner.__exit__(*exc_info)


def test_empty_archive_yields_no_members(tmp_path: Path) -> None:
    src = tmp_path / "empty.zip"
    with zipfile.ZipFile(src, "w"):
        pass
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    assert result.extracted == []
    assert result.skipped == []
    assert out.is_dir()


def test_directory_only_archive_extracts_nothing(tmp_path: Path) -> None:
    src = tmp_path / "dirs.zip"
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr(zipfile.ZipInfo("docs/"), b"")
        zf.writestr(zipfile.ZipInfo("docs/nested/"), b"")
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    assert result.extracted == []
    assert result.skipped == []
    assert list(out.iterdir()) == []


def test_truncated_archive_raises_bad_zip(tmp_path: Path) -> None:
    valid = _make_zip(tmp_path / "full.zip", [("a.txt", b"payload")])
    truncated = tmp_path / "truncated.zip"
    data = valid.read_bytes()
    truncated.write_bytes(data[: len(data) // 2])

    with pytest.raises(zipfile.BadZipFile):
        safe_extract_zip(truncated, tmp_path / "out", allowed_extensions=DOC_EXTS)


def test_windows_style_member_names_flatten_into_target(tmp_path: Path) -> None:
    src = _make_zip(
        tmp_path / "separators.zip",
        [("a\\b\\notes.txt", b"one"), ("C:\\temp\\report.txt", b"two")],
    )
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    assert sorted(p.name for p in result.extracted) == ["notes.txt", "report.txt"]
    for p in result.extracted:
        assert out.resolve() in p.resolve().parents
    assert (out / "notes.txt").read_bytes() == b"one"


def test_member_with_control_character_name_is_skipped(tmp_path: Path) -> None:
    src = _make_zip(tmp_path / "a.zip", [("\x01\x02\x03", b"junk"), ("ok.txt", b"keep")])
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    assert [p.name for p in result.extracted] == ["ok.txt"]
    assert any(member == "\x01\x02\x03" for member, _ in result.skipped)
    assert list(out.iterdir()) == [out / "ok.txt"]


def test_nested_archive_with_uppercase_suffix_is_skipped(tmp_path: Path) -> None:
    src = _make_zip(tmp_path / "a.zip", [("INNER.ZIP", b"PK\x03\x04"), ("ok.txt", b"x")])
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    assert [p.name for p in result.extracted] == ["ok.txt"]
    assert any(
        member == "INNER.ZIP" and reason == "nested archive" for member, reason in result.skipped
    )


def test_destination_outside_target_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The validator normally returns a flat basename; simulate a non-conforming
    # return value to exercise the extractor's own containment check.
    monkeypatch.setattr(
        DocumentValidator,
        "validate_upload_safety",
        staticmethod(lambda basename, file_size, allowed_extensions=None: "../outside.txt"),
    )
    src = _make_zip(tmp_path / "a.zip", [("leak.txt", b"payload")])
    out = tmp_path / "out"

    result = safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)

    assert result.extracted == []
    assert any("escapes target directory" in reason for _, reason in result.skipped)
    assert not (tmp_path / "outside.txt").exists()
    assert list(out.iterdir()) == []


def test_unwritable_destination_surfaces_as_oserror(tmp_path: Path) -> None:
    src = _make_zip(tmp_path / "a.zip", [("occupied.txt", b"payload")])
    out = tmp_path / "out"
    (out / "occupied.txt").mkdir(parents=True)

    with pytest.raises(OSError):
        safe_extract_zip(src, out, allowed_extensions=DOC_EXTS)


def test_member_exceeding_declared_size_is_removed_and_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _make_zip(tmp_path / "a.zip", [("a.txt", b"A" * 100)])
    real_open = zipfile.ZipFile.open

    def padded_open(self, *args, **kwargs):
        return _PaddedStream(real_open(self, *args, **kwargs), b"B" * 400)

    monkeypatch.setattr(zipfile.ZipFile, "open", padded_open)
    out = tmp_path / "out"

    with pytest.raises(ArchiveTooLargeError):
        safe_extract_zip(
            src,
            out,
            allowed_extensions=DOC_EXTS,
            limits=ZipExtractionLimits(max_entry_bytes=300),
        )

    assert list(out.glob("*.txt")) == []  # partial output is cleaned up
