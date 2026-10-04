"""Tests for KnowledgeBaseManager.get_info() status promotion (issue #418).

When the persisted ``status`` in ``kb_config.json`` is a "live" sentinel
(``processing`` / ``initializing``) but a ready index version already exists on
disk, ``get_info`` must promote the reported status to ``ready`` so the UI does
not show a perpetual processing banner.

This typically happens when the progress writer or worker process crashes
after the LlamaIndex version is finalised (``ready: true``) but before
``update_kb_status(name, "ready")`` runs and rewrites kb_config.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deeptutor.knowledge.manager import KnowledgeBaseManager

ACTIVE_SIGNATURE = "active-signature"


class _Signature:
    def __init__(self, sig_hash: str = ACTIVE_SIGNATURE) -> None:
        self._hash = sig_hash

    def hash(self) -> str:
        return self._hash


def _create_ready_version(
    kb_dir: Path, version: int = 1, signature: str = ACTIVE_SIGNATURE
) -> None:
    """Create a flat version-N directory recognised as queryable by LlamaIndex."""
    version_dir = kb_dir / f"version-{version}"
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "docstore.json").write_text(
        json.dumps({"docstore/data": {"doc-1": {}}}),
        encoding="utf-8",
    )
    (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"signature": signature, "version": f"version-{version}"}),
        encoding="utf-8",
    )


def _patch_active_embedding(
    monkeypatch: pytest.MonkeyPatch, sig_hash: str = ACTIVE_SIGNATURE
) -> None:
    from deeptutor.knowledge import manager as manager_module
    from deeptutor.services.rag import embedding_signature

    monkeypatch.setattr(
        manager_module, "_get_embedding_fingerprint", lambda: ("embed-active", 4096)
    )
    monkeypatch.setattr(
        embedding_signature,
        "signature_from_embedding_config",
        lambda: _Signature(sig_hash),
    )


def test_processing_with_ready_index_promotes_to_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Headline reproduction of issue #418.

    kb_config.json has ``status: "processing"`` and stale
    ``progress.stage: "processing_documents"``, but a ready version-1 exists.
    """
    _patch_active_embedding(monkeypatch)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.update_kb_status(
        name="kb1",
        status="processing",
        progress={
            "stage": "processing_documents",
            "message": "Embedding chunks",
            "percent": 60,
        },
    )
    _create_ready_version(tmp_path / "kb1")

    info = manager.get_info("kb1")
    assert info["status"] == "ready"
    # When promoted to ready the progress banner is cleared so consumers
    # don't show "ready" + a stale processing bar at the same time.
    assert info["progress"] is None
    assert info["statistics"]["status"] == "ready"
    assert info["statistics"]["progress"] is None
    assert info["statistics"]["rag_initialized"] is True


