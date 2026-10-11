"""Focused unit tests for ZoteroSearchClient query construction and parsing.

All requests go through an injected fake client factory; no network is used.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from deeptutor.tools.zotero_search import (
    ZOTERO_API_BASE,
    ZoteroSearchClient,
    ZoteroSearchError,
)


class FakeResponse:
    def __init__(
        self,
        payload: Any = None,
        status_code: int = 200,
        json_error: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.json_error = json_error

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", ZOTERO_API_BASE),
                response=httpx.Response(self.status_code),
            )

    def json(self) -> Any:
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class FakeClient:
    def __init__(self, response: FakeResponse, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.url: str | None = None
        self.headers: dict[str, str] = {}
        self.params: dict[str, Any] = {}

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, *, headers: dict, params: dict) -> FakeResponse:
        if self.error is not None:
            raise self.error
        self.url = url
        self.headers = headers
        self.params = params
        return self.response


def _item(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "key": "ABCD1234",
        "itemType": "journalArticle",
        "title": "Attention Is All You Need",
        "creators": [{"firstName": "Ashish", "lastName": "Vaswani"}],
        "date": "2017-06-12",
        "DOI": "10.5555/example",
        "url": "https://example.com/paper",
        "abstractNote": "A compact abstract.",
    }
    data.update(overrides)
    return {"key": "OUTER1", "data": data, "links": {"alternate": {"href": "https://alt"}}}


def _client(response: FakeResponse, error: Exception | None = None) -> FakeClient:
    return FakeClient(response, error)


class TestQueryConstruction:
    @pytest.mark.asyncio
    async def test_builds_params_and_strips_inputs(self) -> None:
        client = _client(FakeResponse([_item()]))

        await ZoteroSearchClient(lambda: client).search(
            query="  attention is all you need  ",
            user_id=" 12345 ",
        )

        assert client.url == f"{ZOTERO_API_BASE}/users/12345/items/top"
        assert client.headers["Zotero-API-Version"] == "3"
        assert "Authorization" not in client.headers
        assert client.params == {
            "format": "json",
            "itemType": "-attachment",
            "limit": 5,
            "q": "attention is all you need",
            "qmode": "titleCreatorYear",
        }

    @pytest.mark.asyncio
    async def test_sends_bearer_token_when_api_key_given(self) -> None:
        client = _client(FakeResponse([]))

        await ZoteroSearchClient(lambda: client).search(
            query="attention",
            user_id="12345",
            api_key="secret-key",
        )

        assert client.headers["Authorization"] == "Bearer secret-key"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (1, 1),
            (5, 5),
            (25, 25),
            (0, 1),
            (-3, 1),
            (26, 25),
            (999, 25),
            ("3", 3),
        ],
    )
    @pytest.mark.asyncio
    async def test_clamps_max_results_between_one_and_max(self, raw: Any, expected: int) -> None:
        client = _client(FakeResponse([]))

        await ZoteroSearchClient(lambda: client).search(
            query="attention",
            user_id="12345",
            max_results=raw,
        )

        assert client.params["limit"] == expected

    @pytest.mark.parametrize(
        ("kwargs", "match"),
        [
            ({"query": "", "user_id": "12345"}, "non-empty"),
            ({"query": "   ", "user_id": "12345"}, "non-empty"),
            ({"query": "attention", "user_id": ""}, "user ID"),
            ({"query": "attention", "user_id": "a/b"}, "user ID"),
            ({"query": "attention", "user_id": "with space"}, "user ID"),
            ({"query": "attention", "user_id": "12345", "max_results": "abc"}, "max_results"),
            ({"query": "attention", "user_id": "12345", "max_results": None}, "max_results"),
        ],
    )
    @pytest.mark.asyncio
    async def test_rejects_invalid_inputs_before_request(self, kwargs: dict, match: str) -> None:
        client = _client(FakeResponse([]))

        with pytest.raises(ValueError, match=match):
            await ZoteroSearchClient(lambda: client).search(**kwargs)

        assert client.url is None


class TestFailureBranches:
    @pytest.mark.parametrize(
        ("status", "expected_code"),
        [
            (401, "invalid_api_key"),
            (403, "invalid_api_key"),
            (404, "library_not_found"),
            (429, "rate_limited"),
            (500, "request_failed"),
            (503, "request_failed"),
        ],
    )
    @pytest.mark.asyncio
    async def test_maps_http_status_to_normalized_errors(
        self, status: int, expected_code: str
    ) -> None:
        client = _client(FakeResponse([], status_code=status))

        with pytest.raises(ZoteroSearchError) as exc_info:
            await ZoteroSearchClient(lambda: client).search(query="attention", user_id="12345")

        assert exc_info.value.code == expected_code
        assert exc_info.value.status_code == status

    @pytest.mark.parametrize(
        "error",
        [
            httpx.ReadTimeout("timed out"),
            httpx.ConnectError("connection refused"),
            httpx.RemoteProtocolError("bad response"),
        ],
    )
    @pytest.mark.asyncio
    async def test_maps_transport_errors_to_network_unavailable(self, error: Exception) -> None:
        client = _client(FakeResponse([]), error=error)

        with pytest.raises(ZoteroSearchError) as exc_info:
            await ZoteroSearchClient(lambda: client).search(query="attention", user_id="12345")

        assert exc_info.value.code == "network_unavailable"
        assert exc_info.value.status_code is None

    @pytest.mark.asyncio
    async def test_maps_non_json_body_to_invalid_response(self) -> None:
        client = _client(FakeResponse(json_error=ValueError("not JSON")))

        with pytest.raises(ZoteroSearchError, match="invalid_response"):
            await ZoteroSearchClient(lambda: client).search(query="attention", user_id="12345")

    @pytest.mark.asyncio
    async def test_rejects_non_list_payload(self) -> None:
        client = _client(FakeResponse({"items": []}))

        with pytest.raises(ZoteroSearchError, match="invalid_response"):
            await ZoteroSearchClient(lambda: client).search(query="attention", user_id="12345")


class TestResponseParsing:
    @pytest.mark.asyncio
    async def test_filters_entries_without_dict_shape(self) -> None:
        payload: list[Any] = [
            None,
            "not-an-item",
            42,
            {},
            {"data": "scalar-data"},
            {"no_data_key": True},
            _item(title="Kept Item"),
        ]
        client = _client(FakeResponse(payload))

        items = await ZoteroSearchClient(lambda: client).search(query="attention", user_id="12345")

        assert [item["title"] for item in items] == ["Kept Item"]

    @pytest.mark.asyncio
    async def test_normalize_collects_single_name_and_pair_creators(self) -> None:
        item = _item(
            creators=[
                {"name": "Ada Lovelace"},
                {"firstName": "Grace", "lastName": "Hopper"},
                {"name": "   "},
                {},
                "not-a-dict",
            ]
        )
        client = _client(FakeResponse([item]))

        items = await ZoteroSearchClient(lambda: client).search(query="attention", user_id="12345")

        assert items[0]["authors"] == ["Ada Lovelace", "Grace Hopper"]

    @pytest.mark.asyncio
    async def test_normalize_defaults_missing_metadata(self) -> None:
        item = _item(creators=[], date="", title="")
        del item["links"]
        client = _client(FakeResponse([item]))

        items = await ZoteroSearchClient(lambda: client).search(query="attention", user_id="12345")

        assert items[0]["title"] == "Untitled"
        assert items[0]["authors"] == []
        assert items[0]["year"] == ""
        assert items[0]["zotero_url"] == ""
        assert items[0]["item_type"] == "journalArticle"
        assert items[0]["doi"] == "10.5555/example"
        assert items[0]["abstract"] == "A compact abstract."
        assert items[0]["zotero_key"] == "ABCD1234"

    @pytest.mark.asyncio
    async def test_normalize_extracts_year_from_leading_year_date(self) -> None:
        client = _client(FakeResponse([_item(date="1999 (Published by MIT Press)")]))

        items = await ZoteroSearchClient(lambda: client).search(query="attention", user_id="12345")

        assert items[0]["year"] == "1999"

    @pytest.mark.asyncio
    async def test_normalize_falls_back_when_date_has_no_leading_year(self) -> None:
        client = _client(FakeResponse([_item(date="Published 1999 by MIT Press")]))

        items = await ZoteroSearchClient(lambda: client).search(query="attention", user_id="12345")

        assert items[0]["year"] == "Published 1999 by MIT Press"
