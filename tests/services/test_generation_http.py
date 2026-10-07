"""Contract tests for the generation HTTP layer (``services/generation_http.py``).

Locks the shared media-generation HTTP contract entirely on mocked ``httpx``
clients — no socket is opened:

- non-2xx error mapping via ``raise_for_provider`` (4xx/5xx, body trimming);
- timeout plumbing: every adapter forwards ``request_timeout`` to
  ``httpx.AsyncClient``, and stuck async tasks hit the ``poll_timeout``
  deadline and raise an actionable ``GenerationProviderError``;
- connection-error classification: transport failures are re-raised per
  action/adapter with the original ``httpx`` error chained as ``__cause__``;
- inline (``b64_json`` / data URI) vs. download (URL) materialization branches,
  including mid-flow download/poll failures. The generation cluster has no HTTP
  streaming branch on this tree (request/response only), so stream-interruption
  style contracts are locked by the mid-flow failure paths below.

The chat-completions 404-modality retry is covered by
``tests/services/imagegen/test_chat_completions_modalities.py`` and is not
duplicated here.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from deeptutor.services.generation_http import (
    AUTH_API_KEY_HEADER,
    AUTH_BEARER,
    GenerationProviderError,
    build_auth_headers,
    decode_base64_media,
    join_api_path,
    raise_for_provider,
)
from deeptutor.services.imagegen.adapters.chat_completions import ChatCompletionsImagegenAdapter
from deeptutor.services.imagegen.adapters.dashscope import DashScopeImagegenAdapter
from deeptutor.services.imagegen.adapters.openai_compat import OpenAICompatImagegenAdapter
from deeptutor.services.imagegen.config import ImagegenConfig
from deeptutor.services.videogen.adapters.async_task import AsyncTaskVideogenAdapter
from deeptutor.services.videogen.adapters.dashscope import DashScopeVideogenAdapter
from deeptutor.services.videogen.config import VideogenConfig


def _image_config(**overrides: Any) -> ImagegenConfig:
    defaults: dict[str, Any] = {
        "model": "m",
        "base_url": "https://img.example/v1",
        "api_key": "k",
        "poll_interval": 0.0,
    }
    defaults.update(overrides)
    return ImagegenConfig(**defaults)


def _video_config(**overrides: Any) -> VideogenConfig:
    defaults: dict[str, Any] = {
        "model": "m",
        "base_url": "https://vid.example/v3",
        "api_key": "k",
        "poll_interval": 0.0,
    }
    defaults.update(overrides)
    return VideogenConfig(**defaults)


def _patch_http(
    monkeypatch: pytest.MonkeyPatch,
    *,
    post: Any = None,
    get: Any = None,
) -> dict[str, list[dict[str, Any]]]:
    """Patch ``httpx.AsyncClient`` post/get with mock responders.

    Each of ``post``/``get`` may be an ``httpx.Response``, an exception instance
    to raise, or a callable ``(url, kwargs) -> Response``; routers may also
    raise or return an exception to simulate transport failures.
    """
    captured: dict[str, list[dict[str, Any]]] = {"posts": [], "gets": []}

    def _resolve(responder: Any, method: str, url: str, kwargs: dict[str, Any]) -> httpx.Response:
        resp = responder(url, kwargs) if callable(responder) else responder
        if isinstance(resp, Exception):
            raise resp
        resp.request = httpx.Request(method, url)
        return resp

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["posts"].append({"url": url, **kwargs})
        return _resolve(post, "POST", url, kwargs)

    async def fake_get(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["gets"].append({"url": url, **kwargs})
        return _resolve(get, "GET", url, kwargs)

    if post is not None:
        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    if get is not None:
        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    return captured


def _capture_client_init(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record every ``httpx.AsyncClient(**kwargs)`` construction."""
    sink: list[dict[str, Any]] = []
    original = httpx.AsyncClient.__init__

    def patched(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        sink.append(kwargs)
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)
    return sink


# ── non-2xx error mapping (raise_for_provider) ──────────────────────────────


@pytest.mark.parametrize("status", [200, 201, 204, 302])
def test_raise_for_provider_allows_below_400(status: int) -> None:
    raise_for_provider(httpx.Response(status, text="ok"), "Image generation")


@pytest.mark.parametrize(
    ("status", "detail"),
    [
        (400, "invalid size"),
        (401, "bad api key"),
        (404, "no such model"),
        (429, "rate limited"),
    ],
)
def test_raise_for_provider_maps_4xx(status: int, detail: str) -> None:
    resp = httpx.Response(status, text=detail)
    with pytest.raises(GenerationProviderError, match=f"HTTP {status}: {detail}"):
        raise_for_provider(resp, "Image generation")


