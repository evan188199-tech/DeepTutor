from __future__ import annotations

import hashlib
import json
from pathlib import Path

from deeptutor.services.rag.index_versioning import (
    EmbeddingSignature,
    find_matching_version,
    list_kb_versions,
    read_version_meta,
    resolve_storage_dir_for_read,
    resolve_storage_dir_for_rebuild,
    resolve_storage_dir_for_write,
    storage_dir_for_signature,
    version_dir_for_signature,
    write_version_meta,
)


def _signature(model: str = "embed-a", dim: int = 1024) -> EmbeddingSignature:
    return EmbeddingSignature(
        binding="openai",
        model=model,
        dimension=dim,
        base_url="https://example.test/v1",
        api_version="",
    )


def test_legacy_role_naive_signature_hash_is_stable() -> None:
    fields = {
        "api_version": "",
        "base_url": "https://api.openai.com/v1/embeddings",
        "binding": "openai",
        "dimension": 1536,
        "model": "text-embedding-3-small",
    }
    signature = EmbeddingSignature(
        binding=fields["binding"],
        model=fields["model"],
        dimension=fields["dimension"],
        base_url=fields["base_url"],
        api_version="",
    )
    expected_hash = hashlib.sha256(
        json.dumps(fields, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]

    assert signature.hash() == expected_hash
    assert signature.role_semantics == ""


def test_jina_role_semantics_changes_signature() -> None:
    from types import SimpleNamespace

    from deeptutor.services.rag.embedding_signature import signature_from_config

    config = SimpleNamespace(
        binding="jina",
        model="jina-embeddings-v3",
        dim=1024,
        base_url="https://api.jina.ai/v1/embeddings",
        effective_url="https://api.jina.ai/v1/embeddings",
        api_version="",
    )
    legacy_signature = EmbeddingSignature(
        binding="jina",
        model="jina-embeddings-v3",
        dimension=1024,
        base_url="https://api.jina.ai/v1/embeddings",
        api_version="",
    )
    active_signature = signature_from_config(config)

    assert active_signature.role_semantics == "jina-task"
    assert active_signature.hash() != legacy_signature.hash()


def test_resolve_storage_dir_for_write_allocates_flat_version_dirs(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    sig = _signature()

    storage_dir = resolve_storage_dir_for_write(kb_dir, sig)
    (storage_dir / "docstore.json").write_text("{}", encoding="utf-8")
    write_version_meta(kb_dir, sig, storage_dir=storage_dir)

    assert storage_dir == kb_dir / "version-1"
    assert (storage_dir / "meta.json").exists()
    assert not (kb_dir / "index_versions").exists()
    assert not (kb_dir / "llamaindex_storage").exists()


def test_resolve_storage_dir_for_write_reuses_matching_flat_version(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    sig = _signature()
    version_dir = kb_dir / "version-3"
    version_dir.mkdir(parents=True)
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"signature": sig.hash(), "version": "version-3"}),
        encoding="utf-8",
    )

    assert resolve_storage_dir_for_write(kb_dir, sig) == version_dir


def test_resolve_storage_dir_for_rebuild_allocates_fresh_version(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    sig = _signature()
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True)
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"signature": sig.hash(), "version": "version-1"}),
        encoding="utf-8",
    )

    assert resolve_storage_dir_for_rebuild(kb_dir, sig) == kb_dir / "version-2"


def test_resolve_storage_dir_for_write_without_signature_still_uses_flat_layout(
    tmp_path: Path,
) -> None:
    kb_dir = tmp_path / "kb"

    storage_dir = resolve_storage_dir_for_write(kb_dir, None)

    assert storage_dir == kb_dir / "version-1"
    assert not (kb_dir / "llamaindex_storage").exists()
    assert not (kb_dir / "index_versions").exists()


