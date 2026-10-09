"""Contract and faiss-less degradation tests for the LlamaIndex vector-store seam.

Complements ``test_llamaindex_faiss_vector_store.py`` (which skips entirely
without faiss) by pinning the module's degradation contract: when ``faiss`` or
its LlamaIndex integration cannot be imported, every entry point falls back to
the SimpleVectorStore path instead of raising — and a FAISS-persisted knowledge
base surfaces an actionable install hint. Also pins the direct contracts of
``faiss_available`` / ``faiss_write_index`` / ``faiss_read_index`` /
``new_faiss_storage_context`` that the end-to-end tests only touch indirectly.

No network and no real credentials or services are needed.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from deeptutor.services.rag.pipelines.llamaindex import vector_store
from deeptutor.services.rag.pipelines.llamaindex.config import (
    HNSW_VECTOR_INDEX,
    VectorIndexConfig,
)

_DIM = 8

# Test vector: unit length in the first coordinate, so a normalized
# IndexFlatIP store can reconstruct and re-rank it deterministically.
_UNIT = [1.0] + [0.0] * (_DIM - 1)


@pytest.fixture
def no_faiss(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate an install where faiss is not importable.

    A ``None`` entry in ``sys.modules`` makes the next ``import faiss`` raise
    ``ImportError``, which drives ``_faiss_modules`` through its real
    ``except`` branch. The cosine-store class cache is reset so the memoized
    value from a previous (faiss-enabled) test cannot leak in.
    """
    monkeypatch.setitem(sys.modules, "faiss", None)
    monkeypatch.setattr(vector_store, "_COSINE_FAISS_CLS", None)