@pytest.mark.parametrize(
    ("status", "detail"),
    [
        (500, "upstream exploded"),
        (502, "bad gateway"),
        (503, "capacity exhausted"),
    ],
)
def test_raise_for_provider_maps_5xx(status: int, detail: str) -> None:
    resp = httpx.Response(status, text=detail)
    with pytest.raises(GenerationProviderError, match=f"HTTP {status}: {detail}"):
        raise_for_provider(resp, "Video download")


def test_raise_for_provider_trims_long_bodies_to_400_chars() -> None:
    body = "x" * 1000
    with pytest.raises(GenerationProviderError) as excinfo:
        raise_for_provider(httpx.Response(500, text=f"  {body}  "), "Image generation")
    assert str(excinfo.value) == f"Image generation failed with HTTP 500: {'x' * 400}"


def test_raise_for_provider_without_body_uses_period() -> None:
    with pytest.raises(GenerationProviderError) as excinfo:
        raise_for_provider(httpx.Response(429), "Image generation")
    assert str(excinfo.value) == "Image generation failed with HTTP 429."


# ── payload / auth / URL helper contracts ───────────────────────────────────


def test_decode_base64_media_roundtrip_and_rejects_whitespace() -> None:
    import base64

    payload = base64.b64encode(b"MEDIABYTES").decode("ascii")
    assert decode_base64_media(payload, "Image generation") == b"MEDIABYTES"
    with pytest.raises(GenerationProviderError, match="invalid base64"):
        decode_base64_media("aGVs bG8=", "Image generation")


def test_build_auth_headers_empty_api_key_header_style() -> None:
    assert AUTH_BEARER == "bearer"
    assert AUTH_API_KEY_HEADER == "api_key_header"
    assert build_auth_headers(AUTH_API_KEY_HEADER, "") == {}
    assert build_auth_headers("unknown-style", "k") == {"Authorization": "Bearer k"}


def test_join_api_path_preserves_query_string() -> None:
    assert (
        join_api_path("https://ark.example/api/v3?region=cn", "images/generations")
        == "https://ark.example/api/v3/images/generations?region=cn"
    )
    full = "https://ark.example/api/v3/images/generations?region=cn"
    assert join_api_path(full, "images/generations") == full


def test_join_api_path_normalizes_slashes_and_rejects_empty_base() -> None:
    assert (
        join_api_path("https://api.example/v1//", "/images/generations/")
        == "https://api.example/v1/images/generations"
    )
    with pytest.raises(GenerationProviderError, match="No endpoint URL configured"):
        join_api_path("  ", "images/generations")


# ── timeout plumbing ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_imagegen_request_timeout_reaches_async_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_kwargs = _capture_client_init(monkeypatch)
    _patch_http(
        monkeypatch,
        post=httpx.Response(200, json={"data": [{"b64_json": "aGVsbG8="}]}),
    )
    await OpenAICompatImagegenAdapter().generate("x", _image_config(request_timeout=42))
    assert init_kwargs[-1]["timeout"] == 42


@pytest.mark.asyncio
async def test_chat_completions_request_timeout_reaches_async_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_kwargs = _capture_client_init(monkeypatch)
    data_uri = "data:image/png;base64,aGVsbG8="
    _patch_http(
        monkeypatch,
        post=httpx.Response(
            200,
            json={"choices": [{"message": {"images": [{"image_url": {"url": data_uri}}]}}]},
        ),
    )
    await ChatCompletionsImagegenAdapter().generate("x", _image_config(request_timeout=17))
    assert init_kwargs[-1]["timeout"] == 17


@pytest.mark.asyncio
async def test_videogen_request_timeout_reaches_async_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_kwargs = _capture_client_init(monkeypatch)
    submit = httpx.Response(200, json={"id": "t-timeout"})
    poll = httpx.Response(
        200, json={"status": "succeeded", "content": {"video_url": "https://cdn/v.mp4"}}
    )
    download = httpx.Response(200, content=b"MP4", headers={"content-type": "video/mp4"})
    _patch_http(
        monkeypatch, post=submit, get=lambda url, kwargs: poll if "tasks/" in url else download
    )
    await AsyncTaskVideogenAdapter().generate("x", _video_config(request_timeout=61))
    assert init_kwargs, "expected at least one AsyncClient construction"
    assert {kw["timeout"] for kw in init_kwargs} == {61}


