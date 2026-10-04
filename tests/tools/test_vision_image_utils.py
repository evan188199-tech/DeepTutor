"""Unit tests for ``deeptutor.tools.vision.image_utils`` pure helpers and
network paths (all HTTP traffic is mocked)."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from deeptutor.tools.vision.image_utils import (
    MAX_IMAGE_SIZE,
    REQUEST_TIMEOUT,
    SUPPORTED_IMAGE_TYPES,
    ImageError,
    fetch_image_from_url,
    guess_image_type_from_url,
    image_bytes_to_base64,
    is_base64_image,
    is_valid_image_url,
    resolve_image_input,
    url_to_base64,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(
    content: bytes = b"img",
    content_type: str | None = "image/png",
    status_code: int = 200,
) -> MagicMock:
    """Build a mock ``httpx.Response`` with the given payload and headers."""
    response = MagicMock()
    response.status_code = status_code
    response.content = content
    response.headers = {} if content_type is None else {"content-type": content_type}
    response.raise_for_status = MagicMock()
    return response


def _patch_async_client(monkeypatch, response: MagicMock | None):
    """Patch ``httpx.AsyncClient`` used by image_utils; returns the client mock."""
    client = AsyncMock()
    if response is not None:
        client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        "deeptutor.tools.vision.image_utils.httpx.AsyncClient",
        MagicMock(return_value=client),
    )
    return client


def _raise_on_get(client: AsyncMock, exc: Exception) -> None:
    client.get = AsyncMock(side_effect=exc)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_supported_image_types_table() -> None:
    assert SUPPORTED_IMAGE_TYPES == {
        "image/jpeg": "jpeg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/gif": "gif",
        "image/webp": "webp",
    }


def test_limits_match_contract() -> None:
    assert MAX_IMAGE_SIZE == 10 * 1024 * 1024
    assert REQUEST_TIMEOUT == 30


# ---------------------------------------------------------------------------
# is_valid_image_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/img.png",
        "https://example.com/img.png",
        "https://example.com:8443/a/b/img.png?q=1#frag",
        "https://user:pass@example.com/secret.png",
        "http://localhost/img.png",
        "https://192.168.1.10/pic",
    ],
)
def test_is_valid_image_url_accepts_http_https(url: str) -> None:
    assert is_valid_image_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "",
        "ftp://example.com/img.png",
        "file:///etc/hostname",
        "data:image/png;base64,AAAA",
        "javascript:alert(1)",
        "//example.com/img.png",
        "example.com/img.png",
        "https://",
        "http:/missing-slash.com/x.png",
    ],
)
def test_is_valid_image_url_rejects_bad_schemes_or_hosts(url: str) -> None:
    assert is_valid_image_url(url) is False


def test_is_valid_image_url_non_string_returns_false() -> None:
    # None parses like an empty URL (no scheme); a non-str raises inside
    # urlparse and must be swallowed into the same False answer.
    assert is_valid_image_url(None) is False  # type: ignore[arg-type]
    assert is_valid_image_url(123) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# is_base64_image
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        "data:image/png;base64,iVBORw0KGgo=",
        "data:image/jpeg;base64,/9j/4AAQ",
        "data:image/webp;base64,UklGR",
        "data:image/png;base64,",  # format check only; empty payload still matches
    ],
)
def test_is_base64_image_accepts_data_urls(data: str) -> None:
    assert is_base64_image(data) is True


@pytest.mark.parametrize(
    "data",
    [
        "",
        "data:text/plain;base64,AAAA",
        "data:application/pdf;base64,AAAA",
        "data:image/png,not-base64",
        "image/png;base64,AAAA",
        "data:image/png;charset=utf-8,AAAA",
        "DATA:IMAGE/PNG;BASE64,AAAA",  # detection is case sensitive
        "data:video/mp4;base64,AAAA",
    ],
)
def test_is_base64_image_rejects_non_image_or_plain_data(data: str) -> None:
    assert is_base64_image(data) is False


# ---------------------------------------------------------------------------
# guess_image_type_from_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/a.png", "image/png"),
        ("https://example.com/a.PNG", "image/png"),
        ("https://example.com/a.jpg", "image/jpeg"),
        ("https://example.com/a.JPG", "image/jpeg"),
        ("https://example.com/a.jpeg", "image/jpeg"),
        ("https://example.com/a.gif", "image/gif"),
        ("https://example.com/a.webp", "image/webp"),
        ("https://example.com/a.png?size=large", "image/png"),
        ("https://example.com/no-extension", "image/jpeg"),  # default fallback
        ("https://example.com/a.bmp", "image/jpeg"),
    ],
)
def test_guess_image_type_from_url_extensions(url: str, expected: str) -> None:
    assert guess_image_type_from_url(url) == expected


def test_guess_image_type_from_url_first_match_wins() -> None:
    # ".png" is checked before the other extensions.
    assert guess_image_type_from_url("https://example.com/x.png.gif") == "image/png"
    assert guess_image_type_from_url("https://example.com/x.webp.jpg") == "image/jpeg"


# ---------------------------------------------------------------------------
# image_bytes_to_base64
# ---------------------------------------------------------------------------


def test_image_bytes_to_base64_known_payload() -> None:
    result = image_bytes_to_base64(b"hi", "image/png")
    assert result == f"data:image/png;base64,{base64.b64encode(b'hi').decode()}"
    assert result == "data:image/png;base64,aGk="


def test_image_bytes_to_base64_roundtrip() -> None:
    payload = bytes(range(256))
    result = image_bytes_to_base64(payload, "image/jpeg")
    header, _, encoded = result.partition(";base64,")
    assert header == "data:image/jpeg"
    assert base64.b64decode(encoded) == payload


@pytest.mark.parametrize("mime", sorted(SUPPORTED_IMAGE_TYPES))
def test_image_bytes_to_base64_preserves_mime_type(mime: str) -> None:
    result = image_bytes_to_base64(b"\x00\x01", mime)
    assert result.startswith(f"data:{mime};base64,")


def test_image_bytes_to_base64_empty_bytes() -> None:
    assert image_bytes_to_base64(b"", "image/gif") == "data:image/gif;base64,"


def test_image_bytes_to_base64_accepts_unlisted_mime() -> None:
    # No allow-list here: the function formats whatever mime it is given.
    result = image_bytes_to_base64(b"x", "image/svg+xml")
    assert result == f"data:image/svg+xml;base64,{base64.b64encode(b'x').decode()}"


# ---------------------------------------------------------------------------
# fetch_image_from_url (all network access mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_rejects_invalid_url_without_creating_client(monkeypatch) -> None:
    client = _patch_async_client(monkeypatch, None)
    with pytest.raises(ImageError, match="Invalid image URL"):
        await fetch_image_from_url("ftp://example.com/a.png")
    client.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_success_returns_content_and_mime(monkeypatch) -> None:
    response = _make_response(content=b"PNGDATA", content_type="image/png")
    client = _patch_async_client(monkeypatch, response)
    content, mime = await fetch_image_from_url("https://example.com/a.png")
    assert content == b"PNGDATA"
    assert mime == "image/png"
    client.get.assert_awaited_once_with("https://example.com/a.png")


@pytest.mark.asyncio
async def test_fetch_accepts_jpg_alias(monkeypatch) -> None:
    response = _make_response(content_type="image/jpg")
    _patch_async_client(monkeypatch, response)
    _, mime = await fetch_image_from_url("https://example.com/a.jpg")
    assert mime == "image/jpg"


@pytest.mark.asyncio
async def test_fetch_strips_charset_parameter(monkeypatch) -> None:
    response = _make_response(content_type="image/png; charset=binary")
    _patch_async_client(monkeypatch, response)
    _, mime = await fetch_image_from_url("https://example.com/a.png")
    assert mime == "image/png"


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type", [None, "", "application/octet-stream"])
async def test_fetch_missing_type_falls_back_to_url_guess(monkeypatch, content_type) -> None:
    response = _make_response(content_type=content_type)
    _patch_async_client(monkeypatch, response)
    _, mime = await fetch_image_from_url("https://example.com/photo.gif")
    assert mime == "image/gif"


@pytest.mark.asyncio
async def test_fetch_unsupported_format_raises(monkeypatch) -> None:
    response = _make_response(content_type="text/html")
    _patch_async_client(monkeypatch, response)
    with pytest.raises(ImageError, match="Unsupported image format: text/html"):
        await fetch_image_from_url("https://example.com/page.png")


@pytest.mark.asyncio
async def test_fetch_octet_stream_with_unknown_extension_raises(monkeypatch) -> None:
    # Fallback guess defaults to image/jpeg, which is supported, so use a URL
    # the guesser cannot map and assert the octet-stream header surfaces.
    response = _make_response(content_type="video/mp4")
    _patch_async_client(monkeypatch, response)
    with pytest.raises(ImageError, match="Unsupported image format: video/mp4"):
        await fetch_image_from_url("https://example.com/clip")


@pytest.mark.asyncio
async def test_fetch_oversized_image_raises(monkeypatch) -> None:
    response = _make_response(content=b"x" * (MAX_IMAGE_SIZE + 1), content_type="image/png")
    _patch_async_client(monkeypatch, response)
    with pytest.raises(ImageError, match="Image too large"):
        await fetch_image_from_url("https://example.com/huge.png")


@pytest.mark.asyncio
async def test_fetch_http_status_error_maps_to_image_error(monkeypatch) -> None:
    response = _make_response()
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Not Found",
        request=httpx.Request("GET", "https://example.com/a.png"),
        response=httpx.Response(404, request=httpx.Request("GET", "https://example.com/a.png")),
    )
    _patch_async_client(monkeypatch, response)
    with pytest.raises(ImageError, match="HTTP 404"):
        await fetch_image_from_url("https://example.com/a.png")


@pytest.mark.asyncio
async def test_fetch_timeout_maps_to_image_error(monkeypatch) -> None:
    client = _patch_async_client(monkeypatch, None)
    _raise_on_get(client, httpx.ReadTimeout("timed out"))
    with pytest.raises(ImageError, match="timeout"):
        await fetch_image_from_url("https://example.com/a.png")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError("connection refused"),
        httpx.TooManyRedirects("redirect loop"),
    ],
)
async def test_fetch_request_errors_map_to_image_error(monkeypatch, exc) -> None:
    client = _patch_async_client(monkeypatch, None)
    _raise_on_get(client, exc)
    with pytest.raises(ImageError, match="Failed to download image"):
        await fetch_image_from_url("https://example.com/a.png")


# ---------------------------------------------------------------------------
# url_to_base64
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_url_to_base64_converts_fetched_image(monkeypatch) -> None:
    response = _make_response(content=b"PNGDATA", content_type="image/png")
    _patch_async_client(monkeypatch, response)
    result = await url_to_base64("https://example.com/a.png")
    assert result == f"data:image/png;base64,{base64.b64encode(b'PNGDATA').decode()}"


@pytest.mark.asyncio
async def test_url_to_base64_propagates_invalid_url(monkeypatch) -> None:
    client = _patch_async_client(monkeypatch, None)
    with pytest.raises(ImageError, match="Invalid image URL"):
        await url_to_base64("not-a-url")
    client.get.assert_not_awaited()


# ---------------------------------------------------------------------------
# resolve_image_input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_prefers_base64_and_skips_download(monkeypatch) -> None:
    data_url = "data:image/png;base64,iVBORw0KGgo="
    client = _patch_async_client(monkeypatch, None)
    result = await resolve_image_input(image_base64=data_url, image_url="https://example.com/a.png")
    assert result == data_url
    client.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_invalid_base64_raises(monkeypatch) -> None:
    _patch_async_client(monkeypatch, None)
    with pytest.raises(ImageError, match="Invalid base64 image format"):
        await resolve_image_input(image_base64="plain-bytes-not-a-data-url")


@pytest.mark.asyncio
async def test_resolve_invalid_base64_ignores_url(monkeypatch) -> None:
    _patch_async_client(monkeypatch, None)
    with pytest.raises(ImageError, match="Invalid base64 image format"):
        await resolve_image_input(image_base64="oops", image_url="https://example.com/a.png")


@pytest.mark.asyncio
async def test_resolve_downloads_when_only_url_given(monkeypatch) -> None:
    response = _make_response(content=b"GIF89a", content_type="image/gif")
    client = _patch_async_client(monkeypatch, response)
    result = await resolve_image_input(image_url="https://example.com/anim.gif")
    assert result == f"data:image/gif;base64,{base64.b64encode(b'GIF89a').decode()}"
    client.get.assert_awaited_once_with("https://example.com/anim.gif")


@pytest.mark.asyncio
async def test_resolve_url_download_failure_propagates(monkeypatch) -> None:
    response = _make_response(content_type="text/html")
    _patch_async_client(monkeypatch, response)
    with pytest.raises(ImageError, match="Unsupported image format"):
        await resolve_image_input(image_url="https://example.com/a.png")


@pytest.mark.asyncio
async def test_resolve_no_input_returns_none(monkeypatch) -> None:
    client = _patch_async_client(monkeypatch, None)
    assert await resolve_image_input() is None
    assert await resolve_image_input(image_base64=None, image_url=None) is None
    client.get.assert_not_awaited()