def test_resolve_storage_dir_for_read_without_signature_prefers_latest_flat_version(
    tmp_path: Path,
) -> None:
    kb_dir = tmp_path / "kb"
    for version in ("version-1", "version-2"):
        version_dir = kb_dir / version
        version_dir.mkdir(parents=True, exist_ok=True)
        (version_dir / "docstore.json").write_text("{}", encoding="utf-8")

    assert resolve_storage_dir_for_read(kb_dir, None) == kb_dir / "version-2"


def test_read_prefers_flat_version_over_legacy_nested_with_same_signature(
    tmp_path: Path,
) -> None:
    kb_dir = tmp_path / "kb"
    sig = _signature()
    flat = kb_dir / "version-1"
    flat.mkdir(parents=True)
    (flat / "docstore.json").write_text("{}", encoding="utf-8")
    (flat / "meta.json").write_text(
        json.dumps({"signature": sig.hash(), "version": "version-1"}),
        encoding="utf-8",
    )
    legacy = kb_dir / "index_versions" / sig.hash()
    legacy_storage = legacy / "llamaindex_storage"
    legacy_storage.mkdir(parents=True)
    (legacy_storage / "docstore.json").write_text("{}", encoding="utf-8")
    (legacy / "meta.json").write_text(
        json.dumps({"signature": sig.hash()}),
        encoding="utf-8",
    )

    assert resolve_storage_dir_for_read(kb_dir, sig) == flat
    assert find_matching_version(kb_dir, sig)["layout"] == "flat"


def test_list_kb_versions_includes_legacy_nested_and_root_layouts(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    sig = _signature()
    nested = kb_dir / "index_versions" / sig.hash()
    nested_storage = nested / "llamaindex_storage"
    nested_storage.mkdir(parents=True)
    (nested_storage / "docstore.json").write_text("{}", encoding="utf-8")
    (nested / "meta.json").write_text(json.dumps({"signature": sig.hash()}), encoding="utf-8")
    root_storage = kb_dir / "llamaindex_storage"
    root_storage.mkdir(parents=True)
    (root_storage / "docstore.json").write_text("{}", encoding="utf-8")

    layouts = {entry["layout"] for entry in list_kb_versions(kb_dir)}

    assert {"nested_legacy", "root_legacy"} <= layouts


def test_list_kb_versions_ignores_non_version_entries_and_sorts_newest_first(
    tmp_path: Path,
) -> None:
    kb_dir = tmp_path / "kb"
    for name in ("version-1", "version-2"):
        version_dir = kb_dir / name
        version_dir.mkdir(parents=True)
        (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (kb_dir / "version-not-a-number").mkdir(parents=True)
    (kb_dir / "notes.txt").write_text("x", encoding="utf-8")

    entries = list_kb_versions(kb_dir)

    assert [entry["version"] for entry in entries] == ["version-2", "version-1"]


def test_flat_version_without_meta_defaults_identity_fields(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True)
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")

    entry = list_kb_versions(kb_dir)[0]

    assert entry["version"] == "version-1"
    assert entry["signature"] == "version-1"
    assert entry["ready"] is True
    assert entry["layout"] == "flat"


def test_flat_version_with_malformed_meta_still_lists_output(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True)
    (version_dir / "meta.json").write_text("{broken", encoding="utf-8")
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")

    entry = list_kb_versions(kb_dir)[0]

    assert entry["signature"] == "version-1"
    assert entry["version"] == "version-1"
    assert entry["ready"] is True


def test_storage_with_only_meta_json_is_not_ready(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True)
    (version_dir / "meta.json").write_text("{}", encoding="utf-8")

    assert list_kb_versions(kb_dir)[0]["ready"] is False


def test_unpublished_lightrag_candidate_is_not_ready(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True)
    (version_dir / "kv_store_doc_status.json").write_text("{}", encoding="utf-8")
    (version_dir / "vdb_entities.json").write_text("{}", encoding="utf-8")

    assert list_kb_versions(kb_dir)[0]["ready"] is False


def test_building_flat_version_without_published_meta_is_not_ready(
    tmp_path: Path,
) -> None:
    kb_dir = tmp_path / "kb"
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True)
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / ".building.json").write_text("{}", encoding="utf-8")

    assert list_kb_versions(kb_dir)[0]["ready"] is False