@pytest.mark.asyncio
async def test_dashscope_videogen_request_timeout_reaches_async_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_kwargs = _capture_client_init(monkeypatch)
    submit = httpx.Response(200, json={"output": {"task_id": "ds-timeout"}})
    poll = httpx.Response(
        200, json={"output": {"task_status": "SUCCEEDED", "video_url": "https://cdn/v.mp4"}}
    )
    download = httpx.Response(200, content=b"MP4", headers={"content-type": "video/mp4"})
    _patch_http(
        monkeypatch, post=submit, get=lambda url, kwargs: poll if "tasks/" in url else download
    )
    await DashScopeVideogenAdapter().generate(
        "x", _video_config(model="wanx2.1-t2v-turbo", request_timeout=7)
    )
    assert {kw["timeout"] for kw in init_kwargs} == {7}


@pytest.mark.asyncio
async def test_videogen_poll_timeout_deadline_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submit = httpx.Response(200, json={"id": "t-stuck"})
    rendering = httpx.Response(200, json={"status": "rendering"})
    _patch_http(monkeypatch, post=submit, get=rendering)
    with pytest.raises(
        GenerationProviderError,
        match=r"Video task t-stuck timed out after 0s \(last status: rendering\)",
    ):
        await AsyncTaskVideogenAdapter().generate("x", _video_config(poll_timeout=0))


@pytest.mark.asyncio
async def test_dashscope_imagegen_poll_timeout_deadline_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submit = httpx.Response(200, json={"output": {"task_id": "img-stuck"}})
    running = httpx.Response(200, json={"output": {"task_status": "RUNNING"}})
    _patch_http(monkeypatch, post=submit, get=running)
    with pytest.raises(
        GenerationProviderError,
        match=r"DashScope image task img-stuck timed out after 0s \(last status: running\)",
    ):
        await DashScopeImagegenAdapter().generate(
            "x", _image_config(adapter="dashscope", poll_timeout=0)
        )


@pytest.mark.asyncio
async def test_dashscope_videogen_poll_timeout_deadline_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submit = httpx.Response(200, json={"output": {"task_id": "vid-stuck"}})
    running = httpx.Response(200, json={"output": {"task_status": "RUNNING"}})
    _patch_http(monkeypatch, post=submit, get=running)
    with pytest.raises(
        GenerationProviderError,
        match=r"DashScope video task vid-stuck timed out after 0s \(last status: running\)",
    ):
        await DashScopeVideogenAdapter().generate(
            "x", _video_config(model="wanx2.1-t2v-turbo", poll_timeout=0)
        )


# ── connection-error classification ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_imagegen_connect_error_is_classified_with_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boom = httpx.ConnectError("connection refused")
    _patch_http(monkeypatch, post=boom)
    with pytest.raises(GenerationProviderError, match="Image generation request error: ") as info:
        await OpenAICompatImagegenAdapter().generate("x", _image_config())
    assert isinstance(info.value.__cause__, httpx.ConnectError)


@pytest.mark.asyncio
async def test_imagegen_download_transport_error_is_classified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post = httpx.Response(200, json={"data": [{"url": "https://cdn/x.png"}]})
    _patch_http(monkeypatch, post=post, get=httpx.ReadTimeout("peer stalled"))
    with pytest.raises(GenerationProviderError, match="Image generation request error: "):
        await OpenAICompatImagegenAdapter().generate("x", _image_config())


@pytest.mark.asyncio
async def test_videogen_submit_connect_error_is_classified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_http(monkeypatch, post=httpx.ConnectError("dns failure"))
    with pytest.raises(GenerationProviderError, match="Video task submission error: "):
        await AsyncTaskVideogenAdapter().generate("x", _video_config())


@pytest.mark.asyncio
async def test_videogen_poll_transport_error_is_classified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submit = httpx.Response(200, json={"id": "t-net"})
    _patch_http(monkeypatch, post=submit, get=httpx.ReadTimeout("reset by peer"))
    with pytest.raises(GenerationProviderError, match="Video generation request error: "):
        await AsyncTaskVideogenAdapter().generate("x", _video_config())


@pytest.mark.asyncio
async def test_dashscope_imagegen_transport_error_is_classified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_http(monkeypatch, post=httpx.ConnectTimeout("gateway unreachable"))
    with pytest.raises(GenerationProviderError, match="DashScope image request error: "):
        await DashScopeImagegenAdapter().generate(
            "x", _image_config(adapter="dashscope", provider_name="dashscope")
        )


