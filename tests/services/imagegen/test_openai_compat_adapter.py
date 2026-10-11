"""Focused tests for the OpenAI-compatible imagegen adapter.

Covers request construction (URL join, optional payload fields, auth styles,
header merging, ``n`` clamping), response parsing (``b64_json`` / ``url``
shapes, mixed items) and the failure paths (missing endpoint, rate limit,
timeout, malformed responses, failed/empty downloads). All HTTP traffic is
faked via ``httpx.AsyncClient`` patching — no real network is touched.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest

from deeptutor.services.generation_http import (
    AUTH_API_KEY_HEADER,
    GenerationProviderError,
)
from deeptutor.services.imagegen.adapters.openai_compat import OpenAICompatImagegenAdapter
from deeptutor.services.imagegen.config import ImagegenConfig


def _config(**overrides: Any) -> ImagegenConfig:
    defaults: dict[str, Any] = {
        "model": "gpt-image-1",
        "base_url": "https://gateway.example/v1",
        "api_key": "sk-test",
    }
    defaults.update(overrides)
    return ImagegenConfig(**defaults)


def _patch_http(
    monkeypatch: pytest.MonkeyPatch,
    *,
    post: Any = None,
    get: Any = None,
) -> dict[str, Any]:
    """Patch ``httpx.AsyncClient`` post/get with url-agnostic fakes."""
    captured: dict[str, Any] = {"posts": [], "gets": []}

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["posts"].append(
            {"url": url, "json": kwargs.get("json"), "headers": kwargs.get("headers")}
        )
        if not callable(post):
            raise AssertionError("POST should not have been called")
        resp = post(url, kwargs)
        resp.request = httpx.Request("POST", url)
        return resp

    async def fake_get(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["gets"].append({"url": url})
        resp = get(url, kwargs)
        resp.request = httpx.Request("GET", url)
        return resp

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    return captured


def _b64(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


# ── request construction ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_base_url_rejected_without_http_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_http(monkeypatch)
    with pytest.raises(GenerationProviderError, match="No endpoint URL configured"):
        await OpenAICompatImagegenAdapter().generate("a cat", _config(base_url=""))
    assert captured["posts"] == []


@pytest.mark.asyncio
async def test_request_payload_and_headers_are_fully_constructed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resp = httpx.Response(200, json={"data": [{"b64_json": _b64(b"IMG")}]})
    captured = _patch_http(monkeypatch, post=lambda url, kwargs: resp)
    config = _config(
        auth_style=AUTH_API_KEY_HEADER,
        extra_headers={"X-Trace": "t-1"},
        size="512x512",
        quality="hd",
        style="vivid",
        response_format="b64_json",
    )
    images = await OpenAICompatImagegenAdapter().generate("a cat", config, n=3)

    assert images == [(b"IMG", "image/png")]
    post = captured["posts"][0]
    assert post["url"] == "https://gateway.example/v1/images/generations"
    assert post["json"] == {
        "model": "gpt-image-1",
        "prompt": "a cat",
        "n": 3,
        "size": "512x512",
        "quality": "hd",
        "style": "vivid",
        "response_format": "b64_json",
    }
    assert post["headers"]["api-key"] == "sk-test"
    assert "Authorization" not in post["headers"]
    assert post["headers"]["Content-Type"] == "application/json"
    assert post["headers"]["X-Trace"] == "t-1"


@pytest.mark.asyncio
async def test_optional_fields_omitted_when_unset_and_n_clamped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resp = httpx.Response(200, json={"data": [{"b64_json": _b64(b"IMG")}]})
    captured = _patch_http(monkeypatch, post=lambda url, kwargs: resp)
    await OpenAICompatImagegenAdapter().generate("a cat", _config(api_key=""), n=0)

    post = captured["posts"][0]
    assert post["json"] == {"model": "gpt-image-1", "prompt": "a cat", "n": 1}
    assert "Authorization" not in post["headers"]
    assert "api-key" not in post["headers"]


@pytest.mark.asyncio
async def test_full_generation_endpoint_base_url_is_used_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resp = httpx.Response(200, json={"data": [{"b64_json": _b64(b"IMG")}]})
    captured = _patch_http(monkeypatch, post=lambda url, kwargs: resp)
    config = _config(base_url="https://gateway.example/v1/images/generations?api-version=1")
    await OpenAICompatImagegenAdapter().generate("a cat", config)
    assert captured["posts"][0]["url"] == (
        "https://gateway.example/v1/images/generations?api-version=1"
    )


# ── response parsing ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mixed_b64_and_url_items_are_both_materialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post_resp = httpx.Response(
        200,
        json={
            "data": [
                {"b64_json": _b64(b"INLINE")},
                {"url": "https://cdn/remote.png"},
            ]
        },
    )
    get_resp = httpx.Response(
        200, content=b"REMOTE", headers={"content-type": "image/jpeg"}
    )
    captured = _patch_http(monkeypatch, post=lambda url, kwargs: post_resp,
                           get=lambda url, kwargs: get_resp)
    images = await OpenAICompatImagegenAdapter().generate("a cat", _config())

    assert images == [(b"INLINE", "image/png"), (b"REMOTE", "image/jpeg")]
    assert captured["gets"][0]["url"] == "https://cdn/remote.png"


@pytest.mark.asyncio
async def test_non_image_download_content_type_coerced_to_png(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post_resp = httpx.Response(200, json={"data": [{"url": "https://cdn/bin"}]})
    get_resp = httpx.Response(
        200, content=b"BYTES", headers={"content-type": "application/octet-stream"}
    )
    _patch_http(monkeypatch, post=lambda url, kwargs: post_resp,
                get=lambda url, kwargs: get_resp)
    images = await OpenAICompatImagegenAdapter().generate("a cat", _config())
    assert images == [(b"BYTES", "image/png")]


# ── failure / degradation branches ──────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        ["not", "a", "dict"],
        {"error": "no data key"},
        {"data": []},
        {"data": "not-a-list"},
    ],
)
async def test_malformed_response_bodies_are_rejected(
    monkeypatch: pytest.MonkeyPatch, body: Any
) -> None:
    _patch_http(monkeypatch, post=lambda url, kwargs: httpx.Response(200, json=body))
    with pytest.raises(GenerationProviderError, match="no `data` array"):
        await OpenAICompatImagegenAdapter().generate("a cat", _config())


@pytest.mark.asyncio
async def test_non_dict_items_only_yield_no_images_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_http(
        monkeypatch, post=lambda url, kwargs: httpx.Response(200, json={"data": ["x", 7]})
    )
    with pytest.raises(GenerationProviderError, match="returned no images"):
        await OpenAICompatImagegenAdapter().generate("a cat", _config())


@pytest.mark.asyncio
async def test_item_without_b64_or_url_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http(
        monkeypatch, post=lambda url, kwargs: httpx.Response(200, json={"data": [{}]})
    )
    with pytest.raises(GenerationProviderError, match="neither `b64_json` nor `url`"):
        await OpenAICompatImagegenAdapter().generate("a cat", _config())


@pytest.mark.asyncio
async def test_rate_limited_response_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http(
        monkeypatch,
        post=lambda url, kwargs: httpx.Response(429, text='{"error":"rate limited"}'),
    )
    with pytest.raises(GenerationProviderError, match="HTTP 429"):
        await OpenAICompatImagegenAdapter().generate("a cat", _config())


@pytest.mark.asyncio
async def test_timeout_error_is_wrapped_as_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def raise_timeout(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx.AsyncClient, "post", raise_timeout)
    with pytest.raises(GenerationProviderError, match="Image generation request error"):
        await OpenAICompatImagegenAdapter().generate("a cat", _config())


@pytest.mark.asyncio
async def test_invalid_inline_base64_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http(
        monkeypatch,
        post=lambda url, kwargs: httpx.Response(200, json={"data": [{"b64_json": "%%%bad%%%"}]}),
    )
    with pytest.raises(GenerationProviderError, match="invalid base64"):
        await OpenAICompatImagegenAdapter().generate("a cat", _config())


@pytest.mark.asyncio
async def test_url_download_http_failure_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post_resp = httpx.Response(200, json={"data": [{"url": "https://cdn/gone.png"}]})
    _patch_http(
        monkeypatch,
        post=lambda url, kwargs: post_resp,
        get=lambda url, kwargs: httpx.Response(403, text="forbidden"),
    )
    with pytest.raises(GenerationProviderError, match="Image download failed with HTTP 403"):
        await OpenAICompatImagegenAdapter().generate("a cat", _config())