def test_lightrag_schema2_publication_gate(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True)

    def write_meta(**overrides: object) -> None:
        payload: dict[str, object] = {
            "provider": "lightrag",
            "state": "published",
            "lightrag_adapter_schema": 2,
        }
        payload.update(overrides)
        (version_dir / "meta.json").write_text(json.dumps(payload), encoding="utf-8")

    write_meta(workspace="ws")
    assert list_kb_versions(kb_dir)[0]["ready"] is False

    workspace = version_dir / "ws"
    workspace.mkdir()
    (workspace / "kv_store_doc_status.json").write_text(
        json.dumps({"doc-1": {"status": "processed"}}),
        encoding="utf-8",
    )
    assert list_kb_versions(kb_dir)[0]["ready"] is True

    write_meta(workspace="ws", state="building")
    assert list_kb_versions(kb_dir)[0]["ready"] is False

    write_meta(workspace="ws", lightrag_adapter_schema=1)
    assert list_kb_versions(kb_dir)[0]["ready"] is False

    write_meta(workspace="/etc/passwd")
    assert list_kb_versions(kb_dir)[0]["ready"] is False

    write_meta(workspace="nested/dir")
    assert list_kb_versions(kb_dir)[0]["ready"] is False


def test_lightrag_schema2_accepts_transitional_flat_status_store(
    tmp_path: Path,
) -> None:
    kb_dir = tmp_path / "kb"
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True)
    (version_dir / "meta.json").write_text(
        json.dumps(
            {
                "provider": "lightrag",
                "state": "published",
                "lightrag_adapter_schema": 2,
            }
        ),
        encoding="utf-8",
    )
    (version_dir / "kv_store_doc_status.json").write_text(
        json.dumps({"doc-1": {"chunks_list": ["c1"]}}),
        encoding="utf-8",
    )

    assert list_kb_versions(kb_dir)[0]["ready"] is True


def test_legacy_nested_entry_without_meta_defaults_signature(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    legacy_storage = kb_dir / "index_versions" / "deadbeef" / "llamaindex_storage"
    legacy_storage.mkdir(parents=True)
    (legacy_storage / "docstore.json").write_text("{}", encoding="utf-8")

    entry = list_kb_versions(kb_dir)[0]

    assert entry["signature"] == "deadbeef"
    assert entry["legacy"] is True
    assert entry["ready"] is True
    assert entry["kb_path"] == str(kb_dir)


def test_root_legacy_entry_requires_content(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    root_storage = kb_dir / "llamaindex_storage"
    root_storage.mkdir(parents=True)

    assert list_kb_versions(kb_dir) == []

    (root_storage / "docstore.json").write_text("{}", encoding="utf-8")
    entries = list_kb_versions(kb_dir)

    assert len(entries) == 1
    assert entries[0]["layout"] == "root_legacy"
    assert entries[0]["ready"] is True


def test_next_flat_version_allocates_after_highest_number(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    for name in ("version-1", "version-3"):
        version_dir = kb_dir / name
        version_dir.mkdir(parents=True)
        (version_dir / "docstore.json").write_text("{}", encoding="utf-8")

    assert resolve_storage_dir_for_write(kb_dir, None) == kb_dir / "version-4"


def test_version_dir_for_signature_reuses_match_or_allocates_next(
    tmp_path: Path,
) -> None:
    kb_dir = tmp_path / "kb"
    sig = _signature()
    version_dir = kb_dir / "version-2"
    version_dir.mkdir(parents=True)
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"signature": sig.hash()}),
        encoding="utf-8",
    )

    assert version_dir_for_signature(kb_dir, sig.hash()) == version_dir
    assert version_dir_for_signature(kb_dir, "missing-sig") == kb_dir / "version-3"