@pytest.fixture
def no_faiss_integration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate faiss installed but the LlamaIndex FAISS integration missing."""
    monkeypatch.setitem(sys.modules, "llama_index.vector_stores.faiss", None)
    monkeypatch.setattr(vector_store, "_COSINE_FAISS_CLS", None)


requires_faiss = pytest.mark.skipif(
    not vector_store.faiss_available(), reason="faiss-cpu is not installed"
)


def _cosine_store():
    context = vector_store.new_faiss_storage_context(_DIM)
    assert context is not None
    return context.vector_store


# ---------------------------------------------------------------------------
# Availability probe
# ---------------------------------------------------------------------------


def test_faiss_modules_report_missing_without_faiss(no_faiss: None) -> None:
    assert vector_store._faiss_modules() == (None, None)


def test_faiss_modules_report_missing_without_llama_integration(
    no_faiss_integration: None,
) -> None:
    assert vector_store._faiss_modules() == (None, None)


def test_faiss_available_false_without_faiss(no_faiss: None) -> None:
    assert vector_store.faiss_available() is False


def test_faiss_available_false_without_llama_integration(
    no_faiss_integration: None,
) -> None:
    assert vector_store.faiss_available() is False


@requires_faiss
def test_faiss_available_true_with_faiss_installed() -> None:
    assert vector_store.faiss_available() is True


# ---------------------------------------------------------------------------
# Degradation: every entry point falls back instead of raising
# ---------------------------------------------------------------------------


def test_new_faiss_storage_context_returns_none_without_faiss(no_faiss: None) -> None:
    assert vector_store.new_faiss_storage_context(_DIM) is None


def test_storage_context_for_nodes_falls_back_without_faiss(
    no_faiss: None,
) -> None:
    """Uniform-dimension nodes still land on SimpleVectorStore without faiss."""

    class _Node:
        embedding = [0.0] * _DIM

    assert vector_store.storage_context_for_nodes([_Node()]) is None


@requires_faiss
def test_new_faiss_storage_context_returns_none_for_invalid_dimension() -> None:
    """A non-positive dimension cannot size a FAISS index, so fall back."""
    assert vector_store.new_faiss_storage_context(0) is None
    assert vector_store.new_faiss_storage_context(-3) is None


@requires_faiss
def test_storage_context_for_nodes_empty_or_unembedded_nodes_fall_back() -> None:
    """No embeddings to size an index from, so use the SimpleVectorStore path."""
    assert vector_store.storage_context_for_nodes([]) is None

    class _Node:
        embedding = None

    assert vector_store.storage_context_for_nodes([_Node()]) is None


def test_cosine_faiss_cls_is_none_without_faiss(no_faiss: None) -> None:
    assert vector_store._cosine_faiss_cls() is None


def test_load_index_raises_actionable_error_for_faiss_kb_without_faiss(
    tmp_path: Path, no_faiss: None
) -> None:
    """A FAISS-persisted KB on a faiss-less install explains how to recover."""
    # Any first byte other than "{" marks the store as FAISS (detect_backend).
    (tmp_path / vector_store.DEFAULT_VECTOR_STORE_FILENAME).write_bytes(b"\x00")

    with pytest.raises(RuntimeError, match="faiss-cpu"):
        vector_store.load_index(tmp_path)


# ---------------------------------------------------------------------------
# new_faiss_storage_context contract
# ---------------------------------------------------------------------------


@requires_faiss
def test_new_faiss_storage_context_builds_flat_cosine_store_by_default() -> None:
    import faiss

    context = vector_store.new_faiss_storage_context(_DIM)

    assert context is not None
    store = context.vector_store
    cosine_cls = vector_store._cosine_faiss_cls()
    assert cosine_cls is not None
    assert type(store) is cosine_cls
    index = store._faiss_index
    assert type(index).__name__ == "IndexFlatIP"
    assert index.d == _DIM
    assert index.metric_type == faiss.METRIC_INNER_PRODUCT


@requires_faiss
def test_new_faiss_storage_context_builds_hnsw_index_when_configured() -> None:
    config = VectorIndexConfig(
        type=HNSW_VECTOR_INDEX, hnsw_m=8, hnsw_ef_construction=32, hnsw_ef_search=16
    )
    context = vector_store.new_faiss_storage_context(_DIM, config)

    assert context is not None
    index = context.vector_store._faiss_index
    assert type(index).__name__ == "IndexHNSWFlat"
    assert index.hnsw.efConstruction == 32
    assert index.hnsw.efSearch == 16


@requires_faiss
def test_new_faiss_storage_context_clamps_hnsw_knobs_to_positive() -> None:
    """Non-positive HNSW knobs are clamped to 1 instead of building a broken index."""
    config = VectorIndexConfig(
        type=HNSW_VECTOR_INDEX, hnsw_m=0, hnsw_ef_construction=0, hnsw_ef_search=0
    )
    context = vector_store.new_faiss_storage_context(_DIM, config)

    assert context is not None
    index = context.vector_store._faiss_index
    assert index.hnsw.efConstruction == 1
    assert index.hnsw.efSearch == 1


@requires_faiss
def test_cosine_cls_is_memoized_across_calls() -> None:
    first = vector_store._cosine_faiss_cls()
    assert first is not None
    assert vector_store._cosine_faiss_cls() is first


# ---------------------------------------------------------------------------
# Cosine store persistence guards
# ---------------------------------------------------------------------------


@requires_faiss
def test_cosine_store_persist_rejects_non_local_fs(tmp_path: Path) -> None:
    store = _cosine_store()
    with pytest.raises(NotImplementedError):
        store.persist(str(tmp_path / "store.json"), fs=object())


@requires_faiss
def test_cosine_store_from_persist_path_rejects_non_local_fs(tmp_path: Path) -> None:
    cosine_cls = vector_store._cosine_faiss_cls()
    assert cosine_cls is not None
    with pytest.raises(NotImplementedError):
        cosine_cls.from_persist_path(str(tmp_path / "store.json"), fs=object())


@requires_faiss
def test_cosine_store_from_persist_path_missing_file_raises_value_error(
    tmp_path: Path,
) -> None:
    cosine_cls = vector_store._cosine_faiss_cls()
    assert cosine_cls is not None
    with pytest.raises(ValueError, match="No existing FAISS index"):
        cosine_cls.from_persist_path(str(tmp_path / "absent.json"))


@requires_faiss
def test_cosine_store_persist_creates_parent_dirs_and_roundtrips(tmp_path: Path) -> None:
    """persist() creates missing parents and from_persist_path reloads the index."""
    import numpy as np

    store = _cosine_store()
    store._faiss_index.add(np.asarray([_UNIT], dtype="float32"))

    target = tmp_path / "nested" / "kb" / vector_store.DEFAULT_VECTOR_STORE_FILENAME
    store.persist(str(target))
    assert target.is_file()

    cosine_cls = vector_store._cosine_faiss_cls()
    assert cosine_cls is not None
    reloaded = cosine_cls.from_persist_path(str(target))
    assert reloaded._faiss_index.ntotal == 1


# ---------------------------------------------------------------------------
# faiss_write_index / faiss_read_index contract
# ---------------------------------------------------------------------------


@requires_faiss
def test_faiss_write_then_read_index_roundtrip(tmp_path: Path) -> None:
    import faiss
    import numpy as np

    index = faiss.IndexFlatIP(_DIM)
    index.add(np.asarray([_UNIT], dtype="float32"))

    path = tmp_path / "index.faiss"
    vector_store.faiss_write_index(index, str(path))
    reloaded = vector_store.faiss_read_index(str(path))

    assert path.stat().st_size > 0
    assert reloaded.ntotal == 1
    assert reloaded.d == _DIM
    assert reloaded.reconstruct(0).tolist() == index.reconstruct(0).tolist()


# ---------------------------------------------------------------------------
# detect_backend first-byte contract edge
# ---------------------------------------------------------------------------


def test_detect_backend_reports_faiss_for_empty_store_file(tmp_path: Path) -> None:
    """Only a leading "{" means SimpleVectorStore; anything else (even empty) is FAISS."""
    store = tmp_path / vector_store.DEFAULT_VECTOR_STORE_FILENAME
    store.write_bytes(b"")
    assert vector_store.detect_backend(tmp_path) == vector_store.BACKEND_FAISS
