"""Optional cross-encoder reranking for LlamaIndex retrieval."""

from __future__ import annotations

from decimal import Decimal
import math
from pathlib import Path
from typing import Any

from llama_index.core.schema import MetadataMode, NodeWithScore, TextNode
import pytest

from deeptutor.services.rag.pipelines.llamaindex import rerank as rerank_module
from deeptutor.services.rag.pipelines.llamaindex import retrievers as retriever_module
from deeptutor.services.rag.pipelines.llamaindex.config import RetrievalConfig


@pytest.fixture(autouse=True)
def _clear_reranker_cache():
    rerank_module.clear_reranker_cache()
    yield
    rerank_module.clear_reranker_cache()


def _result(node_id: str, text: str, score: float = 0.5) -> NodeWithScore:
    return NodeWithScore(node=TextNode(text=text, id_=node_id), score=score)


def test_cross_encoder_reranks_candidates_and_normalizes_scores() -> None:
    class _FakeModel:
        def predict(
            self,
            pairs: list[tuple[str, str]],
            *,
            activation_fct: object,
        ) -> list[float]:
            assert all(query == "probe" for query, _ in pairs)
            assert callable(activation_fct)
            return [-8.0, 8.0]

    candidates = [_result("weak", "weak candidate"), _result("strong", "strong candidate")]

    ranked = rerank_module.rerank_nodes(
        "probe",
        candidates,
        top_k=2,
        model_name="fake-reranker",
        loader=lambda _model: _FakeModel(),
    )

    assert [result.node_id for result in ranked] == ["strong", "weak"]
    assert ranked[0].score is not None and ranked[0].score > 0.99
    assert ranked[1].score is not None and ranked[1].score < 0.01


def test_reranker_load_failure_returns_first_stage_candidates(
    caplog: pytest.LogCaptureFixture,
) -> None:
    candidates = [_result("first", "first"), _result("second", "second")]

    def _missing_dependency(_model: str):
        raise ImportError("sentence-transformers is not installed")

    with caplog.at_level("WARNING"):
        ranked = rerank_module.rerank_nodes(
            "probe",
            candidates,
            top_k=1,
            model_name="fake-reranker",
            loader=_missing_dependency,
        )

    assert [result.node_id for result in ranked] == ["first"]
    assert "sentence-transformers is not installed" in caplog.text


