"""Behavior contract tests for the Zhipu (智谱 GLM) search provider.

Zhipu's standalone web-search endpoint rejects out-of-range queries outright
and 4xx/5xx responses with a bare status, so the adapter has to truncate the
query, clamp the result count, and validate the engine/recency knobs before
any bytes leave the process. These tests pin the request construction
(endpoint, Bearer auth, payload knobs, optional domain filter, proxy), the
``search_result`` row parsing (content doubling as snippet, media falling
back to a "Zhipu" source, numbered citations), and every failure branch —
non-200 statuses, malformed bodies, network errors, and a missing API key —
all through a fake transport, mirroring ``test_serper_provider``.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests

from deeptutor.services.search.providers.zhipu import ZhipuProvider

_QUERY_LIMIT = 70


class _FakeResponse:
    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        status_code: int = 200,
        text: str = "",
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self) -> dict[str, Any]:
        if self._payload is None:
            raise ValueError(f"invalid json: {self.text!r}")
        return self._payload


@pytest.fixture
def transport(monkeypatch):
    """Fake requests transport: records each POST, replies with `holder["response"]`.

    The holder may also carry an exception instance, which the transport then
    raises — how network-level failures are simulated.
    """
    captured: list[dict[str, Any]] = []
    holder: dict[str, Any] = {"response": _FakeResponse({"search_result": []})}

    def _post(url: str, **kwargs: Any) -> _FakeResponse:
        captured.append({"url": url, **kwargs})
        reply = holder["response"]
        if isinstance(reply, Exception):
            raise reply
        return reply

    class _FakeRequests:
        post = staticmethod(_post)

    monkeypatch.setattr("deeptutor.services.search.providers.zhipu.requests", _FakeRequests)
    return captured, holder


# ---------------------------------------------------------------------------
# Request assembly
# ---------------------------------------------------------------------------


def test_default_search_posts_the_documented_payload(transport) -> None:
    captured, _ = transport
    ZhipuProvider(api_key="k").search("attention")

    (call,) = captured
    assert call["url"] == "https://open.bigmodel.cn/api/paas/v4/web_search"
    assert call["headers"] == {
        "Authorization": "Bearer k",
        "Content-Type": "application/json",
    }
    assert call["json"] == {
        "search_query": "attention",
        "search_engine": "search_std",
        "search_intent": False,
        "count": 5,
        "search_recency_filter": "noLimit",
        "content_size": "medium",
    }
    assert call["timeout"] == 30
    assert "proxies" not in call


def test_long_queries_are_truncated_to_the_api_limit(transport) -> None:
    """The API rejects long queries instead of truncating, so the client must."""
    captured, _ = transport
    long_query = "x" * (_QUERY_LIMIT + 20)

    ZhipuProvider(api_key="k").search(long_query)

    sent = captured[-1]["json"]["search_query"]
    assert sent == long_query[:_QUERY_LIMIT]
    assert len(sent) == _QUERY_LIMIT


def test_count_is_clamped_into_the_documented_one_to_fifty_range(transport) -> None:
    captured, _ = transport
    provider = ZhipuProvider(api_key="k")

    provider.search("q", max_results=0)
    assert captured[-1]["json"]["count"] == 1

    provider.search("q", max_results=100)
    assert captured[-1]["json"]["count"] == 50


def test_engine_recency_content_size_and_domain_filter_reach_the_request(transport) -> None:
    captured, _ = transport
    ZhipuProvider(api_key="k").search(
        "q",
        max_results=8,
        search_engine="search_pro_sogou",
        content_size="high",
        search_recency_filter="oneWeek",
        timeout=7,
        search_domain_filter=["arxiv.org"],
    )

    call = captured[-1]
    assert call["json"] == {
        "search_query": "q",
        "search_engine": "search_pro_sogou",
        "search_intent": False,
        "count": 8,
        "search_recency_filter": "oneWeek",
        "content_size": "high",
        "search_domain_filter": ["arxiv.org"],
    }
    assert call["timeout"] == 7


def test_empty_domain_filter_is_omitted_from_the_payload(transport) -> None:
    captured, _ = transport
    provider = ZhipuProvider(api_key="k")

    provider.search("q", search_domain_filter=[])
    assert "search_domain_filter" not in captured[-1]["json"]

    provider.search("q", search_domain_filter="")
    assert "search_domain_filter" not in captured[-1]["json"]


def test_base_url_override_and_proxy_are_honored(transport) -> None:
    captured, _ = transport
    proxy = "http://127.0.0.1:7890"

    ZhipuProvider(api_key="k", proxy=proxy).search("q", base_url="https://gw.example/search")
    call = captured[-1]
    assert call["url"] == "https://gw.example/search"
    assert call["proxies"] == {"http": proxy, "https": proxy}


@pytest.mark.parametrize(
    "bad_kwargs",
    [
        {"search_engine": "search_ultra"},
        {"search_recency_filter": "oneHour"},
    ],
)
def test_invalid_knobs_fail_fast_before_any_request(transport, bad_kwargs) -> None:
    captured, _ = transport

    with pytest.raises(ValueError, match="Zhipu"):
        ZhipuProvider(api_key="k").search("q", **bad_kwargs)

    assert captured == []


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def test_rows_become_results_and_numbered_citations(transport) -> None:
    _, holder = transport
    holder["response"] = _FakeResponse(
        {
            "request_id": "req-42",
            "search_result": [
                {
                    "title": "Attention Is All You Need",
                    "link": "https://arxiv.org/abs/1706.03762",
                    "content": "The dominant sequence transduction models...",
                    "media": "arXiv",
                    "publish_date": "2017-06-12",
                    "icon": "https://arxiv.org/favicon.ico",
                },
                {"title": "Second", "link": "https://e/2", "content": "s2", "media": "Slashdot"},
            ],
        }
    )

    response = ZhipuProvider(api_key="k").search("attention")

    assert response.provider == "zhipu"
    assert response.model == "search_std"
    assert response.query == "attention"
    assert response.answer == ""

    (first, second) = response.search_results
    assert first.title == "Attention Is All You Need"
    assert first.url == "https://arxiv.org/abs/1706.03762"
    # Zhipu returns one body field; it doubles as snippet and content.
    assert first.snippet == "The dominant sequence transduction models..."
    assert first.content == first.snippet
    assert first.date == "2017-06-12"
    assert first.source == "arXiv"
    assert second.source == "Slashdot"

    assert [c.id for c in response.citations] == [1, 2]
    assert [c.reference for c in response.citations] == ["[1]", "[2]"]
    assert response.citations[0].url == first.url
    assert response.citations[0].title == first.title
    assert response.citations[0].snippet == first.snippet
    assert response.citations[0].date == "2017-06-12"
    assert response.citations[0].source == "arXiv"
    assert response.citations[0].icon == "https://arxiv.org/favicon.ico"
    assert response.citations[0].website == "arXiv"

    assert response.metadata["finish_reason"] == "stop"
    assert response.metadata["request_id"] == "req-42"


def test_sparse_rows_fall_back_to_safe_defaults(transport) -> None:
    _, holder = transport
    holder["response"] = _FakeResponse(
        {"search_result": [{"title": "Bare", "link": "https://e/1"}]}
    )

    response = ZhipuProvider(api_key="k").search("q")

    (row,) = response.search_results
    assert row.snippet == ""
    assert row.content == ""
    assert row.date == ""
    assert row.source == "Zhipu"

    (citation,) = response.citations
    assert citation.source == "Zhipu"
    assert citation.icon == ""
    assert citation.website == ""


def test_missing_or_null_search_result_yields_an_empty_response(transport) -> None:
    _, holder = transport
    provider = ZhipuProvider(api_key="k")

    holder["response"] = _FakeResponse({"request_id": "req-empty"})
    empty = provider.search("q")
    assert empty.search_results == []
    assert empty.citations == []
    assert empty.metadata["request_id"] == "req-empty"

    holder["response"] = _FakeResponse({"search_result": None})
    null_rows = provider.search("q")
    assert null_rows.search_results == []
    assert null_rows.citations == []


# ---------------------------------------------------------------------------
# Failure branches
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (401, '{"error": "invalid api key"}'),
        (429, "rate limited"),
        (500, "internal error"),
    ],
)
def test_non_200_raises_with_status_and_body(transport, status, body) -> None:
    captured, holder = transport
    holder["response"] = _FakeResponse(None, status_code=status, text=body)

    with pytest.raises(Exception, match=f"Zhipu API error: {status}.*{body}"):
        ZhipuProvider(api_key="k").search("q")

    assert captured  # the failing status came from the fake transport


def test_malformed_json_surfaces_instead_of_an_empty_result_set(transport) -> None:
    """A garbled 200 body must not quietly become "no results"."""
    _, holder = transport
    holder["response"] = _FakeResponse(None, status_code=200, text="<html>oops</html>")

    with pytest.raises(ValueError, match="invalid json"):
        ZhipuProvider(api_key="k").search("q")


def test_network_errors_propagate(transport) -> None:
    _, holder = transport
    holder["response"] = requests.ConnectionError("connection refused")

    with pytest.raises(requests.ConnectionError, match="connection refused"):
        ZhipuProvider(api_key="k").search("q")


def test_missing_api_key_fails_fast_at_construction(monkeypatch) -> None:
    from deeptutor.services.search import base as search_base

    monkeypatch.setattr(search_base, "search_provider_credentials", lambda name: ("", ""))

    with pytest.raises(ValueError, match="zhipu requires an api_key"):
        ZhipuProvider()


def test_blank_api_key_still_fails_fast_at_construction(monkeypatch) -> None:
    """An empty key is not a key: the credential lookup still runs and raises."""
    from deeptutor.services.search import base as search_base

    monkeypatch.setattr(search_base, "search_provider_credentials", lambda name: ("", ""))

    with pytest.raises(ValueError, match="zhipu requires an api_key"):
        ZhipuProvider(api_key="")


def test_provider_without_a_key_reports_unavailable(monkeypatch) -> None:
    from deeptutor.services.search import base as search_base

    monkeypatch.setattr(search_base, "search_provider_credentials", lambda name: ("", ""))

    provider = ZhipuProvider(api_key="k")
    provider.api_key = ""

    assert provider.is_available() is False
    assert ZhipuProvider(api_key="k").is_available() is True
