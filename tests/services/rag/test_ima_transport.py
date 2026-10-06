"""Tests for the IMA transport layer: wire mechanics shared by every IMA call.

The client surface (method tables, payload parsing) is covered by
``test_ima_client_surface``; the envelope's status-code mapping is covered by
the same module. This module pins only what ``ImaTransport`` itself owns:

* request construction — the URL (prefix + method), the credential headers and
  the JSON body, for both the async and the blocking flavour;
* the failure branches that never reach the envelope — a transport-level 429,
  a non-2xx status, and a dead or malformed wire;
* the sync/async transport gating that keeps a blocking call from being handed
  a transport it cannot drive.

Everything runs against an injected ``httpx.MockTransport`` — no network.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from deeptutor.services.rag.pipelines.ima.config import ImaConfig
from deeptutor.services.rag.pipelines.ima.envelope import ImaAPIError, ImaRateLimitError
from deeptutor.services.rag.pipelines.ima.transport import (
    API_BASE_URL,
    DEFAULT_TIMEOUT,
    NOTE_PREFIX,
    WIKI_PREFIX,
    ImaTransport,
    _sync_transport,
    build_headers,
)

CONFIG = ImaConfig(client_id="cid", api_key="key", knowledge_base_id="kb-1")


def _transport(handler) -> ImaTransport:
    return ImaTransport(CONFIG, transport=httpx.MockTransport(handler))


def _responder(data: dict) -> httpx.Response:
    return httpx.Response(200, json={"code": 0, "msg": "ok", "data": data})


class TestBuildHeaders:
    def test_headers_carry_content_type_and_both_credentials(self) -> None:
        assert build_headers(CONFIG) == {
            "Content-Type": "application/json",
            "ima-openapi-clientid": "cid",
            "ima-openapi-apikey": "key",
        }


class TestRequestConstruction:
    def test_post_targets_the_wiki_prefix_by_default(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["method"] = request.method
            return _responder({"value": 1})

        assert asyncio.run(_transport(handler).post("search_knowledge", {"query": "q"})) == {
            "value": 1
        }

        assert seen["url"] == f"{API_BASE_URL}{WIKI_PREFIX}/search_knowledge"
        assert seen["method"] == "POST"

    def test_post_honours_the_note_prefix(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            return _responder({"doc_id": "n1"})

        note_id = asyncio.run(
            _transport(handler).post("import_doc", {"content": "hi"}, prefix=NOTE_PREFIX)
        )

        assert note_id == {"doc_id": "n1"}
        assert seen["url"] == f"{API_BASE_URL}{NOTE_PREFIX}/import_doc"

    def test_post_sends_json_body_and_credential_headers(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            seen["headers"] = dict(request.headers)
            return _responder({})

        asyncio.run(_transport(handler).post("search_knowledge", {"query": "plasma", "cursor": ""}))

        assert seen["body"] == {"query": "plasma", "cursor": ""}
        assert seen["headers"]["content-type"] == "application/json"
        assert seen["headers"]["ima-openapi-clientid"] == "cid"
        assert seen["headers"]["ima-openapi-apikey"] == "key"

    def test_post_sync_shares_the_same_wire_and_reuses_a_sync_capable_transport(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            seen["headers"] = dict(request.headers)
            return _responder({"value": 2})

        result = _transport(handler).post_sync("get_knowledge_list", {"knowledge_base_id": "kb-1"})

        assert result == {"value": 2}
        assert seen["url"] == f"{API_BASE_URL}{WIKI_PREFIX}/get_knowledge_list"
        assert seen["body"] == {"knowledge_base_id": "kb-1"}
        assert seen["headers"]["ima-openapi-apikey"] == "key"

    def test_default_timeout_is_thirty_seconds(self) -> None:
        assert ImaTransport(CONFIG).timeout == DEFAULT_TIMEOUT == 30.0


class TestTransportFailures:
    def test_transport_level_429_maps_to_the_rate_limit_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429)

        with pytest.raises(ImaRateLimitError):
            asyncio.run(_transport(handler).post("search_knowledge", {}))

    def test_transport_level_429_maps_the_same_way_when_blocking(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429)

        with pytest.raises(ImaRateLimitError):
            _transport(handler).post_sync("get_knowledge_list", {})

    def test_non_2xx_with_a_usable_error_envelope_still_maps_the_business_error(self) -> None:
        """The status code only names itself when the body is unusable."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"retcode": 110001, "errmsg": "参数非法"})

        with pytest.raises(ImaAPIError, match="参数非法"):
            asyncio.run(_transport(handler).post("search_knowledge", {}))

    def test_non_2xx_with_a_non_json_body_is_rejected_with_the_status_named(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, text="<html>Bad Gateway</html>")

        with pytest.raises(ImaAPIError, match="unexpected payload with status 502"):
            asyncio.run(_transport(handler).post("search_knowledge", {}))

    def test_malformed_json_body_is_rejected_with_the_status_named(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"{not json")

        with pytest.raises(ImaAPIError, match="unexpected payload with status 200"):
            asyncio.run(_transport(handler).post("search_knowledge", {}))

    def test_empty_body_is_rejected(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        with pytest.raises(ImaAPIError, match="unexpected payload"):
            _transport(handler).post_sync("get_knowledge_list", {})

    def test_wire_timeout_propagates_without_wrapping(self) -> None:
        """No retry/wrap layer exists here — the caller decides what to do."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        with pytest.raises(httpx.ReadTimeout):
            asyncio.run(_transport(handler).post("search_knowledge", {}))

        with pytest.raises(httpx.ReadTimeout):
            _transport(handler).post_sync("get_knowledge_list", {})


class TestSyncTransportGating:
    def test_a_sync_capable_transport_is_reused_for_blocking_calls(self) -> None:
        mock = httpx.MockTransport(lambda request: httpx.Response(200))

        assert _sync_transport(mock) is mock

    def test_an_async_only_transport_is_not_handed_to_blocking_calls(self) -> None:
        class AsyncOnly(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                return httpx.Response(200)

        async_only = AsyncOnly()

        assert _sync_transport(async_only) is None

    def test_the_async_flavour_still_drives_an_async_only_transport(self) -> None:
        class AsyncOnly(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                return _responder({"value": 3})

        result = asyncio.run(
            ImaTransport(CONFIG, transport=AsyncOnly()).post("search_knowledge", {})
        )

        assert result == {"value": 3}