@pytest.mark.asyncio
async def test_dashscope_videogen_submit_transport_error_is_classified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_http(monkeypatch, post=httpx.ReadTimeout("gateway timeout"))
    with pytest.raises(GenerationProviderError, match="DashScope video submission error: "):
        await DashScopeVideogenAdapter().generate("x", _video_config(model="wanx2.1-t2v-turbo"))


@pytest.mark.asyncio
async def test_dashscope_videogen_download_transport_error_is_classified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submit = httpx.Response(200, json={"output": {"task_id": "ds-net"}})
    poll = httpx.Response(
        200, json={"output": {"task_status": "SUCCEEDED", "video_url": "https://cdn/v.mp4"}}
    )
    _patch_http(
        monkeypatch,
        post=submit,
        get=lambda url, kwargs: poll if "tasks/" in url else httpx.ConnectError("cdn refused"),
    )
    with pytest.raises(GenerationProviderError, match="DashScope video request error: "):
        await DashScopeVideogenAdapter().generate("x", _video_config(model="wanx2.1-t2v-turbo"))


# ── inline vs. download materialization branches / mid-flow failures ───────


@pytest.mark.asyncio
async def test_imagegen_url_download_http_error_surfaces_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post = httpx.Response(200, json={"data": [{"url": "https://cdn/x.png"}]})
    _patch_http(monkeypatch, post=post, get=httpx.Response(502, text="cdn hiccup"))
    with pytest.raises(
        GenerationProviderError, match="Image download failed with HTTP 502: cdn hiccup"
    ):
        await OpenAICompatImagegenAdapter().generate("x", _image_config())


@pytest.mark.asyncio
async def test_imagegen_item_without_media_source_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_http(monkeypatch, post=httpx.Response(200, json={"data": [{}]}))
    with pytest.raises(GenerationProviderError, match="neither `b64_json` nor `url`"):
        await OpenAICompatImagegenAdapter().generate("x", _image_config())


@pytest.mark.asyncio
async def test_imagegen_empty_data_array_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_http(monkeypatch, post=httpx.Response(200, json={"data": []}))
    with pytest.raises(GenerationProviderError, match="had no `data` array"):
        await OpenAICompatImagegenAdapter().generate("x", _image_config())


@pytest.mark.asyncio
async def test_imagegen_non_dict_data_rows_yield_no_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_http(monkeypatch, post=httpx.Response(200, json={"data": ["junk"]}))
    with pytest.raises(GenerationProviderError, match="returned no images"):
        await OpenAICompatImagegenAdapter().generate("x", _image_config())


@pytest.mark.asyncio
async def test_chat_completions_malformed_data_uri_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resp = httpx.Response(
        200,
        json={
            "choices": [{"message": {"images": [{"image_url": {"url": "data:image/png;base64,"}}]}}]
        },
    )
    _patch_http(monkeypatch, post=resp)
    with pytest.raises(GenerationProviderError, match="Malformed image data URI"):
        await ChatCompletionsImagegenAdapter().generate(
            "x", _image_config(adapter="chat_completions")
        )


@pytest.mark.asyncio
async def test_chat_completions_non_image_data_uri_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resp = httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"images": [{"image_url": {"url": "data:text/html;base64,PGI+"}}]}}
            ]
        },
    )
    _patch_http(monkeypatch, post=resp)
    with pytest.raises(GenerationProviderError, match="non-image content type"):
        await ChatCompletionsImagegenAdapter().generate(
            "x", _image_config(adapter="chat_completions")
        )


@pytest.mark.asyncio
async def test_chat_completions_content_part_http_download_empty_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resp = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": [
                            {"image_url": {"url": "https://cdn/part.png"}},
                        ]
                    }
                }
            ]
        },
    )
    _patch_http(
        monkeypatch,
        post=resp,
        get=httpx.Response(200, content=b"", headers={"content-type": "image/png"}),
    )
    with pytest.raises(GenerationProviderError, match="Image download returned empty data"):
        await ChatCompletionsImagegenAdapter().generate(
            "x", _image_config(adapter="chat_completions")
        )


@pytest.mark.asyncio
async def test_chat_completions_message_without_image_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resp = httpx.Response(200, json={"choices": [{"message": {"content": "no picture for you"}}]})
    _patch_http(monkeypatch, post=resp)
    with pytest.raises(GenerationProviderError, match="no image in the assistant message"):
        await ChatCompletionsImagegenAdapter().generate(
            "x", _image_config(adapter="chat_completions")
        )


