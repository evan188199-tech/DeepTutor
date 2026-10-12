"""LightRAG ingestion/query parameter passthrough (upstream #640 slice one).

``chunk_token_size`` must ride verbatim into each frozen bundle's
``chunk_options`` (and from there into the enqueue call), and ``chunk_top_k``
must ride verbatim into ``QueryParam``. Unset values keep today's literals
and SDK defaults so existing deployments behave exactly as before.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from deeptutor.services.parsing.types import ParsedDocument
from deeptutor.services.rag.pipelines.lightrag import config as lightrag_config
from deeptutor.services.rag.pipelines.lightrag import engine, ingress

REQUIRES_LIGHTRAG = pytest.mark.skipif(
    importlib.util.find_spec("lightrag") is None,
    reason="requires the optional rag-lightrag extra",
)

_TODAY_QUERY_SETTINGS = {
    "top_k": 60,
    "response_type": "Multiple Paragraphs",
    "chunk_token_size": None,
    "chunk_top_k": None,
}


def _settings(monkeypatch: pytest.MonkeyPatch, payload: dict) -> None:
    monkeypatch.setattr("deeptutor.services.config.load_lightrag_settings", lambda: payload)


def _structured_parsed() -> ParsedDocument:
    return ParsedDocument(
        markdown="# Fixture\n\nBody",
        blocks=[
            {
                "type": "text",
                "text": "Fixture",
                "text_level": 1,
                "page_idx": 0,
                "bbox": [1, 2, 3, 4],
            },
            {"type": "text", "text": "Body", "page_idx": 0},
        ],
        source_hash="source-sha",
        parser_signature="mineru-signature",
        engine="mineru",
    )


def _raw_parsed() -> ParsedDocument:
    return ParsedDocument(
        markdown="plain body",
        engine="text_only",
        source_hash="source-sha",
        parser_signature="signature",
    )


def test_query_kwargs_keep_current_surface_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, dict(_TODAY_QUERY_SETTINGS))

    assert lightrag_config.query_kwargs_from_settings() == {
        "top_k": 60,
        "response_type": "Multiple Paragraphs",
    }


def test_query_kwargs_omit_knobs_for_legacy_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """A lightrag.json written before these knobs existed must load unchanged."""
    _settings(monkeypatch, {"top_k": 30, "response_type": "Single Paragraph"})

    assert lightrag_config.query_kwargs_from_settings() == {
        "top_k": 30,
        "response_type": "Single Paragraph",
    }


def test_query_kwargs_forward_chunk_top_k_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, {**_TODAY_QUERY_SETTINGS, "chunk_top_k": 12})

    kwargs = lightrag_config.query_kwargs_from_settings()

    assert kwargs["chunk_top_k"] == 12
    assert isinstance(kwargs["chunk_top_k"], int)
    assert kwargs["top_k"] == 60


def test_ingestion_chunk_options_default_to_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, dict(_TODAY_QUERY_SETTINGS))

    assert lightrag_config.ingestion_chunk_options_from_settings() == {}


def test_ingestion_chunk_options_forward_configured_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings(monkeypatch, {**_TODAY_QUERY_SETTINGS, "chunk_token_size": 2048})

    assert lightrag_config.ingestion_chunk_options_from_settings() == {"chunk_token_size": 2048}


def test_freeze_document_keeps_today_chunk_options(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Unset settings must freeze exactly the payloads staged before this knob."""
    _settings(monkeypatch, dict(_TODAY_QUERY_SETTINGS))

    structured_source = tmp_path / "paper.pdf"
    structured_source.write_bytes(b"pdf")
    staged = ingress.freeze_document(
        tmp_path / "v-structured", structured_source, _structured_parsed()
    )
    assert staged.chunk_options == {"paragraph_semantic": {"chunk_token_size": 1200}}
    manifest, _bundle = ingress.load_verified_bundle(
        tmp_path / "v-structured", staged.canonical_name
    )
    assert manifest["chunk_options"] == {"paragraph_semantic": {"chunk_token_size": 1200}}

    raw_source = tmp_path / "notes.md"
    raw_source.write_text("notes", encoding="utf-8")
    raw_staged = ingress.freeze_document(tmp_path / "v-raw", raw_source, _raw_parsed())
    assert raw_staged.chunk_options == {"fixed_token": {}}


