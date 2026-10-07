"""KB initialization statistics must state the effective retrieval profile."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from deeptutor.knowledge.initializer import KnowledgeBaseInitializer
from deeptutor.services.rag.pipelines.llamaindex.config import (
    HYBRID_PROFILE,
    RetrievalConfig,
)

INITIALIZER_LOGGER = "deeptutor.knowledge.initializer"
CONFIG_LOADER = "deeptutor.services.rag.pipelines.llamaindex.config.retrieval_config_from_settings"
BM25_IMPORTER = "deeptutor.services.rag.pipelines.llamaindex.retrievers._import_bm25_retriever"


def _initializer(tmp_path: Path) -> KnowledgeBaseInitializer:
    return KnowledgeBaseInitializer(kb_name="notes", base_dir=str(tmp_path))


@pytest.mark.asyncio
async def test_summary_warns_when_hybrid_degrades_to_vector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(CONFIG_LOADER, lambda: RetrievalConfig(profile=HYBRID_PROFILE))
    monkeypatch.setattr(BM25_IMPORTER, lambda: None)

    with caplog.at_level(logging.INFO, logger=INITIALIZER_LOGGER):
        await _initializer(tmp_path).display_statistics_generic()

    warning = next(
        (
            record
            for record in caplog.records
            if record.levelno == logging.WARNING and "Retrieval profile" in record.message
        ),
        None,
    )
    assert warning is not None
    assert "configured 'hybrid', effective 'vector'" in warning.message


@pytest.mark.asyncio
async def test_summary_reports_profile_when_hybrid_is_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(CONFIG_LOADER, lambda: RetrievalConfig(profile=HYBRID_PROFILE))
    monkeypatch.setattr(BM25_IMPORTER, lambda: object)

    with caplog.at_level(logging.INFO, logger=INITIALIZER_LOGGER):
        await _initializer(tmp_path).display_statistics_generic()

    assert "Retrieval profile: hybrid" in caplog.text
    assert not [
        record
        for record in caplog.records
        if record.levelno >= logging.WARNING and "Retrieval profile" in record.message
    ]


@pytest.mark.asyncio
async def test_summary_skips_profile_line_for_non_llamaindex_providers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(CONFIG_LOADER, lambda: RetrievalConfig(profile=HYBRID_PROFILE))
    initializer = KnowledgeBaseInitializer(
        kb_name="notes", base_dir=str(tmp_path), rag_provider="lightrag"
    )

    with caplog.at_level(logging.INFO, logger=INITIALIZER_LOGGER):
        await initializer.display_statistics_generic()

    assert "Retrieval profile" not in caplog.text
