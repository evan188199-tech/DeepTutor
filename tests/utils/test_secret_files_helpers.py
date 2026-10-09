"""Contract and boundary tests for ensure_private_directory/ensure_private_file."""

from __future__ import annotations

import os
import stat

import pytest

from deeptutor.utils.secret_files import (
    SECRET_DIR_MODE,
    SECRET_FILE_MODE,
    ensure_private_directory,
    ensure_private_file,
    write_secret_text,
)

posix_only = pytest.mark.skipif(
    os.name != "posix", reason="POSIX permission bits are not modelled on Windows"
)


@posix_only
def test_ensure_private_directory_creates_missing_parents(tmp_path):
    target = tmp_path / "nested" / "deeper" / "secrets"

    returned = ensure_private_directory(target)

    assert returned == target
    assert target.is_dir()
    assert stat.S_IMODE(target.stat().st_mode) == SECRET_DIR_MODE


@posix_only
def test_ensure_private_directory_tightens_existing_directory(tmp_path):
    target = tmp_path / "secrets"
    target.mkdir(mode=0o755)

    ensure_private_directory(target)

    assert stat.S_IMODE(target.stat().st_mode) == SECRET_DIR_MODE


@posix_only
def test_ensure_private_directory_is_idempotent(tmp_path):
    target = ensure_private_directory(tmp_path / "secrets")

    ensure_private_directory(target)

    assert stat.S_IMODE(target.stat().st_mode) == SECRET_DIR_MODE


@posix_only
def test_ensure_private_directory_ignores_permissive_umask(tmp_path):
    previous = os.umask(0)
    try:
        target = tmp_path / "secrets"

        ensure_private_directory(target)

        assert stat.S_IMODE(target.stat().st_mode) == SECRET_DIR_MODE
    finally:
        os.umask(previous)


def test_ensure_private_directory_rejects_existing_file(tmp_path):
    target = tmp_path / "occupied"
    target.write_text("not a directory", encoding="utf-8")

    with pytest.raises(FileExistsError):
        ensure_private_directory(target)


@posix_only
def test_ensure_private_file_tightens_existing_file(tmp_path):
    target = tmp_path / "secret.txt"
    target.write_text("token-value", encoding="utf-8")
    target.chmod(0o644)

    returned = ensure_private_file(target)

    assert returned == target
    assert stat.S_IMODE(target.stat().st_mode) == SECRET_FILE_MODE
    assert target.read_text(encoding="utf-8") == "token-value"


@posix_only
def test_ensure_private_file_keeps_private_file_unchanged(tmp_path):
    target = tmp_path / "secret.txt"
    target.write_text("token-value", encoding="utf-8")
    target.chmod(SECRET_FILE_MODE)

    ensure_private_file(target)

    assert stat.S_IMODE(target.stat().st_mode) == SECRET_FILE_MODE


@posix_only
def test_ensure_private_file_tolerates_missing_file(tmp_path):
    target = tmp_path / "missing.txt"

    assert ensure_private_file(target) == target
    assert not target.exists()


@posix_only
def test_write_secret_text_creates_parent_with_private_mode(tmp_path):
    target = tmp_path / "nested" / "deeper" / "secret.txt"

    write_secret_text(target, "token-value")

    assert stat.S_IMODE(target.parent.stat().st_mode) == SECRET_DIR_MODE
