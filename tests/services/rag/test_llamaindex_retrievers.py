"""Focused tests for the LlamaIndex retriever composition layer."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.services.rag.pipelines.llamaindex import retrievers as retriever_module
from deeptutor.services.rag.pipelines.llamaindex.config import RetrievalConfig

RETRIEVERS_LOGGER = "deeptutor.services.rag.pipelines.llamaindex.retrievers"


class _FakeNode:
    def __init__(self, node_id: str) -> None:
        self.node_id = node_id


class _RecordingRetriever:
    def __init__(self, similarity_top_k: int, results: list[object] | None = None) -> None:
        self.similarity_top_k = similarity_top_k
        self.results = list(results or [])
        self.queries: list[str] = []

    def retrieve(self, query: str) -> list[object]:
        self.queries.append(query)
        return list(self.results)


class _RecordingIndex:
    def __init__(self, results: list[object] | None = None, docs: dict | None = None) -> None:
        self.results = list(results or [])
        if docs is not None:
            self.docstore = SimpleNamespace(docs=docs)
        self.retriever_top_k: list[int] = []
        self.last_retriever: _RecordingRetriever | None = None

    def as_retriever(self, similarity_top_k: int) -> _RecordingRetriever:
        self.retriever_top_k.append(similarity_top_k)
        self.last_retriever = _RecordingRetriever(similarity_top_k, self.results)
        return self.last_retriever


def _fake_bm25_class(
    calls: list[dict],
    *,
    persist_dir_error: Exception | None = None,
    defaults_error: Exception | None = None,
    with_persist: bool = True,
    persist_error: Exception | None = None,
):
    class _FakeBM25:
        @classmethod
        def from_persist_dir(cls, path: str):
            calls.append({"op": "from_persist_dir", "path": path})
            if persist_dir_error is not None:
                raise persist_dir_error
            return SimpleNamespace(similarity_top_k=99)

        @classmethod
        def from_defaults(cls, index, similarity_top_k: int):
            calls.append(
                {"op": "from_defaults", "index": index, "similarity_top_k": similarity_top_k}
            )
            if defaults_error is not None:
                raise defaults_error
            if not with_persist:
                return SimpleNamespace(similarity_top_k=similarity_top_k)

            def _persist(target: str) -> None:
                if persist_error is not None:
                    raise persist_error
                calls.append({"op": "persist", "path": target})

            return SimpleNamespace(similarity_top_k=similarity_top_k, persist=_persist)

    return _FakeBM25


def _patch_settings(monkeypatch: pytest.MonkeyPatch, config: RetrievalConfig) -> None:
    monkeypatch.setattr(retriever_module, "retrieval_config_from_settings", lambda: config)


def _forbid_bm25(monkeypatch: pytest.MonkeyPatch) -> None:
    def _unexpected() -> None:
        raise AssertionError("BM25 integration must not be touched on this path")

    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", _unexpected)


def test_vector_profile_passes_top_k_through_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_bm25(monkeypatch)
    index = _RecordingIndex()

    retriever = retriever_module.build_retriever(
        index, tmp_path, top_k=7, config=RetrievalConfig(profile="vector")
    )

    assert index.retriever_top_k == [7]
    assert retriever.similarity_top_k == 7
    assert retriever.queries == []


def test_build_retriever_clamps_non_positive_top_k_to_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_bm25(monkeypatch)
    index = _RecordingIndex()
    config = RetrievalConfig(profile="vector")

    retriever_module.build_retriever(index, tmp_path, top_k=0, config=config)
    retriever_module.build_retriever(index, tmp_path, top_k=-3, config=config)

    assert index.retriever_top_k == [1, 1]


def test_unknown_profile_falls_back_to_vector_with_original_top_k(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: None)
    index = _RecordingIndex()

    retriever_module.build_retriever(
        index, tmp_path, top_k=4, config=RetrievalConfig(profile="custom")
    )

    assert index.retriever_top_k == [4]


def test_bm25_top_k_clamped_down_to_corpus_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: _fake_bm25_class(calls))
    index = _RecordingIndex(docs={"a": 1, "b": 2, "c": 3})

    retriever = retriever_module.build_bm25_retriever(index, tmp_path, top_k=10)

    assert calls == [{"op": "from_defaults", "index": index, "similarity_top_k": 3}]
    assert retriever.similarity_top_k == 3


def test_bm25_top_k_not_inflated_below_corpus_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: _fake_bm25_class(calls))
    index = _RecordingIndex(docs={"a": 1, "b": 2, "c": 3})

    retriever_module.build_bm25_retriever(index, tmp_path, top_k=2)

    assert calls[0]["similarity_top_k"] == 2


def test_bm25_top_k_kept_when_corpus_size_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: _fake_bm25_class(calls))
    index = _RecordingIndex()

    retriever_module.build_bm25_retriever(index, tmp_path, top_k=4)

    assert calls == [{"op": "from_defaults", "index": index, "similarity_top_k": 4}]


def test_bm25_top_k_floor_of_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: _fake_bm25_class(calls))

    retriever_module.build_bm25_retriever(_RecordingIndex(), tmp_path, top_k=0)

    assert calls[0]["similarity_top_k"] == 1


def test_bm25_missing_package_degrades_to_none_without_building(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: None)
    caplog.set_level(logging.INFO, logger=RETRIEVERS_LOGGER)

    with caplog.at_level(logging.INFO, logger=RETRIEVERS_LOGGER):
        result = retriever_module.build_bm25_retriever(_RecordingIndex(), tmp_path, top_k=5)

    assert result is None
    assert calls == []
    assert "falling back to vector retrieval" in caplog.text


def test_persisted_load_failure_falls_back_to_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[dict] = []
    persist_dir = tmp_path / retriever_module.BM25_PERSIST_DIRNAME
    persist_dir.mkdir()
    fake_cls = _fake_bm25_class(calls, persist_dir_error=RuntimeError("corrupt sidecar"))
    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: fake_cls)
    caplog.set_level(logging.WARNING, logger=RETRIEVERS_LOGGER)

    with caplog.at_level(logging.WARNING, logger=RETRIEVERS_LOGGER):
        retriever = retriever_module.build_bm25_retriever(_RecordingIndex(), tmp_path, top_k=5)

    assert [call["op"] for call in calls] == ["from_persist_dir", "from_defaults"]
    assert calls[1]["similarity_top_k"] == 5
    assert retriever.similarity_top_k == 5
    assert "Failed to load persisted BM25 retriever" in caplog.text


def test_rebuild_failure_translates_to_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[dict] = []
    fake_cls = _fake_bm25_class(calls, defaults_error=RuntimeError("empty corpus"))
    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: fake_cls)
    caplog.set_level(logging.WARNING, logger=RETRIEVERS_LOGGER)

    with caplog.at_level(logging.WARNING, logger=RETRIEVERS_LOGGER):
        result = retriever_module.build_bm25_retriever(_RecordingIndex(), tmp_path, top_k=5)

    assert result is None
    assert [call["op"] for call in calls] == ["from_defaults"]
    assert "falling back to vector retrieval" in caplog.text


def test_persist_bm25_success_writes_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []
    fake_cls = _fake_bm25_class(calls)
    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: fake_cls)
    index = _RecordingIndex(docs={"a": 1})

    assert retriever_module.persist_bm25_retriever(index, tmp_path, top_k=3) is True

    persist_dir = tmp_path / retriever_module.BM25_PERSIST_DIRNAME
    assert persist_dir.is_dir()
    assert calls[0] == {"op": "from_defaults", "index": index, "similarity_top_k": 3}
    assert calls[1] == {"op": "persist", "path": str(persist_dir)}


def test_persist_bm25_returns_false_when_package_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: None)

    assert retriever_module.persist_bm25_retriever(_RecordingIndex(), tmp_path, top_k=3) is False
    assert not (tmp_path / retriever_module.BM25_PERSIST_DIRNAME).exists()


def test_persist_bm25_returns_false_without_persist_method(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []
    fake_cls = _fake_bm25_class(calls, with_persist=False)
    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: fake_cls)

    assert retriever_module.persist_bm25_retriever(_RecordingIndex(), tmp_path, top_k=3) is False
    assert [call["op"] for call in calls] == ["from_defaults"]
    assert not (tmp_path / retriever_module.BM25_PERSIST_DIRNAME).exists()


def test_persist_bm25_returns_false_when_persist_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[dict] = []
    fake_cls = _fake_bm25_class(calls, persist_error=RuntimeError("disk full"))
    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: fake_cls)
    caplog.set_level(logging.WARNING, logger=RETRIEVERS_LOGGER)

    with caplog.at_level(logging.WARNING, logger=RETRIEVERS_LOGGER):
        result = retriever_module.persist_bm25_retriever(_RecordingIndex(), tmp_path, top_k=3)

    assert result is False
    assert "Failed to persist BM25 retriever" in caplog.text


def test_retrieve_nodes_passes_query_and_slices_to_top_k(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_bm25(monkeypatch)
    index = _RecordingIndex(results=[_FakeNode("n1"), _FakeNode("n2"), _FakeNode("n3")])
    _patch_settings(monkeypatch, RetrievalConfig(profile="vector"))

    results = retriever_module.retrieve_nodes(index, tmp_path, "what is rag?", top_k=2)

    assert index.retriever_top_k == [2]
    assert index.last_retriever is not None
    assert index.last_retriever.queries == ["what is rag?"]
    assert [node.node_id for node in results] == ["n1", "n2"]


def test_retrieve_nodes_empty_result_degrades_to_empty_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_bm25(monkeypatch)
    index = _RecordingIndex(results=[])
    _patch_settings(monkeypatch, RetrievalConfig(profile="vector"))

    results = retriever_module.retrieve_nodes(index, tmp_path, "probe", top_k=3)

    assert results == []


def test_retrieve_nodes_returns_all_candidates_below_top_k(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_bm25(monkeypatch)
    index = _RecordingIndex(results=[_FakeNode("n1"), _FakeNode("n2")])
    _patch_settings(monkeypatch, RetrievalConfig(profile="vector"))

    results = retriever_module.retrieve_nodes(index, tmp_path, "probe", top_k=5)

    assert [node.node_id for node in results] == ["n1", "n2"]


def test_retrieve_nodes_hybrid_without_bm25_package_degrades_to_vector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: None)
    index = _RecordingIndex(results=[_FakeNode("n1"), _FakeNode("n2"), _FakeNode("n3")])
    _patch_settings(monkeypatch, RetrievalConfig(profile="hybrid"))

    results = retriever_module.retrieve_nodes(index, tmp_path, "probe", top_k=3)

    assert index.retriever_top_k == [3]
    assert [node.node_id for node in results] == ["n1", "n2", "n3"]


def test_retrieve_nodes_hybrid_bm25_build_failure_degrades_to_vector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[dict] = []
    fake_cls = _fake_bm25_class(calls, defaults_error=RuntimeError("empty corpus"))
    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: fake_cls)
    index = _RecordingIndex(results=[_FakeNode("n1"), _FakeNode("n2")])
    _patch_settings(monkeypatch, RetrievalConfig(profile="hybrid"))
    caplog.set_level(logging.WARNING, logger=RETRIEVERS_LOGGER)

    with caplog.at_level(logging.WARNING, logger=RETRIEVERS_LOGGER):
        results = retriever_module.retrieve_nodes(index, tmp_path, "probe", top_k=3)

    assert calls[0]["similarity_top_k"] == 6
    assert index.retriever_top_k == [3]
    assert [node.node_id for node in results] == ["n1", "n2"]


def test_retrieve_nodes_with_reranker_expands_candidates_and_keeps_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = RetrievalConfig(profile="vector", reranker_model="fake/model", rerank_top_k=9)
    _patch_settings(monkeypatch, config)
    index = _RecordingIndex(results=[_FakeNode("n1"), _FakeNode("n2"), _FakeNode("n3")])
    build_calls: dict[str, object] = {}

    def _fake_build(idx, storage_dir, *, top_k: int, config: RetrievalConfig):
        build_calls["index"] = idx
        build_calls["top_k"] = top_k
        build_calls["config"] = config
        return _RecordingRetriever(top_k, idx.results)

    rerank_calls: list[dict[str, object]] = []

    def _fake_rerank(query, candidates, *, top_k: int, model_name: str):
        rerank_calls.append(
            {
                "query": query,
                "count": len(candidates),
                "top_k": top_k,
                "model_name": model_name,
            }
        )
        return candidates[:top_k]

    monkeypatch.setattr(retriever_module, "build_retriever", _fake_build)
    monkeypatch.setattr(retriever_module, "rerank_nodes", _fake_rerank)

    results = retriever_module.retrieve_nodes(index, tmp_path, "probe", top_k=2)

    assert build_calls["top_k"] == 9
    assert build_calls["config"] is config
    assert rerank_calls == [
        {
            "query": "probe",
            "count": 3,
            "top_k": 2,
            "model_name": "fake/model",
        }
    ]
    assert [node.node_id for node in results] == ["n1", "n2"]
