"""Failure-branch and response-parsing tests for the DashScope adapter.

The ``dashscope`` SDK is stubbed (or removed) via ``sys.modules`` — no
network and no real key. Complements ``test_dashscope_adapter.py``, which
covers surface routing and happy-path request construction.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from deeptutor.services.embedding.adapters.base import EmbeddingRequest
from deeptutor.services.embedding.adapters.dashscope_native import (
    DashScopeMultiModalEmbeddingAdapter,
)


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int | None = 200,
        output: Any = None,
        usage: Any = None,
        code: str = "",
        message: str = "",
        request_id: str = "req-1",
    ) -> None:
        self.status_code = status_code
        self.output = output
        self.usage = usage
        self.code = code
        self.message = message
        self.request_id = request_id


class _Record:
    """Attribute-style stand-in for SDK response objects."""

    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


def _install_fake_sdk(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse) -> dict[str, Any]:
    """Stub both DashScope embedding surfaces and record which one is called."""
    captured: dict[str, Any] = {}

    def _surface(name: str):
        def fake_call(*, api_key: str, model: str, input: Any, **kwargs: Any) -> _FakeResponse:  # noqa: A002
            captured.update(
                surface=name,
                api_key=api_key,
                model=model,
                input=input,
                kwargs=kwargs,
            )
            return response

        return fake_call

    fake_module = types.SimpleNamespace(
        MultiModalEmbedding=types.SimpleNamespace(call=_surface("multimodal")),
        TextEmbedding=types.SimpleNamespace(call=_surface("text")),
    )
    monkeypatch.setitem(sys.modules, "dashscope", fake_module)
    return captured


def _adapter(model: str) -> DashScopeMultiModalEmbeddingAdapter:
    return DashScopeMultiModalEmbeddingAdapter(
        {
            "api_key": "sk-dashscope-test",
            "base_url": "https://dashscope.aliyuncs.com/api/v1/services/embeddings",
            "model": model,
            "dimensions": 1024,
            "request_timeout": 5,
        }
    )


# ── Missing SDK ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_sdk_raises_actionable_import_error_multimodal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "dashscope", None)

    with pytest.raises(ImportError, match="pip install dashscope"):
        await _adapter("qwen3-vl-embedding").embed(
            EmbeddingRequest(texts=["hello"], model="qwen3-vl-embedding")
        )


@pytest.mark.asyncio
async def test_missing_sdk_raises_actionable_import_error_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "dashscope", None)

    with pytest.raises(ImportError, match="pip install dashscope"):
        await _adapter("text-embedding-v4").embed(
            EmbeddingRequest(texts=["hello"], model="text-embedding-v4")
        )


# ── Error branches ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_text_surface_failure_includes_status_code_and_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _FakeResponse(
        status_code=429,
        output=None,
        code="Throttling",
        message="Requests rate limit exceeded",
        request_id="req-throttled",
    )
    _install_fake_sdk(monkeypatch, response)

    with pytest.raises(RuntimeError) as caught:
        await _adapter("text-embedding-v4").embed(
            EmbeddingRequest(texts=["hello"], model="text-embedding-v4")
        )

    rendered = str(caught.value)
    assert "status=429" in rendered
    assert "Throttling" in rendered
    assert "request_id=req-throttled" in rendered
    assert "text-embedding-v4" in rendered


@pytest.mark.asyncio
async def test_missing_output_raises_value_error_with_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_sdk(monkeypatch, _FakeResponse(output=None, request_id="req-lost"))

    with pytest.raises(ValueError, match="missing `output`") as caught:
        await _adapter("qwen3-vl-embedding").embed(
            EmbeddingRequest(texts=["hello"], model="qwen3-vl-embedding")
        )

    assert "req-lost" in str(caught.value)


@pytest.mark.asyncio
async def test_empty_embeddings_raise_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_sdk(monkeypatch, _FakeResponse(output={"embeddings": []}, request_id="req-empty"))

    with pytest.raises(ValueError, match="no embedding vectors"):
        await _adapter("qwen3-vl-embedding").embed(
            EmbeddingRequest(texts=["hello"], model="qwen3-vl-embedding")
        )


@pytest.mark.asyncio
async def test_items_without_vectors_are_skipped_leaving_no_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_sdk(
        monkeypatch,
        _FakeResponse(output={"embeddings": [{"index": 0}, {"index": 1}]}),
    )

    with pytest.raises(ValueError, match="no embedding vectors"):
        await _adapter("qwen3-vl-embedding").embed(
            EmbeddingRequest(texts=["hello"], model="qwen3-vl-embedding")
        )


@pytest.mark.asyncio
async def test_none_status_code_is_treated_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_sdk(
        monkeypatch,
        _FakeResponse(status_code=None, output={"embeddings": [{"embedding": [0.5]}]}),
    )

    response = await _adapter("qwen3-vl-embedding").embed(
        EmbeddingRequest(texts=["hello"], model="qwen3-vl-embedding")
    )

    assert response.embeddings == [[0.5]]


# ── Response parsing ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_object_style_output_items_and_usage_are_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _FakeResponse(
        output=_Record(embeddings=[_Record(embedding=[0.1, 0.2]), _Record(embedding=[0.3])]),
        usage=_Record(input_tokens=5, output_tokens=0, total_tokens=5),
    )
    _install_fake_sdk(monkeypatch, response)

    resp = await _adapter("qwen3-vl-embedding").embed(
        EmbeddingRequest(texts=["a", "b"], model="qwen3-vl-embedding")
    )

    assert resp.embeddings == [[0.1, 0.2], [0.3]]
    assert resp.dimensions == 2
    assert resp.usage == {"input_tokens": 5, "output_tokens": 0, "total_tokens": 5}


@pytest.mark.asyncio
async def test_partial_attribute_usage_keeps_only_present_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _FakeResponse(
        output={"embeddings": [{"embedding": [1.0]}]},
        usage=_Record(total_tokens=7),
    )
    _install_fake_sdk(monkeypatch, response)

    resp = await _adapter("qwen3-vl-embedding").embed(
        EmbeddingRequest(texts=["a"], model="qwen3-vl-embedding")
    )

    assert resp.usage == {"total_tokens": 7}


# ── Request construction ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_text_model_falls_back_to_text_entries_inside_contents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Images are dropped, not sent, when a text model receives mixed contents."""
    response = _FakeResponse(output={"embeddings": [{"embedding": [0.1]}]})
    captured = _install_fake_sdk(monkeypatch, response)

    await _adapter("text-embedding-v4").embed(
        EmbeddingRequest(
            texts=[],
            model="text-embedding-v4",
            contents=[
                {"text": "caption one"},
                {"image": "https://example.com/figure.png"},
                {"text": "caption two"},
            ],
        )
    )

    assert captured["surface"] == "text"
    assert captured["input"] == ["caption one", "caption two"]
    assert captured["kwargs"].get("dimension") == 1024


@pytest.mark.asyncio
async def test_multimodal_surface_omits_zero_dimension(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(output={"embeddings": [{"embedding": [0.1]}]})
    captured = _install_fake_sdk(monkeypatch, response)
    adapter = DashScopeMultiModalEmbeddingAdapter(
        {
            "api_key": "sk-dashscope-test",
            "base_url": "https://dashscope.aliyuncs.com/api/v1/services/embeddings",
            "model": "qwen3-vl-embedding",
            "dimensions": 0,
            "request_timeout": 5,
        }
    )

    await adapter.embed(
        EmbeddingRequest(texts=["hello"], model="qwen3-vl-embedding", enable_fusion=False)
    )

    assert "dimension" not in captured["kwargs"]
    assert captured["kwargs"].get("enable_fusion") is False