@pytest.mark.asyncio
async def test_videogen_empty_download_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submit = httpx.Response(200, json={"id": "t-empty"})
    poll = httpx.Response(
        200, json={"status": "succeeded", "content": {"video_url": "https://cdn/v.mp4"}}
    )
    _patch_http(
        monkeypatch,
        post=submit,
        get=lambda url, kwargs: (
            poll
            if "tasks/" in url
            else httpx.Response(200, content=b"", headers={"content-type": "video/mp4"})
        ),
    )
    with pytest.raises(GenerationProviderError, match="returned an empty file"):
        await AsyncTaskVideogenAdapter().generate("x", _video_config())


@pytest.mark.asyncio
async def test_videogen_non_video_content_type_is_coerced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submit = httpx.Response(200, json={"id": "t-coerce"})
    poll = httpx.Response(
        200, json={"status": "succeeded", "content": {"video_url": "https://cdn/v.bin"}}
    )
    _patch_http(
        monkeypatch,
        post=submit,
        get=lambda url, kwargs: (
            poll
            if "tasks/" in url
            else httpx.Response(
                200, content=b"BYTES", headers={"content-type": "application/octet-stream"}
            )
        ),
    )
    video, content_type = await AsyncTaskVideogenAdapter().generate("x", _video_config())
    assert video == b"BYTES"
    assert content_type == "video/mp4"


@pytest.mark.parametrize("state", ["cancelled", "expired", "error"])
@pytest.mark.asyncio
async def test_videogen_terminal_failure_states_are_actionable(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    submit = httpx.Response(200, json={"id": "t-dead"})
    failed = httpx.Response(200, json={"status": state})
    _patch_http(monkeypatch, post=submit, get=failed)
    with pytest.raises(GenerationProviderError, match=f"Video task t-dead {state}: "):
        await AsyncTaskVideogenAdapter().generate("x", _video_config())


def test_videogen_extract_task_id_variants() -> None:
    extract = AsyncTaskVideogenAdapter._extract_task_id
    assert extract(httpx.Response(200, json={"task_id": "outer"})) == "outer"
    assert extract(httpx.Response(200, json={"data": {"id": "nested"}})) == "nested"
    with pytest.raises(GenerationProviderError, match="no task id"):
        extract(httpx.Response(200, json={}))


def test_videogen_extract_status_variants() -> None:
    extract = AsyncTaskVideogenAdapter._extract_status
    assert extract(httpx.Response(200, json={"state": "RUNNING"})) == ("running", "", "")
    status, url, error = extract(
        httpx.Response(200, json={"status": "failed", "error": {"message": "nope"}})
    )
    assert (status, url, error) == ("failed", "", "nope")
    status, url, _ = extract(
        httpx.Response(200, json={"status": "succeeded", "url": "https://c/v"})
    )
    assert (status, url) == ("succeeded", "https://c/v")


@pytest.mark.asyncio
async def test_dashscope_imagegen_download_empty_body_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submit = httpx.Response(200, json={"output": {"task_id": "img-empty"}})
    poll = httpx.Response(
        200,
        json={"output": {"task_status": "SUCCEEDED", "results": [{"url": "https://cdn/i.png"}]}},
    )
    _patch_http(
        monkeypatch,
        post=submit,
        get=lambda url, kwargs: (
            poll
            if "tasks/" in url
            else httpx.Response(200, content=b"", headers={"content-type": "image/png"})
        ),
    )
    with pytest.raises(
        GenerationProviderError, match="DashScope image download returned empty data"
    ):
        await DashScopeImagegenAdapter().generate(
            "x", _image_config(adapter="dashscope", provider_name="dashscope")
        )


@pytest.mark.asyncio
async def test_dashscope_videogen_download_empty_body_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submit = httpx.Response(200, json={"output": {"task_id": "vid-empty"}})
    poll = httpx.Response(
        200, json={"output": {"task_status": "SUCCEEDED", "video_url": "https://cdn/v.mp4"}}
    )
    _patch_http(
        monkeypatch,
        post=submit,
        get=lambda url, kwargs: (
            poll
            if "tasks/" in url
            else httpx.Response(200, content=b"", headers={"content-type": "video/mp4"})
        ),
    )
    with pytest.raises(
        GenerationProviderError, match="DashScope video download returned empty data"
    ):
        await DashScopeVideogenAdapter().generate("x", _video_config(model="wanx2.1-t2v-turbo"))
