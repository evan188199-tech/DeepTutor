"""Batch regression: v1.6.13 LOW swallowed-error spots log instead of staying silent.

Each test pins one narrow ``except`` branch added in v1.6.13: the behavior
(cache miss / skipped candidate / cleanup survival) is unchanged, but a debug
record is emitted so the swallow is diagnosable.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from deeptutor.services.llm import image_caption_cache
from deeptutor.services.parsing.engines.mineru import local as mineru_local
from deeptutor.services.parsing.engines.mineru.checkpoints import SliceCheckpoint
from deeptutor.services.rag.pipelines.llamaindex import exercise_lookup
from deeptutor.services.storage.attachment_store import LocalDiskAttachmentStore

# ---------------------------------------------------------------------------
# image_caption_cache — unreadable single/batch entries are logged misses
# ---------------------------------------------------------------------------


def test_read_caption_logs_unreadable_entry(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    entry = tmp_path / "broken.json"
    entry.write_text("{not json", encoding="utf-8")

    with caplog.at_level(logging.DEBUG, logger=image_caption_cache.__name__):
        assert image_caption_cache._read_caption(entry) is None

    assert "image caption cache entry" in caplog.text
    assert str(entry) in caplog.text


def test_read_batch_captions_logs_unreadable_entry(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    entry = tmp_path / "broken-batch.json"
    entry.write_text('["not', encoding="utf-8")

    with caplog.at_level(logging.DEBUG, logger=image_caption_cache.__name__):
        assert image_caption_cache._read_batch_captions(entry, 2) is None

    assert "image caption batch cache entry" in caplog.text


# ---------------------------------------------------------------------------
# exercise_lookup — unreadable manifests and unusable sources are logged skips
# ---------------------------------------------------------------------------


def test_parse_for_logs_unreadable_manifest(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    source = tmp_path / "raw" / "exam.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-1.4")
    stat = source.stat()
    digest = exercise_lookup._source_hash(str(source), stat.st_mtime_ns, stat.st_size)
    manifest = tmp_path / "cache" / digest[:2] / digest / "v1" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{not json", encoding="utf-8")

    with caplog.at_level(logging.DEBUG, logger=exercise_lookup.__name__):
        assert exercise_lookup._parse_for(source, tmp_path / "cache") is None

    assert "exercise parse manifest" in caplog.text
    assert str(manifest) in caplog.text


def test_lookup_exercises_logs_unusable_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    raw = tmp_path / "kb" / "raw"
    raw.mkdir(parents=True)
    (raw / "exam.pdf").write_bytes(b"%PDF-1.4")

    def unusable(*_args: object, **_kwargs: object) -> Path | None:
        raise OSError("controlled manifest read failure")

    monkeypatch.setattr(exercise_lookup, "_parse_for", unusable)

    with caplog.at_level(logging.DEBUG, logger=exercise_lookup.__name__):
        assert (
            exercise_lookup.lookup_exercises("查找习题2-3", tmp_path / "kb", tmp_path / "cache")
            is None
        )

    assert "unusable exercise source" in caplog.text
    assert "exam.pdf" in caplog.text


# ---------------------------------------------------------------------------
# mineru checkpoints — unusable checkpoint state is a logged miss
# ---------------------------------------------------------------------------


def test_slice_checkpoint_load_logs_unusable_pointer(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    checkpoint = SliceCheckpoint(tmp_path / "job", 0, 4)
    checkpoint.directory.mkdir(parents=True)
    checkpoint.pointer.write_text("{not json", encoding="utf-8")

    with caplog.at_level(
        logging.DEBUG, logger="deeptutor.services.parsing.engines.mineru.checkpoints"
    ):
        assert checkpoint.load() is None

    assert "mineru slice checkpoint" in caplog.text
    assert str(checkpoint.pointer) in caplog.text


# ---------------------------------------------------------------------------
# attachment_store — surviving legacy dir cleanup is logged, moves are kept
# ---------------------------------------------------------------------------


def test_materialize_session_logs_uncleanable_legacy_dir(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = LocalDiskAttachmentStore(tmp_path / "workspace", legacy_root=tmp_path / "legacy")
    session = store._session_dir("s1")
    legacy_session = tmp_path / "legacy" / "s1"
    legacy_session.mkdir(parents=True)
    (legacy_session / "a_file.txt").write_text("payload", encoding="utf-8")
    (legacy_session / "dangling.txt").symlink_to(tmp_path / "nowhere")

    with caplog.at_level(logging.DEBUG, logger="deeptutor.services.storage.attachment_store"):
        store._materialize_session_sync("s1")

    assert (session / "a_file.txt").read_text(encoding="utf-8") == "payload"
    assert legacy_session.is_dir()
    assert "legacy attachment dir" in caplog.text


# ---------------------------------------------------------------------------
# mineru local — failed diagnostic write is logged, original failure survives
# ---------------------------------------------------------------------------


def test_mineru_failure_state_write_is_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    source = tmp_path / "exam.pdf"
    source.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(mineru_local, "check_mineru_installed", lambda: None)

    class FakeProcess:
        def __init__(self, cmd: list[str], **_kwargs: object) -> None:
            self.stdout = iter(("one problem",))

        def wait(self) -> int:
            return 7

    monkeypatch.setattr(mineru_local.subprocess, "Popen", FakeProcess)
    original_write = mineru_local.atomic_write_json

    def fail_incomplete_state(path: Path, payload: object) -> None:
        if isinstance(payload, dict) and payload.get("state") == "incomplete":
            raise OSError("controlled diagnostic write failure")
        original_write(path, payload)

    monkeypatch.setattr(mineru_local, "atomic_write_json", fail_incomplete_state)

    with caplog.at_level(logging.DEBUG, logger=mineru_local.__name__):
        result = mineru_local.parse_document_with_mineru_result(
            source, tmp_path / "out", cli_command="mineru"
        )

    assert result.ok is False
    assert result.reason is mineru_local.LocalParseReason.NONZERO_EXIT
    assert "diagnostic state" in caplog.text
