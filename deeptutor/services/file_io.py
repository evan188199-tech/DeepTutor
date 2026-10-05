"""Small, dependency-free helpers for durable service files."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import tempfile
import time
from typing import Any

logger = logging.getLogger(__name__)


def fsync_directory(directory: Path) -> None:
    """Best-effort fsync of *directory* so a completed rename reaches disk.

    A rename is only durable once its directory entry is synced; a power loss
    can otherwise undo it even though the file contents were fsynced first.
    Windows has no ``O_DIRECTORY``, so directory syncing is skipped there.
    Any other failure only weakens that durability promise — the replacement
    already published complete content — so it is logged as a warning.
    """
    if not hasattr(os, "O_DIRECTORY"):  # pragma: no cover - platform specific
        return
    try:
        fd = os.open(str(directory), os.O_RDONLY | os.O_DIRECTORY)
    except OSError as exc:
        logger.warning("Could not open directory %s for fsync after rename: %r", directory, exc)
        return
    try:
        os.fsync(fd)
    except OSError as exc:
        logger.warning("Could not fsync directory %s after rename: %r", directory, exc)
    finally:
        os.close(fd)


def _atomic_replace(src: Path, dst: Path, *, max_retries: int = 5) -> None:
    """Replace *dst* with *src*, retrying on transient ``PermissionError``.

    On Windows the destination file is occasionally locked by another process
    (antivirus, indexer, or a concurrent reader), which makes ``Path.replace``
    raise ``PermissionError``. A short exponential backoff recovers in most
    cases without losing the already-written content.

    After a successful replacement the destination directory is fsynced so the
    rename itself survives a power loss.
    """
    delay = 0.2
    last_err: PermissionError | None = None
    for attempt in range(max_retries):
        try:
            src.replace(dst)
            fsync_directory(dst.parent)
            return
        except PermissionError as exc:  # pragma: no cover - platform specific
            last_err = exc
            if attempt == max_retries - 1:
                break
            time.sleep(delay)
            delay = min(delay * 2, 1.6)
    assert last_err is not None
    raise last_err


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write *payload* as UTF-8 JSON without exposing a partial target file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        _atomic_replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    """Write UTF-8 text with a same-directory atomic replacement."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        _atomic_replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


__all__ = ["atomic_write_json", "atomic_write_text", "fsync_directory"]
