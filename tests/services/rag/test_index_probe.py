from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deeptutor.services.rag.index_probe import (
    _lightrag_doc_count,
    _llamaindex_doc_count,
    has_ready_provider_index,
    inspect_kb_versions,
    inspect_provider_index,
    inspect_provider_version,
    latest_ready_provider_version,
    provider_failure_summary,
)
from deeptutor.services.rag.pipelines.graphrag import storage as graphrag_storage
from deeptutor.services.rag.pipelines.pageindex import storage as pageindex_storage


def _write_meta(version_dir: Path, *, provider: str, signature: str | None = None) -> None:
    (version_dir / "meta.json").write_text(
        json.dumps(
            {
                "version": version_dir.name,
                "provider": provider,
                "signature": signature or provider,
                "layout": "flat",
            }
        ),
        encoding="utf-8",
    )


def test_llamaindex_requires_real_storage_files(tmp_path: Path) -> None:
    version_dir = tmp_path / "version-1"
    version_dir.mkdir()
    (version_dir / "docstore.json").write_text(
        json.dumps({"docstore/data": {"doc-1": {}}}),
        encoding="utf-8",
    )

    probe = inspect_provider_index("llamaindex", version_dir)

    assert probe.ready is False
    assert "index_store.json" in probe.failure_summary
    assert probe.doc_count == 1

    (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    probe = inspect_provider_index("llamaindex", version_dir)
    assert probe.ready is True
    assert probe.doc_count == 1


def test_empty_kb_has_no_failure_summary(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()

    assert inspect_kb_versions(tmp_path, "llamaindex") == []
    assert has_ready_provider_index(tmp_path, "llamaindex") is False
    assert provider_failure_summary(tmp_path, "llamaindex") == ""
    assert provider_failure_summary(tmp_path, "llamaindex", versions=[]) == ""


def test_kb_versions_overrule_fake_llamaindex_ready_marker(tmp_path: Path) -> None:
    version_dir = tmp_path / "version-1"
    version_dir.mkdir()
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    _write_meta(version_dir, provider="llamaindex", signature="sig")

    versions = inspect_kb_versions(tmp_path, "llamaindex")

    assert versions[0]["ready"] is False
    assert "index_store.json" in versions[0]["failure_summary"]
    assert has_ready_provider_index(tmp_path, "llamaindex") is False
    assert "index_store.json" in provider_failure_summary(tmp_path, "llamaindex")


def test_pageindex_ready_requires_doc_ids(tmp_path: Path) -> None:
    version_dir = tmp_path / "version-1"
    version_dir.mkdir()
    _write_meta(version_dir, provider="pageindex")

    probe = inspect_provider_index("pageindex", version_dir)
    assert probe.ready is False

    manifest = pageindex_storage.read_manifest(version_dir)
    pageindex_storage.upsert_doc(manifest, "lesson.pdf", "doc-123")
    pageindex_storage.write_manifest(version_dir, manifest)

    probe = inspect_provider_index("pageindex", version_dir)
    assert probe.ready is True
    assert probe.doc_count == 1


def test_pageindex_oss_requires_local_sdk_artifacts(tmp_path: Path) -> None:
    version_dir = tmp_path / "version-1"
    version_dir.mkdir()
    _write_meta(version_dir, provider="pageindex-oss")
    manifest = pageindex_storage.read_manifest(version_dir, provider="pageindex-oss")
    pageindex_storage.upsert_doc(manifest, "lesson.pdf", "pi-local")
    pageindex_storage.write_manifest(version_dir, manifest)

    probe = inspect_provider_index("pageindex-oss", version_dir)
    assert probe.ready is False

    doc_dir = pageindex_storage.sdk_storage_path(version_dir) / "docs" / "pi-local"
    doc_dir.mkdir(parents=True)
    for name in ("doc.json", "tree.json", "pages.json"):
        (doc_dir / name).write_text("{}", encoding="utf-8")

    probe = inspect_provider_index("pageindex-oss", version_dir)
    assert probe.ready is True
    assert probe.doc_count == 1


def test_graphrag_ready_requires_core_output_table(tmp_path: Path) -> None:
    version_dir = tmp_path / "version-1"
    version_dir.mkdir()
    _write_meta(version_dir, provider="graphrag")

    probe = inspect_provider_index("graphrag", version_dir)
    assert probe.ready is False
    assert "parquet" in probe.failure_summary

    out = graphrag_storage.output_dir(version_dir)
    out.mkdir()
    (out / "entities.parquet").write_bytes(b"placeholder")

    probe = inspect_provider_index("graphrag", version_dir)
    assert probe.ready is True
    assert probe.diagnostics["output_tables"] == ["entities"]


def test_lightrag_uses_doc_status_as_truth(tmp_path: Path) -> None:
    version_dir = tmp_path / "version-1"
    version_dir.mkdir()
    _write_meta(version_dir, provider="lightrag")
    (version_dir / "kv_store_doc_status.json").write_text(
        json.dumps(
            {
                "doc-1": {
                    "status": "failed",
                    "file_path": "bad.docx",
                    "error_msg": "parse failed",
                    "chunks_list": [],
                }
            }
        ),
        encoding="utf-8",
    )

    probe = inspect_provider_index("lightrag", version_dir)
    assert probe.ready is False
    assert "bad.docx" in probe.failure_summary

    (version_dir / "kv_store_doc_status.json").write_text(
        json.dumps(
            {
                "doc-1": {
                    "status": "processed",
                    "file_path": "ok.docx",
                    "chunks_list": ["chunk-1"],
                }
            }
        ),
        encoding="utf-8",
    )
    probe = inspect_provider_index("lightrag", version_dir)
    assert probe.ready is True
    assert probe.doc_count == 1


def test_provider_mismatch_is_not_ready(tmp_path: Path) -> None:
    version_dir = tmp_path / "version-1"
    version_dir.mkdir()
    _write_meta(version_dir, provider="lightrag")
    entry = {
        "provider": "lightrag",
        "signature": "lightrag",
        "ready": True,
        "storage_path": str(version_dir),
    }

    probe = inspect_provider_version(entry, "llamaindex")

    assert probe.ready is False
    assert probe.diagnostics["provider_mismatch"] is True


def test_llamaindex_doc_count_cached_until_file_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated probes must not re-parse docstore.json (issue #859)."""
    from deeptutor.services.rag.index_probe import _read_json

    docstore = tmp_path / "docstore.json"
    docstore.write_text(
        json.dumps({"docstore/data": {"doc-1": {}, "doc-2": {}}}),
        encoding="utf-8",
    )

    real_read = _read_json
    reads: list[str] = []

    def counting_read(path: Path) -> dict[str, Any] | None:
        reads.append(str(path))
        return real_read(path)

    monkeypatch.setattr("deeptutor.services.rag.index_probe._read_json", counting_read)

    assert _llamaindex_doc_count(docstore) == 2
    # Second probe on an unchanged file must be served from the cache.
    assert _llamaindex_doc_count(docstore) == 2
    assert reads == [str(docstore)]

    # A real file change must invalidate the cache entry.
    docstore.write_text(
        json.dumps({"docstore/data": {"doc-1": {}}}),
        encoding="utf-8",
    )
    assert _llamaindex_doc_count(docstore) == 1
    assert reads == [str(docstore), str(docstore)]


def test_llamaindex_doc_count_missing_file_is_not_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing docstore must not poison the cache for a later-created file."""
    from deeptutor.services.rag.index_probe import _read_json

    docstore = tmp_path / "docstore.json"

    real_read = _read_json
    reads: list[str] = []

    def counting_read(path: Path) -> dict[str, Any] | None:
        reads.append(str(path))
        return real_read(path)

    monkeypatch.setattr("deeptutor.services.rag.index_probe._read_json", counting_read)

    assert _llamaindex_doc_count(docstore) is None
    # A missing docstore short-circuits on stat() — no parse is attempted, and
    # no cache entry is created that could shadow a later-created file.
    assert reads == []
    docstore.write_text(
        json.dumps({"docstore/data": {"doc-1": {}}}),
        encoding="utf-8",
    )
    assert _llamaindex_doc_count(docstore) == 1
    assert reads == [str(docstore)]


def test_provider_failure_summary_reuses_precomputed_versions(tmp_path: Path) -> None:
    """Pre-annotated versions must not trigger another on-disk scan (#859)."""
    versions = [
        {"storage_path": str(tmp_path / "version-1"), "ready": True},
        {
            "storage_path": str(tmp_path / "version-2"),
            "ready": False,
            "failure_summary": "Missing LlamaIndex docstore.json.",
        },
    ]
    # Nothing exists on disk under tmp_path; the precomputed list is the only
    # source of failure text and must be honored without a rescan.
    assert provider_failure_summary(tmp_path, "llamaindex", versions=versions) == (
        "Missing LlamaIndex docstore.json."
    )


def test_inspect_provider_index_without_storage_path_is_not_ready() -> None:
    probe = inspect_provider_index("llamaindex", None)

    assert probe.ready is False
    assert probe.storage_dir is None
    assert "No storage path" in probe.failure_summary


def test_inspect_provider_index_normalizes_unknown_provider_to_default(
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "docstore.json").write_text("{}", encoding="utf-8")
    (storage / "index_store.json").write_text("{}", encoding="utf-8")

    probe = inspect_provider_index("mystery-engine", storage)

    assert probe.provider == "llamaindex"
    assert probe.ready is True


def test_inspect_provider_index_missing_dir_is_not_ready(tmp_path: Path) -> None:
    probe = inspect_provider_index("llamaindex", tmp_path / "absent")

    assert probe.ready is False
    assert "does not exist" in probe.failure_summary
    assert probe.doc_count is None


def test_llamaindex_building_marker_requires_verified_publication(tmp_path: Path) -> None:
    version_dir = tmp_path / "version-1"
    version_dir.mkdir()
    for name in ("docstore.json", "index_store.json"):
        (version_dir / name).write_text("{}", encoding="utf-8")
    (version_dir / ".building.json").write_text("{}", encoding="utf-8")

    probe = inspect_provider_index("llamaindex", version_dir)
    assert probe.ready is False
    assert "persistence verification" in probe.failure_summary

    (version_dir / "meta.json").write_text(
        json.dumps({"state": "published", "readiness_verified": True}),
        encoding="utf-8",
    )
    assert inspect_provider_index("llamaindex", version_dir).ready is True


def test_llamaindex_missing_docstore_is_not_ready(tmp_path: Path) -> None:
    version_dir = tmp_path / "version-1"
    version_dir.mkdir()
    (version_dir / "index_store.json").write_text("{}", encoding="utf-8")

    probe = inspect_provider_index("llamaindex", version_dir)

    assert probe.ready is False
    assert "docstore.json" in probe.failure_summary


def test_llamaindex_doc_count_rejects_malformed_docstore(tmp_path: Path) -> None:
    docstore = tmp_path / "docstore.json"

    docstore.write_text("not json", encoding="utf-8")
    assert _llamaindex_doc_count(docstore) is None

    docstore.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    assert _llamaindex_doc_count(docstore) is None

    docstore.write_text(
        json.dumps({"docstore/data": ["still", "a", "list"]}),
        encoding="utf-8",
    )
    assert _llamaindex_doc_count(docstore) is None


def test_inspect_provider_version_probes_matching_entry(tmp_path: Path) -> None:
    version_dir = tmp_path / "version-1"
    version_dir.mkdir()
    (version_dir / "docstore.json").write_text(
        json.dumps({"docstore/data": {"d1": {}, "d2": {}}}),
        encoding="utf-8",
    )
    (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    entry = {
        "provider": "llamaindex",
        "signature": "sig-1",
        "storage_path": str(version_dir),
    }

    probe = inspect_provider_version(entry, "llamaindex")
    assert probe.ready is True
    assert probe.doc_count == 2

    probe = inspect_provider_version({"provider": "llamaindex"}, "llamaindex")
    assert probe.ready is False
    assert probe.storage_dir is None
    assert "No storage path" in probe.failure_summary


def test_inspect_kb_versions_carries_probe_diagnostics_and_doc_count(
    tmp_path: Path,
) -> None:
    ready_dir = tmp_path / "version-1"
    ready_dir.mkdir()
    (ready_dir / "docstore.json").write_text(
        json.dumps({"docstore/data": {"d1": {}}}),
        encoding="utf-8",
    )
    (ready_dir / "index_store.json").write_text("{}", encoding="utf-8")
    _write_meta(ready_dir, provider="llamaindex", signature="sig-1")
    broken_dir = tmp_path / "version-2"
    broken_dir.mkdir()
    _write_meta(broken_dir, provider="llamaindex", signature="sig-2")

    versions = inspect_kb_versions(tmp_path, "llamaindex")

    assert [entry["version"] for entry in versions] == ["version-2", "version-1"]
    broken, ready = versions
    assert broken["ready"] is False
    assert "docstore.json" in broken["failure_summary"]
    assert ready["ready"] is True
    assert ready["doc_count"] == 1
    assert ready["probe_diagnostics"]["vector_stores"] == []


def test_latest_ready_provider_version_skips_unready_newer_versions(
    tmp_path: Path,
) -> None:
    stale = tmp_path / "version-1"
    stale.mkdir()
    for name in ("docstore.json", "index_store.json"):
        (stale / name).write_text("{}", encoding="utf-8")
    _write_meta(stale, provider="llamaindex", signature="sig-1")
    broken = tmp_path / "version-2"
    broken.mkdir()
    _write_meta(broken, provider="llamaindex", signature="sig-2")

    latest = latest_ready_provider_version(tmp_path, "llamaindex")
    assert latest is not None
    assert latest["version"] == "version-1"
    assert has_ready_provider_index(tmp_path, "llamaindex") is True

    assert latest_ready_provider_version(tmp_path / "empty", "llamaindex") is None


def test_provider_failure_summary_joins_and_respects_limit(tmp_path: Path) -> None:
    for n in (1, 2, 3):
        version_dir = tmp_path / f"version-{n}"
        version_dir.mkdir()
        _write_meta(version_dir, provider="llamaindex", signature=f"sig-{n}")

    versions = inspect_kb_versions(tmp_path, "llamaindex")
    assert len(versions) == 3

    full = provider_failure_summary(tmp_path, "llamaindex", versions=versions)
    assert full.count("Missing LlamaIndex docstore.json.") == 3
    assert full.count("; ") == 2

    limited = provider_failure_summary(tmp_path, "llamaindex", versions=versions, limit=2)
    assert limited.count("Missing LlamaIndex docstore.json.") == 2
    assert limited.count("; ") == 1


def test_lightrag_doc_count_counts_only_usable_rows(tmp_path: Path) -> None:
    (tmp_path / "kv_store_doc_status.json").write_text(
        json.dumps(
            {
                "doc-1": {"status": "done"},
                "doc-2": {"status": "pending", "chunks_list": ["c1"]},
                "doc-3": {"status": "pending"},
                "doc-4": "not-a-row",
                "doc-5": {"status": "indexed"},
            }
        ),
        encoding="utf-8",
    )

    assert _lightrag_doc_count(tmp_path) == 3


def test_read_json_returns_none_for_malformed_or_non_dict_payloads(
    tmp_path: Path,
) -> None:
    from deeptutor.services.rag.index_probe import _read_json

    assert _read_json(tmp_path / "absent.json") is None

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert _read_json(bad) is None

    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    assert _read_json(array) is None

    good = tmp_path / "good.json"
    good.write_text('{"ok": true}', encoding="utf-8")
    assert _read_json(good) == {"ok": True}
