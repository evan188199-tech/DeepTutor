"""Cleanup behaviour of ``_save_uploaded_files`` when a later file fails.

When one file of a multi-file upload fails, the already-written files are
removed again. These tests pin both halves of that contract: the cleanup
itself, and the visibility (warning log + error detail) when a cleanup
removal fails and a file has to stay on disk.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi import HTTPException, UploadFile

from deeptutor.api.routers import knowledge as knowledge_router
from deeptutor.api.routers.knowledge import _save_uploaded_files

ALLOWED = {".txt", ".md", ".pdf"}
LOGGER_NAME = "deeptutor.api.routers.knowledge"


@pytest.fixture(autouse=True)
def _disable_pocketbase(monkeypatch):
    monkeypatch.setattr("deeptutor.services.pocketbase_client.is_pocketbase_enabled", lambda: False)


def _upload(filename: str, data: bytes) -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(data))


class _StreamThatFailsMidRead(io.BytesIO):
    """Yields one chunk, then raises like a truncated/disk-full stream."""

    def __init__(self) -> None:
        super().__init__(b"partial bytes")
        self._reads = 0

    def read(self, size: int = -1) -> bytes:
        if self._reads == 0:
            self._reads += 1
            return b"partial bytes"
        raise OSError("mock stream read failure")


def test_later_file_failure_removes_previously_written_files(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()

    with pytest.raises(HTTPException) as exc_info:
        _save_uploaded_files(
            [
                _upload("first.txt", b"first"),
                _upload("second.exe", b"second"),  # disallowed extension
            ],
            raw,
            allowed_extensions=ALLOWED,
        )

    assert exc_info.value.status_code == 400
    assert not (raw / "first.txt").exists()
    assert not (raw / "second.exe").exists()
    assert list(raw.iterdir()) == []


def test_cleanup_failure_of_written_file_is_logged_and_reported(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    real_unlink = knowledge_router.os.unlink

    def _unlink_that_fails_for_first(path, *, dir_fd=None):
        if Path(path).name == "first.txt":
            raise OSError("mock unlink failure")
        return real_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(knowledge_router.os, "unlink", _unlink_that_fails_for_first)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        with pytest.raises(HTTPException) as exc_info:
            _save_uploaded_files(
                [
                    _upload("first.txt", b"first"),
                    _upload("second.exe", b"second"),  # disallowed extension
                ],
                raw,
                allowed_extensions=ALLOWED,
            )

    assert exc_info.value.status_code == 400
    # The leftover is visible both in the raised detail and in a warning log.
    assert str(raw / "first.txt") in exc_info.value.detail
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(str(raw / "first.txt") in r.getMessage() for r in warnings)
    # The file itself is still there — that is exactly what got reported.
    assert (raw / "first.txt").exists()


def test_partial_file_cleanup_failure_is_logged_and_reported(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    real_unlink = knowledge_router.os.unlink

    def _unlink_that_always_fails(path, *, dir_fd=None):
        raise OSError("mock unlink failure")

    monkeypatch.setattr(knowledge_router.os, "unlink", _unlink_that_always_fails)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        with pytest.raises(HTTPException) as exc_info:
            _save_uploaded_files(
                [UploadFile(filename="partial.txt", file=_StreamThatFailsMidRead())],
                raw,
                allowed_extensions=ALLOWED,
            )

    assert exc_info.value.status_code == 400
    assert str(raw / "partial.txt") in exc_info.value.detail
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(str(raw / "partial.txt") in r.getMessage() for r in warnings)
