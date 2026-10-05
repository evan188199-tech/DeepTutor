"""Failure/degradation branches of the embedding binding layer.

Complements ``test_embedding_binding.py``: binding-status edge cases,
migration ambiguity, reconcile tolerance, decorator failure paths and
bound-graph version gating.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.services.embedding.config import (
    embedding_config_scope,
    get_embedding_config,
    scoped_embedding_config,
)
from deeptutor.services.rag import embedding_binding as binding
from deeptutor.services.rag.embedding_signature import signature_from_config
from deeptutor.services.rag.service import RAGService


@pytest.fixture
def catalog(monkeypatch):
    value = {
        "version": 1,
        "services": {
            "embedding": {
                "active_profile_id": "p",
                "active_model_id": "a",
                "profiles": [
                    {
                        "id": "p",
                        "name": "Provider",
                        "binding": "openai",
                        "api_key": "original-key",
                        "base_url": "https://example.test/v1/embeddings",
                        "models": [
                            {"id": "a", "model": "embed-a", "dimension": "2"},
                            {"id": "b", "model": "embed-b", "dimension": "3"},
                        ],
                    }
                ],
            }
        },
    }
    from deeptutor.services import config
    from deeptutor.services.config import provider_runtime

    monkeypatch.setattr(
        config, "get_model_catalog_service", lambda: SimpleNamespace(load=lambda: deepcopy(value))
    )
    monkeypatch.setattr(binding, "load_catalog", lambda: deepcopy(value))
    monkeypatch.setattr(
        provider_runtime,
        "_load_catalog",
        lambda supplied: supplied if supplied is not None else deepcopy(value),
    )
    return value


def selection(model="a"):
    return {"profile_id": "p", "model_id": model}


def write_entry(root: Path, name="kb", model="a", **overrides):
    config = get_embedding_config(selection(model))
    entry = {
        "path": name,
        "rag_provider": "llamaindex",
        "status": "ready",
        **binding.binding_fields(selection(model), config),
        **overrides,
    }
    path = root / "kb_config.json"
    payload = json.loads(path.read_text()) if path.exists() else {"knowledge_bases": {}}
    payload["knowledge_bases"][name] = entry
    path.write_text(json.dumps(payload))
    (root / name / "raw").mkdir(parents=True, exist_ok=True)
    return entry


def read_entry(root, name="kb"):
    return json.loads((root / "kb_config.json").read_text())["knowledge_bases"][name]


def test_default_selection_and_binding_status_states(catalog, tmp_path):
    bare = deepcopy(catalog)
    bare["services"]["embedding"].pop("active_profile_id")
    bare["services"]["embedding"].pop("active_model_id")
    assert binding.default_selection(bare) is None
    assert binding.default_selection(catalog) == selection()

    assert binding.binding_status({"rag_provider": "llamaindex"}, catalog=catalog)[0] == "legacy"

    corrupt = {"embedding_selection": "corrupt", "rag_provider": "llamaindex"}
    assert binding.binding_status(corrupt, catalog=catalog)[0] == "missing"

    unknown_profile = {
        "embedding_selection": {"profile_id": "ghost", "model_id": "a"},
        "rag_provider": "llamaindex",
    }
    assert binding.binding_status(unknown_profile, catalog=catalog)[0] == "missing"

    entry = write_entry(tmp_path)
    keyless = deepcopy(catalog)
    keyless["services"]["embedding"]["profiles"][0].pop("api_key")
    assert binding.binding_status(entry, catalog=keyless)[0] == "unconfigured"

    assert binding.binding_status(entry, catalog=catalog) == (
        "ready",
        get_embedding_config(selection("a")),
    )


def test_entry_signature_falls_back_to_active_and_flags_unresolved(catalog, tmp_path):
    cfg = get_embedding_config(selection("a"))
    legacy = {"rag_provider": "llamaindex"}
    with embedding_config_scope(cfg):
        assert binding.entry_signature(legacy) == signature_from_config(cfg)

    bound = write_entry(tmp_path)
    catalog["services"]["embedding"]["profiles"][0]["models"].pop(0)
    assert binding.entry_signature(bound) is None


def test_load_catalog_reads_model_catalog_service(monkeypatch):
    from deeptutor.services import config

    marker = {"services": {"embedding": {}}}
    monkeypatch.setattr(
        config, "get_model_catalog_service", lambda: SimpleNamespace(load=lambda: marker)
    )
    assert binding.load_catalog() is marker


def test_migrate_binding_skips_unresolvable_profile_and_pins_recorded_identity(catalog, tmp_path):
    catalog["services"]["embedding"]["profiles"].append(
        {
            "id": "q2",
            "name": "Broken",
            "binding": "openai",
            "base_url": "https://broken.test/v1/embeddings",
            "models": [{"id": "x", "model": "embed-x", "dimension": "2"}],
        }
    )
    entry = write_entry(tmp_path)
    entry.pop("embedding_selection")
    assert binding.migrate_binding(entry, tmp_path / "kb") is True
    assert entry["embedding_selection"] == selection("a")
    assert entry["embedding_status"] == "ready"


def test_migrate_binding_leaves_ambiguous_matches_unresolved(catalog, tmp_path):
    catalog["services"]["embedding"]["profiles"].append(
        {
            "id": "q",
            "name": "Mirror",
            "binding": "openai",
            "api_key": "q-key",
            "base_url": "https://mirror.test/v1/embeddings",
            "models": [{"id": "qa", "model": "embed-a", "dimension": "2"}],
        }
    )
    entry = write_entry(tmp_path)
    entry.pop("embedding_selection")
    entry.pop("embedding_signature")
    before = dict(entry)
    assert binding.migrate_binding(entry, tmp_path / "kb") is False
    assert entry == before


def test_reconcile_bindings_survives_catalog_failure_and_skips_unbound(
    catalog, tmp_path, monkeypatch
):
    def broken_catalog():
        raise ValueError("catalog unavailable")

    monkeypatch.setattr(binding, "load_catalog", broken_catalog)
    entries = {"kb": {"rag_provider": "llamaindex"}}
    assert binding.reconcile_bindings(entries, tmp_path) is False
    assert entries == {"kb": {"rag_provider": "llamaindex"}}

    entries = {
        "junk": "not-a-dict",
        "linked": {"type": "linked", "rag_provider": "lightrag"},
        "plain": {"rag_provider": "llamaindex", "path": "plain"},
    }
    assert binding.reconcile_bindings(entries, tmp_path) is False
    assert "index_versions" not in entries["plain"]


def test_search_reports_unconfigured_and_changed_bindings(catalog, tmp_path, monkeypatch):
    seen = []

    class Pipeline:
        async def search(self, query, kb_name, **kwargs):
            seen.append(get_embedding_config().model)
            return {"answer": seen[-1]}

    write_entry(tmp_path)
    service = RAGService(kb_base_dir=str(tmp_path))
    service._pipelines["llamaindex"] = Pipeline()

    keyless = deepcopy(catalog)
    keyless["services"]["embedding"]["profiles"][0].pop("api_key")
    monkeypatch.setattr(binding, "load_catalog", lambda: deepcopy(keyless))
    result = asyncio.run(service.search("q", "kb"))
    assert result["error_type"] == "embedding_binding_unavailable"
    assert "not configured" in result["answer"]

    monkeypatch.setattr(binding, "load_catalog", lambda: deepcopy(catalog))
    catalog["services"]["embedding"]["profiles"][0]["models"][0]["model"] = "changed-a"
    result = asyncio.run(service.search("q", "kb"))
    assert result["error_type"] == "embedding_binding_unavailable"
    assert "Re-index" in result["answer"]

    result = asyncio.run(service.search("q", "kb", embedding_selection=selection("a")))
    assert result["answer"] == "changed-a"
    assert read_entry(tmp_path)["embedding_selection"] == selection("a")


def test_initialize_reraises_for_deleted_binding_model(catalog, tmp_path):
    class Pipeline:
        async def initialize(self, **kwargs):
            raise AssertionError("must not run")

    write_entry(tmp_path)
    catalog["services"]["embedding"]["profiles"][0]["models"].pop(0)
    service = RAGService(kb_base_dir=str(tmp_path))
    service._pipelines["llamaindex"] = Pipeline()
    with pytest.raises(ValueError, match="deleted"):
        asyncio.run(service.initialize("kb", ["doc"]))


def test_search_migrates_legacy_entry_and_persists_fields(catalog, tmp_path):
    seen = []

    class Pipeline:
        async def search(self, query, kb_name, **kwargs):
            seen.append(get_embedding_config().model)
            return {"answer": seen[-1]}

    write_entry(tmp_path)
    payload = json.loads((tmp_path / "kb_config.json").read_text())
    payload["knowledge_bases"]["kb"].pop("embedding_selection")
    (tmp_path / "kb_config.json").write_text(json.dumps(payload))

    service = RAGService(kb_base_dir=str(tmp_path))
    service._pipelines["llamaindex"] = Pipeline()
    assert asyncio.run(service.search("q", "kb"))["answer"] == "embed-a"
    stored = read_entry(tmp_path)
    assert stored["embedding_selection"] == selection("a")
    assert stored["embedding_status"] == "ready"


def test_connected_kb_bypasses_binding_layer(catalog, tmp_path):
    write_entry(tmp_path, name="remote", type="linked", rag_provider="lightrag")
    payload = json.loads((tmp_path / "kb_config.json").read_text())
    entry = payload["knowledge_bases"]["remote"]
    entry.pop("embedding_selection")
    entry.pop("embedding_signature")
    (tmp_path / "kb_config.json").write_text(json.dumps(payload))

    scoped = []

    class Pipeline:
        async def search(self, query, kb_name, **kwargs):
            scoped.append(scoped_embedding_config())
            return {"answer": "linked result"}

    service = RAGService(kb_base_dir=str(tmp_path))
    service._pipelines["lightrag"] = Pipeline()
    assert asyncio.run(service.search("q", "remote"))["answer"] == "linked result"
    assert scoped == [None]
    assert not read_entry(tmp_path, "remote").get("embedding_selection")


def test_search_without_binding_or_versions_uses_active_default(catalog, tmp_path):
    scoped = []

    class Pipeline:
        async def search(self, query, kb_name, **kwargs):
            cfg = scoped_embedding_config()
            scoped.append(cfg)
            return {"answer": cfg.model if cfg else "passthrough"}

    write_entry(tmp_path)
    payload = json.loads((tmp_path / "kb_config.json").read_text())
    entry = payload["knowledge_bases"]["kb"]
    for key in (
        "embedding_selection",
        "embedding_signature",
        "embedding_model",
        "embedding_dim",
    ):
        entry.pop(key)
    (tmp_path / "kb_config.json").write_text(json.dumps(payload))

    service = RAGService(kb_base_dir=str(tmp_path))
    service._pipelines["llamaindex"] = Pipeline()
    assert asyncio.run(service.search("q", "kb"))["answer"] == "embed-a"
    assert not read_entry(tmp_path).get("embedding_selection")

    bare = deepcopy(catalog)
    bare["services"]["embedding"]["active_profile_id"] = None
    bare["services"]["embedding"]["active_model_id"] = None
    saved = binding.load_catalog
    binding.load_catalog = lambda: deepcopy(bare)
    try:
        assert asyncio.run(service.search("q", "kb"))["answer"] == "passthrough"
    finally:
        binding.load_catalog = saved
    assert [cfg is not None for cfg in scoped] == [True, False]


def test_lightrag_snapshot_freezes_embedding_config_for_reindex(catalog, tmp_path):
    write_entry(tmp_path, rag_provider="lightrag")
    frozen = get_embedding_config(selection("b"))
    snapshot = SimpleNamespace(embedding_config=frozen)
    published = []

    class Pipeline:
        async def initialize(self, **kwargs):
            published.append(scoped_embedding_config().model)
            kwargs["validate_embedding_binding"]()
            kwargs["publish_embedding_binding"]()
            return True

    service = RAGService(kb_base_dir=str(tmp_path))
    service._pipelines["lightrag"] = Pipeline()
    assert asyncio.run(service.initialize("kb", ["doc"], indexing_snapshot=snapshot)) is True
    assert published == ["embed-b"]
    stored = read_entry(tmp_path)
    assert stored["embedding_model"] == "embed-b"
    assert stored["embedding_signature"] == signature_from_config(frozen).hash()


def test_bound_graph_storage_root_gates(catalog, tmp_path):
    cfg = get_embedding_config(selection("a"))
    expected = signature_from_config(cfg).hash()

    assert binding.bound_graph_storage_root(tmp_path, "graphrag", None) is None
    assert binding.bound_graph_storage_root(tmp_path, "graphrag", tmp_path) == tmp_path

    stale = tmp_path / "version-1"
    stale.mkdir()
    (stale / "meta.json").write_text(
        json.dumps(
            {
                "provider": "graphrag",
                "signature": "graphrag",
                "embedding_signature": expected,
            }
        )
    )
    (stale / "placeholder.bin").write_bytes(b"")
    fallback = tmp_path / "version-2"
    fallback.mkdir()
    (fallback / "meta.json").write_text(
        json.dumps({"provider": "graphrag", "signature": "graphrag", "embedding_signature": "old"})
    )

    with embedding_config_scope(cfg):
        with pytest.raises(ValueError, match="No index version matches"):
            binding.bound_graph_storage_root(tmp_path, "graphrag", fallback)


def test_bound_graph_storage_root_ignores_unpublished_lightrag_store(catalog, tmp_path):
    cfg = get_embedding_config(selection("a"))
    candidate = tmp_path / "version-1"
    candidate.mkdir()
    (candidate / "meta.json").write_text(
        json.dumps(
            {
                "provider": "lightrag",
                "signature": "lightrag",
                "embedding_signature": signature_from_config(cfg).hash(),
            }
        )
    )
    (candidate / "kv_store_doc_status.json").write_text(
        json.dumps({"doc": {"status": "processed"}})
    )
    fallback = tmp_path / "version-2"
    fallback.mkdir()
    (fallback / "meta.json").write_text(
        json.dumps({"provider": "lightrag", "signature": "lightrag"})
    )

    with embedding_config_scope(cfg):
        assert binding.bound_graph_storage_root(tmp_path, "lightrag", fallback) == fallback
