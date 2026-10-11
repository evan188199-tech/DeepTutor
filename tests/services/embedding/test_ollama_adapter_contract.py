"""Contract tests for the Ollama embedding adapter (local, keyless).

Fake transport only: ``httpx.AsyncClient`` is replaced, no real network.
Covers request-parameter construction (opt-in dimensions, keep_alive,
truncate), response parsing, and the failure branches (404 model lookup,
connect error, timeout).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from deeptutor.services.embedding.adapters.base import EmbeddingRequest
from deeptutor.services.embedding.adapters.ollama import OllamaEmbeddingAdapter

BASE_URL = "http://127.0.0.1:11434/api/embed"


class _FakeAsyncClient:
    """Stands in for ``httpx.AsyncClient`` with canned post/get responses."""

    post_responses: list[httpx.Response] = []
    tag_response: httpx.Response | Exception | None = None
    posts: list[dict[str, Any]] = []
    gets: list[str] = []

    def __init__(self, **_kwargs) -> None:  # noqa: ANN003
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def post(self, url: str, *, json: dict[str, Any], **_kwargs) -> httpx.Response:
        _FakeAsyncClient.posts.append({"url": url, "json": json})
        response = _FakeAsyncClient.post_responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def get(self, url: str) -> httpx.Response:
        _FakeAsyncClient.gets.append(url)
        probe = _FakeAsyncClient.tag_response
        if isinstance(probe, Exception):
            raise probe
        return probe or httpx.Response(200, json={}, request=httpx.Request("GET", url))


def _ok_response(vector: list[float], **extra: Any) -> httpx.Response:
    body: dict[str, Any] = {"embeddings": [vector], "model": "nomic-embed-text"}
    body.update(extra)
    return httpx.Response(200, json=body, request=httpx.Request("POST", BASE_URL))


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> type[_FakeAsyncClient]:
    _FakeAsyncClient.post_responses = []
    _FakeAsyncClient.tag_response = None
    _FakeAsyncClient.posts = []
    _FakeAsyncClient.gets = []
    monkeypatch.setattr(
        "deeptutor.services.embedding.adapters.ollama.httpx.AsyncClient", _FakeAsyncClient
    )
    return _FakeAsyncClient


def _make_adapter(**overrides: Any) -> OllamaEmbeddingAdapter:
    config: dict[str, Any] = {
        "api_key": "",
        "base_url": BASE_URL,
        "model": "nomic-embed-text",
        "request_timeout": 5,
    }
    config.update(overrides)
    return OllamaEmbeddingAdapter(config)


@pytest.mark.asyncio
async def test_ollama_payload_defaults_keep_alive_and_no_dimensions(fake_client) -> None:
    """Default request: `input`, model, keep_alive=5m, truncate=True, and NO
    `dimensions` unless the user opts in via `send_dimensions`."""
    fake_client.post_responses = [_ok_response([0.1, 0.2])]

    response = await _make_adapter(dimensions=768).embed(
        EmbeddingRequest(texts=["a", "b"], model="nomic-embed-text")
    )

    payload = fake_client.posts[0]["json"]
    assert payload["model"] == "nomic-embed-text"
    assert payload["input"] == ["a", "b"]
    assert payload["keep_alive"] == "5m"
    assert payload["truncate"] is True
    assert "dimensions" not in payload
    assert response.embeddings == [[0.1, 0.2]]


@pytest.mark.asyncio
async def test_ollama_sends_dimensions_only_when_opted_in(fake_client) -> None:
    fake_client.post_responses = [_ok_response([0.1, 0.2, 0.3])]

    await _make_adapter(dimensions=3, send_dimensions=True).embed(
        EmbeddingRequest(texts=["a"], model="nomic-embed-text", dimensions=3)
    )
    assert fake_client.posts[-1]["json"]["dimensions"] == 3


@pytest.mark.asyncio
async def test_ollama_omits_truncate_when_none(fake_client) -> None:
    fake_client.post_responses = [_ok_response([0.1, 0.2])]

    await _make_adapter().embed(
        EmbeddingRequest(texts=["a"], model="nomic-embed-text", truncate=None)
    )

    assert "truncate" not in fake_client.posts[0]["json"]


@pytest.mark.asyncio
async def test_ollama_response_usage_and_model_parsing(fake_client) -> None:
    fake_client.post_responses = [
        _ok_response([0.1, 0.2], prompt_eval_count=7, total_duration=12345)
    ]

    response = await _make_adapter().embed(EmbeddingRequest(texts=["a"], model="nomic-embed-text"))

    assert response.model == "nomic-embed-text"
    assert response.dimensions == 2
    assert response.usage == {"prompt_eval_count": 7, "total_duration": 12345}


@pytest.mark.asyncio
async def test_ollama_404_probes_tags_and_lists_available_models(fake_client) -> None:
    """Failure branch: a 404 triggers a `/api/tags` health check on the same
    host, and its model list is surfaced in the error."""
    fake_client.post_responses = [
        httpx.Response(
            404, json={"error": "model not found"}, request=httpx.Request("POST", BASE_URL)
        )
    ]
    fake_client.tag_response = httpx.Response(
        200,
        json={"models": [{"name": "all-minilm"}, {"name": "mxbai-embed-large"}]},
        request=httpx.Request("GET", "http://127.0.0.1:11434/api/tags"),
    )

    with pytest.raises(ValueError, match="not found in Ollama"):
        await _make_adapter().embed(EmbeddingRequest(texts=["a"], model="nomic-embed-text"))

    assert fake_client.gets == ["http://127.0.0.1:11434/api/tags"]


@pytest.mark.asyncio
async def test_ollama_404_with_failed_tags_probe_falls_back_to_generic_hint(
    fake_client,
) -> None:
    """Failure branch: when the tags probe itself fails, a plain pull hint."""
    fake_client.post_responses = [
        httpx.Response(404, json={}, request=httpx.Request("POST", BASE_URL))
    ]
    fake_client.tag_response = httpx.ConnectError("tags endpoint down")

    with pytest.raises(ValueError, match=r"Model 'nomic-embed-text' not found"):
        await _make_adapter().embed(EmbeddingRequest(texts=["a"], model="nomic-embed-text"))


@pytest.mark.asyncio
async def test_ollama_connect_error_maps_to_connection_error(fake_client) -> None:
    """Failure branch: server unreachable -> friendly ConnectionError."""
    fake_client.post_responses = [httpx.ConnectError("connection refused")]

    with pytest.raises(ConnectionError, match="Cannot connect to Ollama"):
        await _make_adapter().embed(EmbeddingRequest(texts=["a"], model="nomic-embed-text"))


@pytest.mark.asyncio
async def test_ollama_timeout_maps_to_timeout_error(fake_client) -> None:
    """Failure branch: read timeout -> TimeoutError naming the timeout."""
    fake_client.post_responses = [httpx.ReadTimeout("timed out")]

    with pytest.raises(TimeoutError, match="timed out after 5s"):
        await _make_adapter().embed(EmbeddingRequest(texts=["a"], model="nomic-embed-text"))


@pytest.mark.asyncio
async def test_ollama_forwards_extra_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    headers_seen: dict[str, str] = {}

    class _HeaderClient(_FakeAsyncClient):
        async def post(self, url: str, *, json: dict[str, Any], headers=None, **_kwargs):
            headers_seen.update(dict(headers or {}))
            return await super().post(url, json=json, headers=headers)

    monkeypatch.setattr(
        "deeptutor.services.embedding.adapters.ollama.httpx.AsyncClient", _HeaderClient
    )
    _FakeAsyncClient.post_responses = [_ok_response([0.1, 0.2])]

    await _make_adapter(extra_headers={"X-Cluster": "local"}).embed(
        EmbeddingRequest(texts=["a"], model="nomic-embed-text")
    )

    assert headers_seen == {"X-Cluster": "local"}


def test_ollama_get_model_info_reports_local_metadata() -> None:
    info = _make_adapter(model="mxbai-embed-large").get_model_info()
    assert info == {
        "model": "mxbai-embed-large",
        "dimensions": 1024,
        "local": True,
        "supports_variable_dimensions": False,
        "multimodal": False,
        "provider": "ollama",
    }
