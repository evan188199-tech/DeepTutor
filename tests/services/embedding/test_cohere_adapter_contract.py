"""Contract tests for the Cohere embedding adapter (v1 and v2 request shapes).

Fake transport only: ``httpx.AsyncClient`` is replaced, no real network, no
real keys. Covers request-parameter construction, response parsing, and the
failure branches (HTTP errors, multimodal rejections).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from deeptutor.services.embedding.adapters.base import EmbeddingRequest
from deeptutor.services.embedding.adapters.cohere import CohereEmbeddingAdapter


class _FakeAsyncClient:
    """Stands in for ``httpx.AsyncClient`` and records every request."""

    calls: list[dict[str, Any]] = []
    post_responses: list[httpx.Response] = []

    def __init__(self, **_kwargs) -> None:  # noqa: ANN003
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def post(self, url: str, *, json: dict[str, Any], **_kwargs) -> httpx.Response:
        _FakeAsyncClient.calls.append({"url": url, "json": json})
        return _FakeAsyncClient.post_responses.pop(0)


def _ok_response(body: dict[str, Any], url: str) -> httpx.Response:
    return httpx.Response(200, json=body, request=httpx.Request("POST", url))


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> type[_FakeAsyncClient]:
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.post_responses = []
    monkeypatch.setattr(
        "deeptutor.services.embedding.adapters.cohere.httpx.AsyncClient", _FakeAsyncClient
    )
    return _FakeAsyncClient


def _make_adapter(**overrides: Any) -> CohereEmbeddingAdapter:
    config: dict[str, Any] = {
        "api_key": "co-test",
        "base_url": "https://api.cohere.test/v2/embed",
        "model": "embed-v4.0",
        "request_timeout": 5,
    }
    config.update(overrides)
    return CohereEmbeddingAdapter(config)


@pytest.mark.asyncio
async def test_cohere_v1_payload_sends_texts_and_truncate_none(fake_client) -> None:
    """v1 shape: flat ``texts`` + ``truncate=NONE``; vectors read from the top level."""
    fake_client.post_responses = [
        _ok_response(
            {
                "embeddings": [[0.1, 0.2], [0.3, 0.4]],
                "model": "embed-english-v3.0",
                "meta": {"billed_units": {"input_tokens": 2}},
            },
            "https://api.cohere.test/v1/embed",
        )
    ]
    adapter = _make_adapter(base_url="https://api.cohere.test/v1/embed", model="embed-english-v3.0")

    response = await adapter.embed(
        EmbeddingRequest(texts=["hello", "world"], model="embed-english-v3.0", truncate=False)
    )

    payload = fake_client.calls[0]["json"]
    assert payload["texts"] == ["hello", "world"]
    assert payload["model"] == "embed-english-v3.0"
    assert payload["input_type"] == "search_document"
    assert payload["truncate"] == "NONE"
    # v1 responses carry a plain list of vectors and Cohere's billed units.
    assert response.embeddings == [[0.1, 0.2], [0.3, 0.4]]
    assert response.dimensions == 2
    assert response.model == "embed-english-v3.0"
    assert response.usage == {"input_tokens": 2}


@pytest.mark.asyncio
async def test_cohere_v1_default_truncate_omits_the_key(fake_client) -> None:
    fake_client.post_responses = [
        _ok_response(
            {"embeddings": [[0.1, 0.2]], "model": "embed-english-v3.0"},
            "https://api.cohere.test/v1/embed",
        )
    ]
    adapter = _make_adapter(base_url="https://api.cohere.test/v1/embed", model="embed-english-v3.0")

    await adapter.embed(EmbeddingRequest(texts=["hello"], model="embed-english-v3.0"))

    assert "truncate" not in fake_client.calls[0]["json"]


@pytest.mark.asyncio
async def test_cohere_v2_payload_embedding_types_and_output_dimension(fake_client) -> None:
    """v2 shape: ``embedding_types`` + ``output_dimension`` for variable-dim models."""
    fake_client.post_responses = [
        _ok_response(
            {"embeddings": {"float": [[0.1, 0.2]]}, "model": "embed-v4.0"},
            "https://api.cohere.test/v2/embed",
        )
    ]

    response = await _make_adapter().embed(
        EmbeddingRequest(texts=["hello"], model="embed-v4.0", dimensions=2)
    )

    payload = fake_client.calls[0]["json"]
    assert payload["embedding_types"] == ["float"]
    assert payload["output_dimension"] == 2
    assert payload["texts"] == ["hello"]
    # Default truncate=True means the key is not force-set to NONE.
    assert "truncate" not in payload
    assert response.embeddings == [[0.1, 0.2]]
    assert response.model == "embed-v4.0"


@pytest.mark.asyncio
async def test_cohere_v2_omits_output_dimension_for_single_dim_model(fake_client) -> None:
    """An explicit ``api_version`` is a request-shape selector: a v1-catalog
    model forced onto the v2 shape keeps a fixed 1024-dim output, so the
    ``output_dimension`` param must stay absent."""
    fake_client.post_responses = [
        _ok_response(
            {"embeddings": {"float": [[0.1, 0.2]]}, "model": "embed-english-v3.0"},
            "https://api.cohere.test/v2/embed",
        )
    ]
    adapter = _make_adapter(model="embed-english-v3.0", api_version="v2")

    await adapter.embed(EmbeddingRequest(texts=["hello"], model="embed-english-v3.0"))

    assert "output_dimension" not in fake_client.calls[0]["json"]
    assert fake_client.calls[0]["json"]["embedding_types"] == ["float"]


@pytest.mark.asyncio
async def test_cohere_forwards_explicit_input_type(fake_client) -> None:
    fake_client.post_responses = [
        _ok_response(
            {"embeddings": {"float": [[0.1, 0.2]]}, "model": "embed-v4.0"},
            "https://api.cohere.test/v2/embed",
        )
    ]

    await _make_adapter().embed(
        EmbeddingRequest(
            texts=["query"], model="embed-v4.0", input_type="search_query", dimensions=2
        )
    )

    assert fake_client.calls[0]["json"]["input_type"] == "search_query"


@pytest.mark.asyncio
async def test_cohere_v1_rejects_multimodal_contents() -> None:
    """Failure branch: v1 models cannot take multimodal ``contents``."""
    adapter = _make_adapter(base_url="https://api.cohere.test/v1/embed", model="embed-english-v3.0")

    with pytest.raises(ValueError, match="v1 API does not support multimodal"):
        await adapter.embed(
            EmbeddingRequest(texts=[], model="embed-english-v3.0", contents=[{"text": "hi"}])
        )


@pytest.mark.asyncio
async def test_cohere_v2_rejects_unsupported_content_type() -> None:
    """Failure branch: only text/image items translate to v2 ``inputs``."""
    adapter = _make_adapter()

    with pytest.raises(ValueError, match="does not support content type 'video'"):
        await adapter.embed(
            EmbeddingRequest(texts=[], model="embed-v4.0", contents=[{"video": "https://v.mp4"}])
        )


@pytest.mark.asyncio
async def test_cohere_http_error_surfaces_as_http_status_error(fake_client) -> None:
    """Failure branch: >=400 responses raise via ``raise_for_status``."""
    fake_client.post_responses = [
        httpx.Response(500, json={"message": "boom"}, request=httpx.Request("POST", "x"))
    ]

    with pytest.raises(httpx.HTTPStatusError):
        await _make_adapter().embed(EmbeddingRequest(texts=["hello"], model="embed-v4.0"))

    assert len(fake_client.calls) == 1


@pytest.mark.asyncio
async def test_cohere_sends_bearer_auth_and_extra_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers_seen: dict[str, str] = {}

    class _HeaderClient(_FakeAsyncClient):
        async def post(self, url: str, *, json: dict[str, Any], headers=None, **_kwargs):
            headers_seen.update(dict(headers or {}))
            return await super().post(url, json=json, headers=headers)

    monkeypatch.setattr(
        "deeptutor.services.embedding.adapters.cohere.httpx.AsyncClient", _HeaderClient
    )
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.post_responses = [
        _ok_response(
            {"embeddings": {"float": [[0.1, 0.2]]}, "model": "embed-v4.0"},
            "https://api.cohere.test/v2/embed",
        )
    ]

    adapter = _make_adapter(extra_headers={"X-Obj-Class": "doc"})
    await adapter.embed(EmbeddingRequest(texts=["hello"], model="embed-v4.0", dimensions=2))

    assert headers_seen["Authorization"] == "Bearer co-test"
    assert headers_seen["Content-Type"] == "application/json"
    assert headers_seen["X-Obj-Class"] == "doc"


def test_cohere_get_model_info_reports_catalog_metadata() -> None:
    v4 = _make_adapter().get_model_info()
    assert v4 == {
        "model": "embed-v4.0",
        "dimensions": 1024,
        "supports_variable_dimensions": True,
        "multimodal": True,
        "provider": "cohere",
    }
    v3 = _make_adapter(model="embed-english-v3.0").get_model_info()
    assert v3["supports_variable_dimensions"] is False
    assert v3["multimodal"] is False