def test_reranker_scoring_failure_returns_first_stage_candidates(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _FailingModel:
        def predict(
            self,
            pairs: list[tuple[str, str]],
            *,
            activation_fct: object,
        ) -> list[float]:
            raise RuntimeError("scoring failed")

    candidates = [_result("first", "first"), _result("second", "second")]

    with caplog.at_level("WARNING"):
        ranked = rerank_module.rerank_nodes(
            "probe",
            candidates,
            top_k=1,
            model_name="fake-reranker",
            loader=lambda _model: _FailingModel(),
        )

    assert [result.node_id for result in ranked] == ["first"]
    assert "failed while scoring 2 candidates" in caplog.text


def test_retrieve_nodes_expands_candidates_only_when_reranker_is_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    class _FakeRetriever:
        def retrieve(self, query: str) -> list[NodeWithScore]:
            captured["query"] = query
            return [
                _result("first", "first"),
                _result("second", "second"),
                _result("third", "third"),
            ]

    def _fake_build(_index, _storage_dir, *, top_k: int, config: RetrievalConfig):
        captured["candidate_top_k"] = top_k
        captured["config"] = config
        return _FakeRetriever()

    def _fail_if_called(*args: object, **kwargs: object):
        raise AssertionError("rerank_nodes must not run without a configured model")

    monkeypatch.setattr(retriever_module, "build_retriever", _fake_build)
    monkeypatch.setattr(retriever_module, "rerank_nodes", _fail_if_called)
    monkeypatch.setattr(
        retriever_module,
        "retrieval_config_from_settings",
        lambda: RetrievalConfig(profile="vector"),
    )

    unchanged = retriever_module.retrieve_nodes(object(), tmp_path, "probe", top_k=2)

    assert captured["candidate_top_k"] == 2
    assert [result.node_id for result in unchanged] == ["first", "second"]

    rerank_calls: list[dict[str, object]] = []

    def _fake_rerank(query, candidates, *, top_k, model_name):
        rerank_calls.append(
            {
                "query": query,
                "count": len(candidates),
                "top_k": top_k,
                "model_name": model_name,
            }
        )
        return candidates[:top_k]

    monkeypatch.setattr(retriever_module, "rerank_nodes", _fake_rerank)
    monkeypatch.setattr(
        retriever_module,
        "retrieval_config_from_settings",
        lambda: RetrievalConfig(profile="vector", reranker_model="fake-reranker", rerank_top_k=9),
    )

    reranked = retriever_module.retrieve_nodes(object(), tmp_path, "probe", top_k=2)

    assert captured["candidate_top_k"] == 9
    assert rerank_calls == [
        {
            "query": "probe",
            "count": 3,
            "top_k": 2,
            "model_name": "fake-reranker",
        }
    ]
    assert [result.node_id for result in reranked] == ["first", "second"]


class _StaticModel:
    def __init__(self, scores: list[Any]) -> None:
        self._scores = scores

    def predict(
        self,
        pairs: list[tuple[str, str]],
        *,
        activation_fct: object,
    ) -> list[Any]:
        return list(self._scores)


def test_rerank_builds_query_content_pairs_and_requests_raw_logits() -> None:
    observed_modes: list[MetadataMode] = []

    class _ProbeNode(TextNode):
        def get_content(self, metadata_mode: MetadataMode = MetadataMode.NONE) -> str:
            observed_modes.append(metadata_mode)
            return f"content for {self.node_id}"

    class _RecordingModel:
        def __init__(self) -> None:
            self.seen_pairs: list[list[tuple[str, str]]] = []
            self.seen_activations: list[object] = []

        def predict(
            self,
            pairs: list[tuple[str, str]],
            *,
            activation_fct: object,
        ) -> list[float]:
            self.seen_pairs.append(pairs)
            self.seen_activations.append(activation_fct)
            return [1.0, -1.0]

    model = _RecordingModel()
    candidates = [
        NodeWithScore(node=_ProbeNode(id_="probe-a"), score=0.0),
        NodeWithScore(node=_ProbeNode(id_="probe-b"), score=0.0),
    ]

    ranked = rerank_module.rerank_nodes(
        "probe query",
        candidates,
        top_k=2,
        model_name="fake-reranker",
        loader=lambda _model: model,
    )

    assert model.seen_pairs == [
        [
            ("probe query", "content for probe-a"),
            ("probe query", "content for probe-b"),
        ]
    ]
    assert len(model.seen_activations) == 1
    assert model.seen_activations[0](3.5) == 3.5
    assert observed_modes == [MetadataMode.LLM, MetadataMode.LLM]
    assert [result.node_id for result in ranked] == ["probe-a", "probe-b"]


def test_rerank_breaks_tied_scores_by_first_stage_order() -> None:
    candidates = [_result("node-0", "text"), _result("node-1", "text"), _result("node-2", "text")]

    ranked = rerank_module.rerank_nodes(
        "probe",
        candidates,
        top_k=3,
        model_name="fake-reranker",
        loader=lambda _model: _StaticModel([0.4, 0.9, 0.4]),
    )

    assert [result.node_id for result in ranked] == ["node-1", "node-0", "node-2"]


def test_rerank_drops_non_finite_scores_from_ranking() -> None:
    scores = [float("nan"), 0.2, float("inf"), 0.8, float("-inf")]
    candidates = [_result(f"node-{index}", "text") for index in range(5)]

    ranked = rerank_module.rerank_nodes(
        "probe",
        candidates,
        top_k=5,
        model_name="fake-reranker",
        loader=lambda _model: _StaticModel(scores),
    )

    assert [result.node_id for result in ranked] == ["node-3", "node-1"]
    assert ranked[0].score is not None
    assert ranked[0].score == pytest.approx(1.0 / (1.0 + math.exp(-0.8)))
    assert ranked[1].score is not None
    assert ranked[1].score == pytest.approx(1.0 / (1.0 + math.exp(-0.2)))


def test_rerank_converts_scores_that_implement_float() -> None:
    candidates = [_result("low", "text"), _result("high", "text")]

    ranked = rerank_module.rerank_nodes(
        "probe",
        candidates,
        top_k=2,
        model_name="fake-reranker",
        loader=lambda _model: _StaticModel([Decimal("0.25"), Decimal("0.75")]),
    )

    assert [result.node_id for result in ranked] == ["high", "low"]
    assert ranked[0].score is not None
    assert ranked[0].score == pytest.approx(1.0 / (1.0 + math.exp(-0.75)))


@pytest.mark.parametrize(
    ("query", "model_name"),
    [("", "fake-reranker"), ("probe", "")],
)
def test_rerank_skips_scoring_without_query_or_model(query: str, model_name: str) -> None:
    candidates = [_result("first", "first"), _result("second", "second")]
    loader_calls: list[str] = []

    def _recording_loader(model: str):
        loader_calls.append(model)
        return _StaticModel([9.0, 9.0])

    ranked = rerank_module.rerank_nodes(
        query,
        candidates,
        top_k=5,
        model_name=model_name,
        loader=_recording_loader,
    )

    assert [result.node_id for result in ranked] == ["first", "second"]
    assert loader_calls == []


def test_rerank_empty_candidates_returns_empty_list() -> None:
    ranked = rerank_module.rerank_nodes(
        "probe",
        [],
        top_k=3,
        model_name="fake-reranker",
        loader=lambda _model: _StaticModel([0.5]),
    )

    assert ranked == []


def test_rerank_applies_top_k_with_minimum_of_one() -> None:
    candidates = [_result("node-0", "text"), _result("node-1", "text"), _result("node-2", "text")]

    def _loader(_model: str):
        return _StaticModel([0.1, 0.9, 0.5])

    best = rerank_module.rerank_nodes(
        "probe",
        candidates,
        top_k=0,
        model_name="fake-reranker",
        loader=_loader,
    )
    assert [result.node_id for result in best] == ["node-1"]

    everything = rerank_module.rerank_nodes(
        "probe",
        candidates,
        top_k=99,
        model_name="fake-reranker",
        loader=_loader,
    )
    assert [result.node_id for result in everything] == ["node-1", "node-2", "node-0"]


def test_rerank_timeout_degrades_to_first_stage_order(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _TimeoutModel:
        def predict(
            self,
            pairs: list[tuple[str, str]],
            *,
            activation_fct: object,
        ) -> list[float]:
            raise TimeoutError("cross-encoder timed out")

    candidates = [_result("first", "first"), _result("second", "second"), _result("third", "third")]

    with caplog.at_level("WARNING"):
        ranked = rerank_module.rerank_nodes(
            "probe",
            candidates,
            top_k=2,
            model_name="fake-reranker",
            loader=lambda _model: _TimeoutModel(),
        )

    assert [result.node_id for result in ranked] == ["first", "second"]
    assert "failed while scoring 3 candidates" in caplog.text


def test_rerank_malformed_scores_degrade_to_first_stage_order(
    caplog: pytest.LogCaptureFixture,
) -> None:
    scores: list[Any] = [None, "not-a-number", 0.7]
    candidates = [_result("first", "first"), _result("second", "second"), _result("third", "third")]

    with caplog.at_level("WARNING"):
        ranked = rerank_module.rerank_nodes(
            "probe",
            candidates,
            top_k=2,
            model_name="fake-reranker",
            loader=lambda _model: _StaticModel(scores),
        )

    assert [result.node_id for result in ranked] == ["first", "second"]
    assert "failed while scoring 3 candidates" in caplog.text


def test_reranker_cache_reuses_models_and_evicts_least_recent() -> None:
    loader_calls: list[str] = []

    def _loader(model_name: str):
        loader_calls.append(model_name)
        return _StaticModel([0.0])

    candidates = [_result("node", "text")]
    for _ in range(2):
        rerank_module.rerank_nodes(
            "probe", candidates, top_k=1, model_name="model-a", loader=_loader
        )
    rerank_module.rerank_nodes("probe", candidates, top_k=1, model_name="model-b", loader=_loader)
    rerank_module.rerank_nodes("probe", candidates, top_k=1, model_name="model-c", loader=_loader)
    rerank_module.rerank_nodes("probe", candidates, top_k=1, model_name="model-a", loader=_loader)

    assert loader_calls == ["model-a", "model-b", "model-c", "model-a"]


def test_rerank_clamps_extreme_logits_to_unit_interval() -> None:
    candidates = [_result("node-0", "text"), _result("node-1", "text"), _result("node-2", "text")]

    ranked = rerank_module.rerank_nodes(
        "probe",
        candidates,
        top_k=3,
        model_name="fake-reranker",
        loader=lambda _model: _StaticModel([2000.0, 0.0, -2000.0]),
    )

    assert [result.node_id for result in ranked] == ["node-0", "node-1", "node-2"]
    assert ranked[0].score == pytest.approx(1.0)
    assert ranked[1].score == pytest.approx(0.5)
    assert ranked[2].score == pytest.approx(0.0)
