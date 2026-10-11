"""Unit tests for the PageIndex on-disk manifest.

Covers read/write round-trips, normalization of damaged manifests, and the
failure branches that must degrade to an empty manifest instead of raising.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.services.rag.pipelines.pageindex import storage


def test_manifest_round_trip(tmp_path: Path) -> None:
    manifest = {"provider": storage.CLOUD_PROVIDER, "docs": {}}
    storage.upsert_doc(manifest, "a.pdf", "pi-1", size=10)

    storage.write_manifest(tmp_path, manifest)
    loaded = storage.read_manifest(tmp_path)

    assert storage.manifest_path(tmp_path).name == "pageindex_docs.json"
    assert loaded["provider"] == storage.CLOUD_PROVIDER
    assert loaded["docs"]["a.pdf"]["doc_id"] == "pi-1"
    assert loaded["docs"]["a.pdf"]["size"] == 10
    assert loaded["docs"]["a.pdf"]["submitted_at"]


def test_read_manifest_without_storage_or_file(tmp_path: Path) -> None:
    empty = {"provider": storage.CLOUD_PROVIDER, "docs": {}}
    assert storage.read_manifest(None) == empty
    assert storage.read_manifest(tmp_path / "missing-kb") == empty


def test_read_manifest_corrupt_json_degrades_to_empty(tmp_path: Path) -> None:
    storage.manifest_path(tmp_path).write_text("{not json", encoding="utf-8")

    assert storage.read_manifest(tmp_path) == {"provider": storage.CLOUD_PROVIDER, "docs": {}}


def test_read_manifest_non_dict_payload_degrades_to_empty(tmp_path: Path) -> None:
    storage.manifest_path(tmp_path).write_text("[1, 2]", encoding="utf-8")

    assert storage.read_manifest(tmp_path) == {"provider": storage.CLOUD_PROVIDER, "docs": {}}


def test_read_manifest_repairs_non_dict_docs(tmp_path: Path) -> None:
    storage.manifest_path(tmp_path).write_text(json.dumps({"docs": "nope"}), encoding="utf-8")

    assert storage.read_manifest(tmp_path) == {"provider": storage.CLOUD_PROVIDER, "docs": {}}


def test_read_manifest_provider_precedence(tmp_path: Path) -> None:
    path = storage.manifest_path(tmp_path)
    path.write_text(
        json.dumps({"provider": storage.OSS_PROVIDER, "docs": {}}), encoding="utf-8"
    )
    assert (
        storage.read_manifest(tmp_path, provider=storage.CLOUD_PROVIDER)["provider"]
        == storage.OSS_PROVIDER
    )

    path.write_text(json.dumps({"docs": {}}), encoding="utf-8")
    assert (
        storage.read_manifest(tmp_path, provider=storage.OSS_PROVIDER)["provider"]
        == storage.OSS_PROVIDER
    )


def test_write_failure_propagates(tmp_path: Path) -> None:
    (tmp_path / storage.MANIFEST_FILENAME).mkdir()

    with pytest.raises(OSError):
        storage.write_manifest(tmp_path, {"provider": storage.CLOUD_PROVIDER, "docs": {}})


def test_write_meta_marks_flat_version_ready(tmp_path: Path) -> None:
    version_dir = tmp_path / "version-3"
    version_dir.mkdir()

    storage.write_meta(version_dir, provider=storage.OSS_PROVIDER)

    payload = json.loads((version_dir / storage.META_FILENAME).read_text(encoding="utf-8"))
    assert payload["version"] == "version-3"
    assert payload["signature"] == storage.OSS_PROVIDER
    assert payload["provider"] == storage.OSS_PROVIDER
    assert payload["layout"] == "flat"
    assert payload["created_at"].endswith("Z")


def test_doc_ids_skips_malformed_entries() -> None:
    manifest = {
        "docs": {
            "a.pdf": {"doc_id": "pi-1"},
            "b.pdf": {"size": 1},
            "c.pdf": "not-a-dict",
        }
    }
    assert storage.doc_ids(manifest) == ["pi-1"]


def test_doc_entries_defaults_for_non_dict_docs() -> None:
    assert storage.doc_entries({}) == {}
    assert storage.doc_entries({"docs": [1]}) == {}


def test_upsert_and_remove_round_trip() -> None:
    manifest: dict = {}

    storage.upsert_doc(manifest, "a.pdf", "pi-1")

    entry = storage.remove_doc(manifest, "a.pdf")
    assert entry is not None and entry["doc_id"] == "pi-1"
    assert storage.doc_entries(manifest) == {}
    assert storage.remove_doc(manifest, "missing") is None


def test_sdk_storage_path(tmp_path: Path) -> None:
    assert storage.sdk_storage_path(tmp_path) == tmp_path / "pageindex"