def test_fresh_empty_kb_stays_ready_without_an_index_version(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.update_kb_status(name="empty", status="ready", progress=None)

    info = manager.get_info("empty")

    assert info["status"] == "ready"
    assert info["statistics"]["rag_initialized"] is False


def test_processing_with_completed_progress_and_ready_index_promotes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Variant: progress.stage == "completed" but status not yet flipped."""
    _patch_active_embedding(monkeypatch)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.update_kb_status(
        name="kb2",
        status="processing",
        progress={"stage": "completed", "percent": 100},
    )
    _create_ready_version(tmp_path / "kb2")

    info = manager.get_info("kb2")
    assert info["status"] == "ready"
    assert info["progress"] is None


def test_get_info_counts_nested_raw_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_active_embedding(monkeypatch)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    kb_dir = tmp_path / "kb-nested"
    raw_dir = kb_dir / "raw"
    (raw_dir / "ModuleA").mkdir(parents=True)
    (raw_dir / "ModuleA" / "a.pdf").write_text("%PDF-1.4\n", encoding="utf-8")
    (raw_dir / "root.txt").write_text("hello", encoding="utf-8")
    _create_ready_version(kb_dir)
    manager.update_kb_status(name="kb-nested", status="ready", progress=None)

    info = KnowledgeBaseManager(base_dir=str(tmp_path)).get_info("kb-nested")

    assert info["statistics"]["raw_documents"] == 2


def test_initializing_with_ready_index_promotes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``initializing`` is also a live sentinel and must be recoverable."""
    _patch_active_embedding(monkeypatch)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.update_kb_status(name="kb3", status="initializing", progress=None)
    _create_ready_version(tmp_path / "kb3")

    info = manager.get_info("kb3")
    assert info["status"] == "ready"


def test_processing_with_error_stage_is_not_promoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ``error`` stage must NOT be silently promoted, even if an older
    ready version still exists on disk — the user needs to see the failure.
    """
    _patch_active_embedding(monkeypatch)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.update_kb_status(
        name="kb4",
        status="processing",
        progress={"stage": "error", "error": "embedding API down"},
    )
    _create_ready_version(tmp_path / "kb4")

    info = manager.get_info("kb4")
    assert info["status"] == "processing"
    assert info["progress"] is not None
    assert info["progress"].get("stage") == "error"


def test_processing_without_ready_index_not_promoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Genuine in-flight indexing (no ready version yet) stays as ``processing``."""
    _patch_active_embedding(monkeypatch)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.update_kb_status(
        name="kb5",
        status="processing",
        progress={"stage": "processing_documents", "percent": 25},
    )
    # Allocate the version dir but leave it empty (writer reserved it but
    # has not persisted any storage files yet — it's NOT ready).
    (tmp_path / "kb5" / "version-1").mkdir(parents=True)

    info = manager.get_info("kb5")
    assert info["status"] == "processing"
    assert info["progress"] is not None
    assert info["progress"].get("stage") == "processing_documents"


def test_ready_status_unaffected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``status="ready"`` is a no-op for the new branch — verify the existing
    happy path still reports ready.
    """
    _patch_active_embedding(monkeypatch)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    _create_ready_version(tmp_path / "kb6")
    manager.update_kb_status(name="kb6", status="ready", progress=None)

    info = manager.get_info("kb6")
    assert info["status"] == "ready"


def test_ready_lightrag_with_failed_doc_status_reports_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_active_embedding(monkeypatch)
    kb_dir = tmp_path / "kb-lightrag"
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True)
    (version_dir / "meta.json").write_text(
        json.dumps(
            {
                "provider": "lightrag",
                "signature": "lightrag",
                "version": "version-1",
            }
        ),
        encoding="utf-8",
    )
    (version_dir / "kv_store_doc_status.json").write_text(
        json.dumps(
            {
                "doc-1": {
                    "status": "failed",
                    "file_path": "bad.docx",
                    "error_msg": "'list' object has no attribute 'size'",
                    "chunks_list": [],
                }
            }
        ),
        encoding="utf-8",
    )
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.config.setdefault("knowledge_bases", {})["kb-lightrag"] = {
        "path": "kb-lightrag",
        "rag_provider": "lightrag",
        "status": "ready",
    }
    manager._save_config()

    info = KnowledgeBaseManager(base_dir=str(tmp_path)).get_info("kb-lightrag")
    assert info["status"] == "error"
    assert info["progress"]["stage"] == "error"
    assert "bad.docx" in info["progress"]["error"]
    assert info["statistics"]["rag_initialized"] is False
    assert info["statistics"]["index_versions"][0]["ready"] is False


def test_needs_reindex_takes_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``effective_needs_reindex`` is checked first — promotion to ready
    must not run when the on-disk version was indexed under a different
    embedding signature than the currently active one.
    """
    _patch_active_embedding(monkeypatch)
    # Version was indexed under "old-signature"; active is "active-signature".
    # _reconcile_against_active_embedding will see the mismatch and flip
    # needs_reindex=True on load.
    _create_ready_version(tmp_path / "kb7", signature="old-signature")
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.update_kb_status(
        name="kb7",
        status="processing",
        progress={"stage": "completed", "percent": 100},
    )

    info = manager.get_info("kb7")
    assert info["status"] == "needs_reindex"


def test_get_info_does_not_reparse_docstore_on_repeat_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``kb list`` / the knowledge API must not re-parse docstore.json per call.

    Regression test for issue #859: probing every index version parses the
    multi-MB LlamaIndex docstore.json, and get_info used to probe the same
    versions two or three times per KB (scan, failure summary, active-match
    re-probe). With the docstore-count cache and version reuse, a second
    get_info call must not read the file again at all.
    """
    _patch_active_embedding(monkeypatch)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.update_kb_status(name="kb-perf", status="ready")
    _create_ready_version(tmp_path / "kb-perf")

    from deeptutor.services.rag import index_probe as probe_module

    real_read = probe_module._read_json
    reads: list[str] = []

    def counting_read(path: Path) -> dict[str, Any] | None:
        reads.append(str(path))
        return real_read(path)

    monkeypatch.setattr(probe_module, "_read_json", counting_read)

    info = manager.get_info("kb-perf")
    assert info["status"] == "ready"
    assert info["statistics"]["active_match"] is True
    parses_after_first_call = len(reads)
    assert parses_after_first_call == 1  # one docstore.json read for the probe

    info_again = manager.get_info("kb-perf")
    assert info_again["status"] == "ready"
    assert info_again["statistics"]["active_match"] is True
    # Cached count + reused version probes: no re-read of the docstore.
    assert len(reads) == parses_after_first_call


def test_get_info_count_failures_report_unknown_not_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A counter that cannot be computed must surface as ``None`` (unknown),
    never as a fake ``0`` — otherwise a broken KB looks like an empty one and
    the failure is undiagnosable from the KB detail page.
    """
    import logging

    from deeptutor.knowledge import manager as manager_module

    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    kb_dir = tmp_path / "kb-counts"
    (kb_dir / "raw").mkdir(parents=True)
    (kb_dir / "raw" / "a.pdf").write_text("%PDF-1.4\n", encoding="utf-8")
    # A stray file where the images directory belongs makes ``iterdir()``
    # fail with NotADirectoryError.
    (kb_dir / "images").write_text("not a directory", encoding="utf-8")
    (kb_dir / "content_list").mkdir()
    manager.update_kb_status(name="kb-counts", status="ready", progress=None)

    def _unreadable_raw(root: Path):
        raise PermissionError("raw directory is unreadable")

    real_glob = Path.glob

    def _unreadable_content_list(self: Path, /, pattern: str):
        if self.name == "content_list":
            raise PermissionError("content_list directory is unreadable")
        return real_glob(self, pattern)

    monkeypatch.setattr(manager_module, "iter_kb_documents", _unreadable_raw)
    monkeypatch.setattr(Path, "glob", _unreadable_content_list)

    with caplog.at_level(logging.WARNING, logger="deeptutor.knowledge.manager"):
        info = manager.get_info("kb-counts")

    statistics = info["statistics"]
    assert statistics["raw_documents"] is None
    assert statistics["images"] is None
    assert statistics["content_lists"] is None
    warned = " ".join(record.getMessage() for record in caplog.records)
    assert "kb-counts" in warned
    assert "raw documents" in warned
    assert "images" in warned
    assert "content lists" in warned


def test_get_info_empty_kb_reports_real_zero_counts(tmp_path: Path) -> None:
    """A healthy KB with no files reports genuine ``0`` counts — the inverse
    guarantee that keeps ``None`` meaningful as "unknown".
    """
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    kb_dir = tmp_path / "kb-empty"
    (kb_dir / "raw").mkdir(parents=True)
    (kb_dir / "images").mkdir()
    (kb_dir / "content_list").mkdir()
    manager.update_kb_status(name="kb-empty", status="ready", progress=None)

    statistics = manager.get_info("kb-empty")["statistics"]

    assert statistics["raw_documents"] == 0
    assert statistics["images"] == 0
    assert statistics["content_lists"] == 0


def test_get_default_logs_warning_when_config_service_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the centralized config read fails, the first-KB fallback still
    applies, but the failure must be logged instead of silently swallowed.
    """
    import logging

    import deeptutor.services.config as config_module

    def _broken_service():
        raise RuntimeError("config service unavailable")

    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    (tmp_path / "kb-a").mkdir()
    manager.update_kb_status(name="kb-a", status="ready", progress=None)

    monkeypatch.setattr(config_module, "get_kb_config_service", _broken_service)

    with caplog.at_level(logging.WARNING, logger="deeptutor.knowledge.manager"):
        default = manager.get_default()

    assert default == "kb-a"
    assert any("default KB" in record.getMessage() for record in caplog.records), [
        record.getMessage() for record in caplog.records
    ]
