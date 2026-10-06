"""Attempt-directory recycling for the local MinerU CLI (follow-up to #1612).

Failed attempts stay on disk for diagnostics, but only the newest
``_ATTEMPT_RETENTION_LIMIT`` survive: older ones are recycled on every parse
so repeated failures cannot grow ``output_base_dir`` without bound.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from deeptutor.services.parsing.engines.mineru import local as mineru_local
from deeptutor.services.parsing.engines.mineru.local import (
    LocalParseReason,
    parse_document_with_mineru_result,
)


@pytest.fixture()
def pdf(tmp_path: Path) -> Path:
    source = tmp_path / "exam.pdf"
    source.write_bytes(b"%PDF-1.4")
    return source


def _install_fake_popen(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int = 0,
    artifacts: tuple[str, ...] = (),
) -> None:
    """Patch the subprocess factory so the local CLI is simulated in-process."""

    class FakeProcess:
        def __init__(self, cmd, **_kwargs) -> None:  # noqa: ANN001
            target = Path(cmd[cmd.index("-o") + 1])
            for name in artifacts:
                path = target / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# parsed", encoding="utf-8")
            self.stdout = iter(())

        def wait(self) -> int:
            return returncode

    monkeypatch.setattr(mineru_local.subprocess, "Popen", FakeProcess)


def _stamp(path: Path, seconds: int) -> None:
    os.utime(path, (seconds, seconds))


def test_repeated_failures_recycle_oldest_attempts(
    pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "out"
    limit = mineru_local._ATTEMPT_RETENTION_LIMIT
    _install_fake_popen(monkeypatch, returncode=9)

    for _ in range(limit + 3):
        result = parse_document_with_mineru_result(pdf, output, cli_command="mineru")
        assert result.reason is LocalParseReason.NONZERO_EXIT
        assert len(list(output.glob(".mineru-attempt-*"))) <= limit

    retained = list(output.glob(".mineru-attempt-*"))
    assert len(retained) == limit
    for attempt in retained:
        assert '"incomplete"' in (attempt / "state.json").read_text(encoding="utf-8")


def test_success_prunes_stale_attempts_and_keeps_unrelated_dirs(
    pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "out"
    limit = mineru_local._ATTEMPT_RETENTION_LIMIT
    for index in range(limit + 2):
        attempt = output / f".mineru-attempt-stale{index:02d}"
        (attempt / "output").mkdir(parents=True)
        (attempt / "state.json").write_text('{"state": "incomplete"}', encoding="utf-8")
        _stamp(attempt, 1_000_000_000 + index)
    backup = output / ".exam.previous-abc123"
    backup.mkdir()
    _stamp(backup, 1_000_000_000)

    _install_fake_popen(monkeypatch, artifacts=("exam.md",))
    result = parse_document_with_mineru_result(pdf, output, cli_command="mineru")

    assert result.ok
    assert (output / "exam" / "exam.md").is_file()
    remaining = {path.name for path in output.glob(".mineru-attempt-*")}
    assert ".mineru-attempt-stale00" not in remaining
    assert ".mineru-attempt-stale01" not in remaining
    assert {f".mineru-attempt-stale{index:02d}" for index in range(2, limit + 2)} <= remaining
    # The successful parse recycles its own attempt directory.
    assert len(remaining) == limit
    # Unrelated directories are never touched by recycling.
    assert backup.is_dir()


def test_prune_keeps_newest_and_ignores_non_attempt_entries(tmp_path: Path) -> None:
    oldest = tmp_path / ".mineru-attempt-old"
    newest = tmp_path / ".mineru-attempt-new"
    for path, stamp in ((oldest, 1_000_000_000), (newest, 2_000_000_000)):
        path.mkdir()
        _stamp(path, stamp)
    unrelated = tmp_path / ".exam.previous-abc123"
    unrelated.mkdir()
    file_named_like_attempt = tmp_path / ".mineru-attempt-notadir"
    file_named_like_attempt.write_text("x", encoding="utf-8")

    mineru_local._prune_stale_attempts(tmp_path, keep=1)

    assert newest.is_dir()
    assert not oldest.exists()
    assert unrelated.is_dir()
    assert file_named_like_attempt.is_file()