def test_freeze_document_freezes_configured_chunk_token_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _settings(monkeypatch, {**_TODAY_QUERY_SETTINGS, "chunk_token_size": 2048})

    structured_source = tmp_path / "paper.pdf"
    structured_source.write_bytes(b"pdf")
    staged = ingress.freeze_document(
        tmp_path / "v-structured", structured_source, _structured_parsed()
    )
    assert staged.chunk_options == {"paragraph_semantic": {"chunk_token_size": 2048}}
    manifest, _bundle = ingress.load_verified_bundle(
        tmp_path / "v-structured", staged.canonical_name
    )
    assert manifest["chunk_options"] == {"paragraph_semantic": {"chunk_token_size": 2048}}

    raw_source = tmp_path / "notes.md"
    raw_source.write_text("notes", encoding="utf-8")
    raw_staged = ingress.freeze_document(tmp_path / "v-raw", raw_source, _raw_parsed())
    assert raw_staged.chunk_options == {"fixed_token": {"chunk_token_size": 2048}}


@pytest.mark.asyncio
async def test_enqueue_passes_staged_chunk_options_verbatim(tmp_path: Path) -> None:
    staged = ingress.StagedDocument(
        canonical_name="paper.pdf",
        source_path=tmp_path / "pending" / "paper.pdf",
        bundle_dir=tmp_path / "bundle",
        manifest_path=tmp_path / "bundle" / "manifest.json",
        process_options="Pit",
        chunk_options={"paragraph_semantic": {"chunk_token_size": 2048}},
        audit_ledger=None,
    )
    captured: dict[str, object] = {}

    class _Rag:
        async def apipeline_enqueue_documents(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return "batch-id"

    batch_id = await engine.enqueue(_Rag(), [staged])

    assert batch_id == "batch-id"
    assert captured["kwargs"]["chunk_options"] == [staged.chunk_options]
    assert captured["kwargs"]["process_options"] == ["Pit"]
    assert captured["kwargs"]["parse_engine"] == engine.PARSER_ENGINE


@REQUIRES_LIGHTRAG
@pytest.mark.asyncio
async def test_query_param_receives_chunk_top_k_only_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lightrag import QueryParam

    captured: dict[str, object] = {}

    class _Rag:
        async def aquery_llm(self, question, param):
            captured["question"] = question
            captured["param"] = param
            return {
                "status": "success",
                "llm_response": {"content": "answer", "is_streaming": False},
                "data": {"chunks": [], "entities": [], "relationships": [], "references": []},
                "metadata": {"top_k": 60},
            }

    _settings(monkeypatch, dict(_TODAY_QUERY_SETTINGS))
    await engine.query_with_sources(_Rag(), "what?")
    default_param: QueryParam = captured["param"]
    assert default_param.top_k == 60
    assert default_param.mode == "hybrid"
    assert default_param.chunk_top_k == QueryParam().chunk_top_k

    _settings(monkeypatch, {**_TODAY_QUERY_SETTINGS, "chunk_top_k": 12})
    content, sources = await engine.query_with_sources(_Rag(), "what?")
    configured_param: QueryParam = captured["param"]
    assert content == "answer"
    assert configured_param.chunk_top_k == 12
    assert configured_param.top_k == 60
    assert [item["kind"] for item in sources] == ["query_metadata"]


def test_helpers_tolerate_unreadable_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> dict:
        raise RuntimeError("settings unavailable")

    monkeypatch.setattr("deeptutor.services.config.load_lightrag_settings", _boom)

    assert lightrag_config.query_kwargs_from_settings() == {}
    assert lightrag_config.ingestion_chunk_options_from_settings() == {}


def test_module_surface_exports_helper() -> None:
    assert "ingestion_chunk_options_from_settings" in lightrag_config.__all__