def test_storage_dir_for_signature_spans_layouts(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    flat = kb_dir / "version-1"
    flat.mkdir(parents=True)
    (flat / "docstore.json").write_text("{}", encoding="utf-8")
    (flat / "meta.json").write_text(
        json.dumps({"signature": "flat-sig"}),
        encoding="utf-8",
    )
    legacy = kb_dir / "index_versions" / "legacy-sig" / "llamaindex_storage"
    legacy.mkdir(parents=True)
    (legacy / "docstore.json").write_text("{}", encoding="utf-8")

    assert storage_dir_for_signature(kb_dir, "flat-sig") == flat
    assert storage_dir_for_signature(kb_dir, "legacy-sig") == legacy
    assert storage_dir_for_signature(kb_dir, "absent") == kb_dir / "version-2"


def test_read_version_meta_across_layouts(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    nested = kb_dir / "index_versions" / "legacy-sig"
    legacy_storage = nested / "llamaindex_storage"
    legacy_storage.mkdir(parents=True)
    (legacy_storage / "docstore.json").write_text("{}", encoding="utf-8")
    (nested / "meta.json").write_text(
        json.dumps({"signature": "legacy-sig"}),
        encoding="utf-8",
    )

    entry = read_version_meta(kb_dir, "legacy-sig")
    assert entry is not None
    assert entry["layout"] == "nested_legacy"
    assert read_version_meta(kb_dir, "absent") is None


def test_find_matching_version_ignores_unready_versions(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    sig = _signature()
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True)
    (version_dir / "meta.json").write_text(
        json.dumps({"signature": sig.hash()}),
        encoding="utf-8",
    )

    assert find_matching_version(kb_dir, sig) is None

    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    match = find_matching_version(kb_dir, sig)

    assert match is not None
    assert match["storage_path"] == str(version_dir)


def test_resolve_storage_dir_for_read_falls_back_to_root_legacy(
    tmp_path: Path,
) -> None:
    kb_dir = tmp_path / "kb"
    sig = _signature()
    root_storage = kb_dir / "llamaindex_storage"
    root_storage.mkdir(parents=True)
    (root_storage / "docstore.json").write_text("{}", encoding="utf-8")

    assert resolve_storage_dir_for_read(kb_dir, sig) == root_storage
    assert resolve_storage_dir_for_read(kb_dir, None) == root_storage
    assert resolve_storage_dir_for_read(tmp_path / "empty-kb", None) is None


def test_write_version_meta_publishes_building_candidate(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    sig = _signature()
    target = resolve_storage_dir_for_write(kb_dir, sig)
    (target / ".building.json").write_text("{}", encoding="utf-8")

    write_version_meta(kb_dir, sig, storage_dir=target)

    payload = json.loads((target / "meta.json").read_text(encoding="utf-8"))
    assert payload["provider"] == "llamaindex"
    assert payload["state"] == "published"
    assert payload["readiness_verified"] is True
    assert payload["signature"] == sig.hash()
    assert payload["layout"] == "flat"


def test_resolve_storage_dir_for_rebuild_guard_creates_building_marker(
    tmp_path: Path,
) -> None:
    kb_dir = tmp_path / "kb"
    sig = _signature()

    first = resolve_storage_dir_for_rebuild(kb_dir, sig, publication_guard=True)
    assert first == kb_dir / "version-1"
    assert (first / ".building.json").is_file()

    second = resolve_storage_dir_for_rebuild(kb_dir, sig, publication_guard=True)
    assert second == kb_dir / "version-2"
    assert (second / ".building.json").is_file()

    third = resolve_storage_dir_for_rebuild(kb_dir, sig)
    assert third == kb_dir / "version-3"
    assert not (third / ".building.json").exists()
