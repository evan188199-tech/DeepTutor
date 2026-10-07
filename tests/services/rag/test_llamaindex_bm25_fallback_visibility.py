"""Visibility of the hybrid → vector-only fallback when BM25 is unavailable."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from deeptutor.services.rag.pipelines.llamaindex import retrievers as retriever_module
from deeptutor.services.rag.pipelines.llamaindex.config import (
    HYBRID_PROFILE,
    VECTOR_PROFILE,
    RetrievalConfig,
)

RETRIEVERS_LOGGER = "deeptutor.services.rag.pipelines.llamaindex.retrievers"


def test_missing_bm25_package_logs_warning_and_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: None)

    with caplog.at_level(logging.WARNING, logger=RETRIEVERS_LOGGER):
        result = retriever_module.build_bm25_retriever(object(), tmp_path, top_k=5)

    assert result is None
    assert "falling back to vector retrieval" in caplog.text
    assert any(record.levelno == logging.WARNING for record in caplog.records)


def test_hybrid_without_bm25_builds_vector_retriever_with_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: None)
    captured: dict[str, int] = {}

    class _RecordingIndex:
        def as_retriever(self, similarity_top_k: int):
            captured["top_k"] = similarity_top_k
            return "vector-retriever"

    with caplog.at_level(logging.WARNING, logger=RETRIEVERS_LOGGER):
        retriever = retriever_module.build_retriever(
            _RecordingIndex(),
            tmp_path,
            top_k=4,
            config=RetrievalConfig(profile=HYBRID_PROFILE),
        )

    assert retriever == "vector-retriever"
    assert captured["top_k"] == 4
    assert "falling back to vector retrieval" in caplog.text


def test_effective_profile_degrades_to_vector_when_hybrid_lacks_bm25(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: None)

    effective = retriever_module.effective_retrieval_profile(
        RetrievalConfig(profile=HYBRID_PROFILE)
    )

    assert effective == VECTOR_PROFILE


def test_effective_profile_stays_hybrid_when_bm25_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: object)

    effective = retriever_module.effective_retrieval_profile(
        RetrievalConfig(profile=HYBRID_PROFILE)
    )

    assert effective == HYBRID_PROFILE


def test_effective_profile_vector_unchanged_without_bm25(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: None)

    effective = retriever_module.effective_retrieval_profile(
        RetrievalConfig(profile=VECTOR_PROFILE)
    )

    assert effective == VECTOR_PROFILE


def test_effective_profile_defaults_to_settings_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: None)
    monkeypatch.setattr(
        retriever_module,
        "retrieval_config_from_settings",
        lambda: RetrievalConfig(profile=HYBRID_PROFILE),
    )

    assert retriever_module.effective_retrieval_profile() == VECTOR_PROFILE
