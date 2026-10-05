"""Unit contracts for ``deeptutor.services.office_preview``.

Every external converter is mocked; LibreOffice is never launched and no
server is started. Covers format detection, conversion failure, timeout
kill paths, and cache-boundary behaviour.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import time
from types import SimpleNamespace

import pytest

from deeptutor.services import office_preview


def _cache_key(data: bytes, suffix: str) -> str:
    return hashlib.sha256(b"office-preview-v1\0" + suffix.encode() + b"\0" + data).hexdigest()


def _install_converter(monkeypatch, process: SimpleNamespace) -> None:
    monkeypatch.setattr(office_preview.shutil, "which", lambda _name: "/fake/soffice")
    monkeypatch.setattr(office_preview.subprocess, "Popen", process)


class FakeProcess:
    def __init__(
        self,
        pdf_bytes: bytes | None = b"%PDF-1.7\nok",
        *,
        returncode: int = 0,
        raise_on_start: bool = False,
        timeout_first_wait: bool = False,
    ) -> None:
        self.pdf_bytes = pdf_bytes
        self.returncode = returncode
        self.raise_on_start = raise_on_start
        self.timeout_first_wait = timeout_first_wait
        self.pid = 4242
        self.events: list[str] = []
        self._pending_output: Path | None = None

    def __call__(self, args: list[str], **_kwargs) -> "FakeProcess":
        if self.raise_on_start:
            raise OSError("soffice is gone")
        self._pending_output = Path(args[args.index("--outdir") + 1])
        return self

    def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
        if self.timeout_first_wait and timeout is not None:
            self.events.append("communicate-timeout")
            raise subprocess.TimeoutExpired(cmd="soffice", timeout=timeout)
        self.events.append("communicate")
        if self._pending_output is not None and self.pdf_bytes is not None:
            self._pending_output.mkdir(parents=True, exist_ok=True)
            (self._pending_output / "source.pdf").write_bytes(self.pdf_bytes)
            self._pending_output = None
        return (b"", b"")

    def kill(self) -> None:
        self.events.append("kill")


def test_format_detection_rejects_empty_and_unsupported_but_normalizes_case(
    monkeypatch, tmp_path: Path
) -> None:
    process = FakeProcess()
    _install_converter(monkeypatch, process)
    with pytest.raises(office_preview.OfficePreviewInvalid):
        asyncio.run(office_preview.render_office_pdf(b"", "report.docx", tmp_path))
    with pytest.raises(office_preview.OfficePreviewInvalid):
        asyncio.run(office_preview.render_office_pdf(b"office", "report.txt", tmp_path))
    assert process.events == []

    pdf = asyncio.run(office_preview.render_office_pdf(b"office", "REPORT.Docx", tmp_path))
    assert pdf.startswith(b"%PDF-")
    assert process.events == ["communicate"]


def test_converter_start_failure_raises_conversion_failed(monkeypatch, tmp_path: Path) -> None:
    process = FakeProcess(raise_on_start=True)
    _install_converter(monkeypatch, process)
    with pytest.raises(office_preview.OfficePreviewConversionFailed):
        asyncio.run(office_preview.render_office_pdf(b"office", "report.docx", tmp_path))
    assert list(tmp_path.glob("*")) == []


def test_nonzero_returncode_raises_conversion_failed(monkeypatch, tmp_path: Path) -> None:
    process = FakeProcess(returncode=1)
    _install_converter(monkeypatch, process)
    with pytest.raises(office_preview.OfficePreviewConversionFailed):
        asyncio.run(office_preview.render_office_pdf(b"office", "report.docx", tmp_path))
    assert list(tmp_path.glob("*")) == []


def test_missing_rendered_output_raises_conversion_failed(monkeypatch, tmp_path: Path) -> None:
    process = FakeProcess(pdf_bytes=None)
    _install_converter(monkeypatch, process)
    with pytest.raises(office_preview.OfficePreviewConversionFailed):
        asyncio.run(office_preview.render_office_pdf(b"office", "report.docx", tmp_path))
    assert list(tmp_path.glob("*")) == []


def test_non_pdf_rendered_output_raises_conversion_failed_and_is_not_cached(
    monkeypatch, tmp_path: Path
) -> None:
    process = FakeProcess(pdf_bytes=b"definitely not a pdf")
    _install_converter(monkeypatch, process)
    with pytest.raises(office_preview.OfficePreviewConversionFailed):
        asyncio.run(office_preview.render_office_pdf(b"office", "report.docx", tmp_path))
    assert not (tmp_path / f"{_cache_key(b'office', '.docx')}.pdf").exists()


def test_oversized_rendered_pdf_raises_invalid(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(office_preview, "MAX_PREVIEW_PDF_BYTES", 8)
    process = FakeProcess(pdf_bytes=b"%PDF-1.7" + b"x" * 64)
    _install_converter(monkeypatch, process)
    with pytest.raises(office_preview.OfficePreviewInvalid):
        asyncio.run(office_preview.render_office_pdf(b"office", "report.docx", tmp_path))
    assert not (tmp_path / f"{_cache_key(b'office', '.docx')}.pdf").exists()


def test_timeout_kills_process_group_then_raises_timeout(monkeypatch, tmp_path: Path) -> None:
    process = FakeProcess(pdf_bytes=None, timeout_first_wait=True)
    _install_converter(monkeypatch, process)
    killpg_calls: list[tuple[int, int]] = []

    def fake_killpg(pid: int, sig: int) -> None:
        killpg_calls.append((pid, sig))

    monkeypatch.setattr(os, "killpg", fake_killpg)
    with pytest.raises(office_preview.OfficePreviewTimeout):
        asyncio.run(office_preview.render_office_pdf(b"office", "report.docx", tmp_path))
    assert killpg_calls == [(process.pid, signal.SIGKILL)]
    assert process.events == ["communicate-timeout", "communicate"]
    assert "kill" not in process.events


def test_timeout_kill_falls_back_to_process_kill_when_group_kill_fails(
    monkeypatch, tmp_path: Path
) -> None:
    process = FakeProcess(pdf_bytes=None, timeout_first_wait=True)
    _install_converter(monkeypatch, process)

    def failing_killpg(pid: int, sig: int) -> None:
        raise OSError("no such process group")

    monkeypatch.setattr(os, "killpg", failing_killpg)
    with pytest.raises(office_preview.OfficePreviewTimeout):
        asyncio.run(office_preview.render_office_pdf(b"office", "report.docx", tmp_path))
    assert "kill" in process.events
    assert process.events == ["communicate-timeout", "kill", "communicate"]


def test_cached_entry_without_pdf_magic_is_reconverted_and_refreshed(
    monkeypatch, tmp_path: Path
) -> None:
    cached = tmp_path / f"{_cache_key(b'office', '.docx')}.pdf"
    cached.write_bytes(b"stale bytes")
    process = FakeProcess()
    _install_converter(monkeypatch, process)
    pdf = asyncio.run(office_preview.render_office_pdf(b"office", "report.docx", tmp_path))
    assert pdf.startswith(b"%PDF-")
    assert process.events == ["communicate"]
    assert cached.read_bytes() == pdf


def test_oversized_cached_entry_is_not_served(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(office_preview, "MAX_PREVIEW_PDF_BYTES", 8)
    cached = tmp_path / f"{_cache_key(b'office', '.docx')}.pdf"
    cached.write_bytes(b"%PDF-1.7" + b"x" * 64)
    process = FakeProcess(pdf_bytes=b"%PDF-1.4")
    _install_converter(monkeypatch, process)
    pdf = asyncio.run(office_preview.render_office_pdf(b"office", "report.docx", tmp_path))
    assert pdf == b"%PDF-1.4"
    assert process.events == ["communicate"]
    assert cached.read_bytes() == b"%PDF-1.4"


def test_symlinked_cache_entry_is_ignored_and_replaced_by_regular_file(
    monkeypatch, tmp_path: Path
) -> None:
    cached = tmp_path / f"{_cache_key(b'office', '.docx')}.pdf"
    cached.symlink_to(tmp_path / "elsewhere.pdf")
    process = FakeProcess()
    _install_converter(monkeypatch, process)
    pdf = asyncio.run(office_preview.render_office_pdf(b"office", "report.docx", tmp_path))
    assert pdf.startswith(b"%PDF-")
    assert process.events == ["communicate"]
    assert cached.is_file()
    assert not cached.is_symlink()


def test_cache_write_failure_still_returns_rendered_pdf(monkeypatch, tmp_path: Path) -> None:
    process = FakeProcess()
    _install_converter(monkeypatch, process)

    def failing_replace(src: object, dst: object) -> None:
        raise OSError("cache disk is full")

    monkeypatch.setattr(os, "replace", failing_replace)
    pdf = asyncio.run(office_preview.render_office_pdf(b"office", "report.docx", tmp_path))
    assert pdf.startswith(b"%PDF-")
    assert process.events == ["communicate"]
    assert list(tmp_path.glob("*.pdf")) == []


def test_unusable_cache_dir_still_renders_without_cache(monkeypatch, tmp_path: Path) -> None:
    blocking = tmp_path / "not-a-dir"
    blocking.write_bytes(b"")
    process = FakeProcess()
    _install_converter(monkeypatch, process)
    pdf = asyncio.run(office_preview.render_office_pdf(b"office", "report.docx", blocking))
    assert pdf.startswith(b"%PDF-")
    assert process.events == ["communicate"]
    assert blocking.read_bytes() == b""


def test_prune_cache_enforces_ttl_count_and_symlink_rules(tmp_path: Path) -> None:
    stale = tmp_path / "stale.pdf"
    stale.write_bytes(b"%PDF-1.7 old")
    fresh = tmp_path / "fresh.pdf"
    fresh.write_bytes(b"%PDF-1.7 new")
    note = tmp_path / "notes.txt"
    note.write_bytes(b"keep me")
    target = tmp_path / "target.bin"
    target.write_bytes(b"keep target")
    link = tmp_path / "link.pdf"
    link.symlink_to(target)
    now = time.time()
    expired = now - office_preview.CACHE_TTL_SECONDS - 3600
    os.utime(stale, (expired, expired))
    os.utime(fresh, (now + 1000, now + 1000))
    bulk: list[Path] = []
    for index in range(office_preview.MAX_CACHE_FILES + 1):
        entry = tmp_path / f"bulk-{index}.pdf"
        entry.write_bytes(b"%PDF-1.7 bulk")
        moment = now - index
        os.utime(entry, (moment, moment))
        bulk.append(entry)

    office_preview._prune_cache(tmp_path)

    assert not stale.exists()
    assert not link.exists()
    assert target.exists()
    assert note.exists()
    assert fresh.exists()
    assert bulk[0].exists()
    assert bulk[office_preview.MAX_CACHE_FILES - 2].exists()
    assert not bulk[office_preview.MAX_CACHE_FILES - 1].exists()
    assert not bulk[-1].exists()
    assert len(list(tmp_path.glob("*.pdf"))) == office_preview.MAX_CACHE_FILES
