"""Behavior-contract tests for zhipu / firecrawl / duckduckgo / searxng.

Covers the request each provider builds, how its rows map onto
``SearchResult``/``Citation``, and the empty/malformed/error branches -- all
offline via fake transports. The shared-knob contract (``max_results`` /
``proxy`` / ``base_url`` reach the HTTP call) already lives in
``test_search_providers.py``; nothing here repeats it.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
import requests

from deeptutor.services.search.providers.firecrawl import FirecrawlProvider
from deeptutor.services.search.providers.searxng import (
    SearxngProvider,
    SearxngResponseError,
    _validate_base_url,
)
from deeptutor.services.search.providers.zhipu import ZhipuProvider

PROXY = "http://127.0.0.1:7890"


class _FakeResponse:
    def __init__(
        self,
        payload: Any = None,
        status_code: int = 200,
        text: str = "",
        json_error: bool = False,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = text
        self._json_error = json_error

    def json(self) -> Any:
        if self._json_error:
            raise ValueError("no JSON")
        return self._payload


@pytest.fixture
def post_calls(monkeypatch):
    """Capture POSTs made by a provider module and answer with ``body``."""
    captured: list[dict[str, Any]] = []
    box: dict[str, _FakeResponse] = {}

    def _install(module: str):
        def _post(url: str, **kwargs: Any) -> _FakeResponse:
            captured.append({"method": "POST", "url": url, **kwargs})
            return box["response"]

        class _FakeRequests:
            post = staticmethod(_post)

        monkeypatch.setattr(f"deeptutor.services.search.providers.{module}.requests", _FakeRequests)

    _install.box = box  # type: ignore[attr-defined]
    _install.captured = captured  # type: ignore[attr-defined]
    return _install


# --------------------------------------------------------------------------
# Zhipu
# --------------------------------------------------------------------------


def test_zhipu_builds_the_documented_payload(post_calls) -> None:
    post_calls("zhipu")
    post_calls.box["response"] = _FakeResponse({"search_result": [], "request_id": "r-1"})

    ZhipuProvider(api_key="zk").search(
        "fourier",
        max_results=5,
        search_engine="search_pro",
        content_size="high",
        search_recency_filter="oneWeek",
    )

    call = post_calls.captured[-1]
    assert call["url"] == ZhipuProvider.BASE_URL
    assert call["headers"]["Authorization"] == "Bearer zk"
    assert call["json"] == {
        "search_query": "fourier",
        "search_engine": "search_pro",
        "search_intent": False,
        "count": 5,
        "search_recency_filter": "oneWeek",
        "content_size": "high",
    }


def test_zhipu_truncates_long_queries_and_clamps_count(post_calls) -> None:
    post_calls("zhipu")
    post_calls.box["response"] = _FakeResponse({"search_result": []})

    ZhipuProvider(api_key="k").search("x" * 90, max_results=99)
    payload = post_calls.captured[-1]["json"]
    assert payload["search_query"] == "x" * 70
    assert payload["count"] == 50

    ZhipuProvider(api_key="k").search("q", max_results=0)
    assert post_calls.captured[-1]["json"]["count"] == 1


def test_zhipu_rejects_unknown_engine_and_recency(post_calls) -> None:
    post_calls("zhipu")
    post_calls.box["response"] = _FakeResponse({"search_result": []})

    with pytest.raises(ValueError, match="search_engine"):
        ZhipuProvider(api_key="k").search("q", search_engine="search_ultra")
    with pytest.raises(ValueError, match="search_recency_filter"):
        ZhipuProvider(api_key="k").search("q", search_recency_filter="oneHour")
    assert post_calls.captured == []


def test_zhipu_adds_domain_filter_only_when_given(post_calls) -> None:
    post_calls("zhipu")
    post_calls.box["response"] = _FakeResponse({"search_result": []})

    ZhipuProvider(api_key="k").search("q", search_domain_filter=["arxiv.org"])
    assert post_calls.captured[-1]["json"]["search_domain_filter"] == ["arxiv.org"]

    ZhipuProvider(api_key="k").search("q")
    assert "search_domain_filter" not in post_calls.captured[-1]["json"]


def test_zhipu_maps_rows_onto_results_and_citations(post_calls) -> None:
    post_calls("zhipu")
    post_calls.box["response"] = _FakeResponse(
        {
            "request_id": "req-7",
            "search_result": [
                {
                    "title": "Attention",
                    "link": "https://a/1",
                    "content": "body text",
                    "media": "arXiv",
                    "publish_date": "2026-08-01",
                    "icon": "https://a/i.png",
                },
                {"title": "Sparse", "link": "https://a/2", "content": None},
            ],
        }
    )

    response = ZhipuProvider(api_key="k").search("attention", search_engine="search_std")

    assert response.provider == "zhipu"
    assert response.model == "search_std"
    assert [r.url for r in response.search_results] == ["https://a/1", "https://a/2"]
    assert response.search_results[0].source == "arXiv"
    assert response.search_results[0].date == "2026-08-01"
    # A row without media falls back to the provider name on both records.
    assert response.search_results[1].source == "Zhipu"
    assert response.search_results[1].content == ""
    (first, second) = response.citations
    assert [c.id for c in (first, second)] == [1, 2]
    assert first.reference == "[1]"
    assert first.icon == "https://a/i.png"
    assert first.website == "arXiv"
    assert second.website == ""
    assert response.metadata["request_id"] == "req-7"


def test_zhipu_non_200_raises_with_status_and_body(post_calls) -> None:
    post_calls("zhipu")
    post_calls.box["response"] = _FakeResponse(status_code=429, text="rate limited")

    with pytest.raises(Exception, match="Zhipu API error: 429"):
        ZhipuProvider(api_key="k").search("q")


# --------------------------------------------------------------------------
# Firecrawl
# --------------------------------------------------------------------------


def test_firecrawl_builds_the_documented_payload(post_calls) -> None:
    post_calls("firecrawl")
    post_calls.box["response"] = _FakeResponse({"success": True, "data": {"web": []}})

    FirecrawlProvider(api_key="fk").search("transformers", max_results=7, timeout=60)

    call = post_calls.captured[-1]
    assert call["url"] == FirecrawlProvider.BASE_URL
    assert call["headers"]["Authorization"] == "Bearer fk"
    payload = call["json"]
    assert payload["query"] == "transformers"
    assert payload["limit"] == 7
    assert payload["sources"] == [{"type": "web"}]
    assert payload["timeout"] == 59000
    assert "categories" not in payload
    assert "tbs" not in payload
    assert "scrapeOptions" not in payload


def test_firecrawl_scrape_adds_markdown_options(post_calls) -> None:
    post_calls("firecrawl")
    post_calls.box["response"] = _FakeResponse({"success": True, "data": {"web": []}})

    FirecrawlProvider(api_key="k").search(
        "q", scrape=True, categories=["research", "pdf"], tbs="qdr:w"
    )

    payload = post_calls.captured[-1]["json"]
    assert payload["scrapeOptions"] == {"formats": [{"type": "markdown"}], "onlyMainContent": True}
    assert payload["categories"] == ["research", "pdf"]
    assert payload["tbs"] == "qdr:w"


def test_firecrawl_rejects_unknown_category(post_calls) -> None:
    post_calls("firecrawl")
    post_calls.box["response"] = _FakeResponse({"success": True, "data": {"web": []}})

    with pytest.raises(ValueError, match="category"):
        FirecrawlProvider(api_key="k").search("q", categories=["recipes"])
    assert post_calls.captured == []


def test_firecrawl_keeps_timeout_inside_the_api_bound(post_calls) -> None:
    post_calls("firecrawl")
    post_calls.box["response"] = _FakeResponse({"success": True, "data": {"web": []}})

    FirecrawlProvider(api_key="k").search("q", timeout=1)
    assert post_calls.captured[-1]["json"]["timeout"] == 1000

    FirecrawlProvider(api_key="k").search("q", timeout=600)
    assert post_calls.captured[-1]["json"]["timeout"] == 300000


def test_firecrawl_maps_rows_and_credits(post_calls) -> None:
    post_calls("firecrawl")
    post_calls.box["response"] = _FakeResponse(
        {
            "success": True,
            "creditsUsed": 3,
            "data": {
                "web": [
                    {
                        "title": "Paper",
                        "url": "https://p/1",
                        "description": "abstract",
                        "markdown": "# Paper\nfull text",
                    },
                    {"title": None, "url": "https://p/2"},
                ]
            },
        }
    )

    response = FirecrawlProvider(api_key="k").search("paper")

    assert response.provider == "firecrawl"
    assert [r.url for r in response.search_results] == ["https://p/1", "https://p/2"]
    assert response.search_results[0].snippet == "abstract"
    assert response.search_results[0].content.startswith("# Paper")
    assert response.search_results[1].source == "Firecrawl"
    assert response.citations[0].reference == "[1]"
    assert response.usage["credits_used"] == 3


def test_firecrawl_empty_data_yields_an_empty_response(post_calls) -> None:
    post_calls("firecrawl")
    post_calls.box["response"] = _FakeResponse({"success": True})

    response = FirecrawlProvider(api_key="k").search("q")

    assert response.search_results == []
    assert response.citations == []


def test_firecrawl_non_200_raises_with_status(post_calls) -> None:
    post_calls("firecrawl")
    post_calls.box["response"] = _FakeResponse(status_code=500, text="boom")

    with pytest.raises(Exception, match="Firecrawl API error: 500"):
        FirecrawlProvider(api_key="k").search("q")


def test_firecrawl_surfaces_an_error_flag_inside_a_200(post_calls) -> None:
    post_calls("firecrawl")
    post_calls.box["response"] = _FakeResponse({"success": False, "error": "rate limited"})

    with pytest.raises(Exception, match="rate limited"):
        FirecrawlProvider(api_key="k").search("q")


# --------------------------------------------------------------------------
# DuckDuckGo
# --------------------------------------------------------------------------


class _FakeDDGS:
    """Stands in for ``ddgs.DDGS``; behavior is seeded on the class because the
    provider constructs its own instance."""

    instances: list[_FakeDDGS] = []
    text_calls: list[dict[str, Any]] = []
    next_rows: list[dict[str, Any]] | None = []
    next_error: Exception | None = None

    def __init__(self, proxy: str | None = None, timeout: int = 10) -> None:
        self.proxy = proxy
        self.timeout = timeout
        _FakeDDGS.instances.append(self)

    def text(self, query: str, max_results: int = 5) -> list[dict[str, Any]] | None:
        _FakeDDGS.text_calls.append({"query": query, "max_results": max_results})
        if _FakeDDGS.next_error is not None:
            raise _FakeDDGS.next_error
        return _FakeDDGS.next_rows


@pytest.fixture
def ddgs(monkeypatch):
    """Replace the ``ddgs`` module so no HTTP client is ever constructed."""
    _FakeDDGS.instances = []
    _FakeDDGS.text_calls = []
    _FakeDDGS.next_rows = []
    _FakeDDGS.next_error = None
    fake_module = types.ModuleType("ddgs")
    fake_module.DDGS = _FakeDDGS
    monkeypatch.setitem(sys.modules, "ddgs", fake_module)
    return _FakeDDGS


def test_duckduckgo_passes_proxy_timeout_and_cap_to_ddgs(ddgs) -> None:
    from deeptutor.services.search.providers.duckduckgo import DuckDuckGoProvider

    DuckDuckGoProvider(api_key="k", proxy=PROXY).search("q", max_results=99, timeout=7)
    assert ddgs.instances[-1].proxy == PROXY
    assert ddgs.instances[-1].timeout == 7
    assert ddgs.text_calls[-1] == {"query": "q", "max_results": 10}

    DuckDuckGoProvider(api_key="k").search("q", max_results=0)
    assert ddgs.text_calls[-1]["max_results"] == 1


def test_duckduckgo_maps_rows_onto_results(ddgs) -> None:
    from deeptutor.services.search.providers.duckduckgo import DuckDuckGoProvider

    ddgs.next_rows = [
        {"title": "T1", "href": "https://d/1", "body": "s1"},
        {"title": "T2", "href": "https://d/2", "body": "s2"},
    ]

    response = DuckDuckGoProvider(api_key="k").search("q")

    assert response.provider == "duckduckgo"
    assert response.answer == ""
    assert [r.url for r in response.search_results] == ["https://d/1", "https://d/2"]
    assert response.search_results[0].snippet == "s1"
    assert response.search_results[0].source == "DuckDuckGo"
    assert [c.id for c in response.citations] == [1, 2]
    assert response.citations[1].reference == "[2]"


def test_duckduckgo_empty_feed_yields_an_empty_response(ddgs) -> None:
    from deeptutor.services.search.providers.duckduckgo import DuckDuckGoProvider

    ddgs.next_rows = None  # ddgs can hand back None instead of a list

    response = DuckDuckGoProvider(api_key="k").search("q")

    assert response.search_results == []
    assert response.citations == []
    assert response.metadata["finish_reason"] == "stop"


def test_duckduckgo_surfaces_client_errors(ddgs) -> None:
    from deeptutor.services.search.providers.duckduckgo import DuckDuckGoProvider

    ddgs.next_error = RuntimeError("ratelimit")

    with pytest.raises(RuntimeError, match="ratelimit"):
        DuckDuckGoProvider(api_key="k").search("q")


# --------------------------------------------------------------------------
# SearXNG
# --------------------------------------------------------------------------


def test_searxng_requires_a_base_url() -> None:
    with pytest.raises(ValueError, match="base_url"):
        SearxngProvider(api_key="k").search("q", base_url="")


def test_validate_base_url_normalizes_and_defaults_the_scheme() -> None:
    assert _validate_base_url("http://searx.example/") == "http://searx.example"
    assert _validate_base_url("  searx.local:8080/  ") == "http://searx.local:8080"
    assert _validate_base_url("https://s.example/x/") == "https://s.example/x"


def test_validate_base_url_rejects_non_http_addresses() -> None:
    with pytest.raises(requests.exceptions.InvalidURL):
        _validate_base_url("ftp://searx.example")
    with pytest.raises(requests.exceptions.InvalidURL):
        _validate_base_url("http://searx.example:99999")


@pytest.fixture
def searxng_get(monkeypatch):
    """Capture SearXNG GETs and answer with a configurable response."""
    captured: list[dict[str, Any]] = []
    box: dict[str, _FakeResponse] = {}

    def _get(url: str, **kwargs: Any) -> _FakeResponse:
        captured.append({"method": "GET", "url": url, **kwargs})
        return box["response"]

    class _FakeRequests:
        get = staticmethod(_get)
        # The provider reads these off its (patched) requests module.
        HTTPError = requests.HTTPError
        exceptions = requests.exceptions

    monkeypatch.setattr("deeptutor.services.search.providers.searxng.requests", _FakeRequests)
    return captured, box


def test_searxng_builds_the_json_search_request(searxng_get) -> None:
    captured, box = searxng_get
    box["response"] = _FakeResponse({"results": []})

    SearxngProvider(api_key="k", proxy=PROXY).search(
        "fourier", base_url="http://searx.example/", max_results=5
    )

    call = captured[-1]
    assert call["url"] == "http://searx.example/search"
    assert call["params"] == {"q": "fourier", "format": "json"}
    assert call["proxies"] == {"http": PROXY, "https": PROXY}


def test_searxng_maps_rows_and_defaults_the_engine(searxng_get) -> None:
    captured, box = searxng_get
    box["response"] = _FakeResponse(
        {
            "results": [
                {"title": "T1", "url": "https://s/1", "content": "c1", "engine": "bing"},
                {"title": "T2", "url": "https://s/2", "content": "c2", "engine": "google"},
                {"title": "T3", "url": "https://s/3", "content": "c3"},
                {"title": "T4", "url": "https://s/4", "content": "c4"},
            ]
        }
    )

    response = SearxngProvider(api_key="k").search("q", base_url="http://s.example", max_results=3)

    assert response.provider == "searxng"
    assert len(response.search_results) == 3
    assert response.search_results[0].source == "bing"
    assert response.search_results[2].source == "SearXNG"
    assert [c.id for c in response.citations] == [1, 2, 3]
    assert response.citations[0].snippet == "c1"


def test_searxng_non_200_raises_http_error_with_response(searxng_get) -> None:
    captured, box = searxng_get
    box["response"] = _FakeResponse(status_code=403, text="Forbidden")

    with pytest.raises(requests.HTTPError, match="HTTP 403") as excinfo:
        SearxngProvider(api_key="k").search("q", base_url="http://s.example")
    assert excinfo.value.response is not None
    assert excinfo.value.response.status_code == 403


def test_searxng_non_json_body_raises_a_response_error(searxng_get) -> None:
    captured, box = searxng_get
    box["response"] = _FakeResponse(text="<html>capcha</html>", json_error=True)

    with pytest.raises(SearxngResponseError, match="valid JSON"):
        SearxngProvider(api_key="k").search("q", base_url="http://s.example")


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param("a plain string", id="payload-not-an-object"),
        pytest.param({}, id="results-key-missing"),
        pytest.param({"results": "nope"}, id="results-not-a-list"),
        pytest.param({"results": [{"title": "ok"}, "stray row"]}, id="row-not-an-object"),
    ],
)
def test_searxng_rejects_malformed_result_payloads(searxng_get, payload) -> None:
    captured, box = searxng_get
    box["response"] = _FakeResponse(payload)

    with pytest.raises(SearxngResponseError, match="results list"):
        SearxngProvider(api_key="k").search("q", base_url="http://s.example")
