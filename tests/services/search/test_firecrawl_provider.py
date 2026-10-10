"""Behavior contract tests for the Firecrawl search provider.

Firecrawl's search endpoint validates the corpus and time knobs up front,
clamps the result cap and its own millisecond timeout, and bills per call —
so a malformed payload or a silent error costs money without results. These
tests pin the request facets the batch suite leaves open (full header block,
transport-vs-payload timeout split, ``base_url`` override, cap clamping), the
row-to-citation mapping with its null-field fallbacks, and every failure
branch — non-200 statuses, malformed bodies, network errors, and a missing
API key — all through a fake transport, mirroring ``test_serper_provider``.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests

from deeptutor.services.search.providers.firecrawl import FirecrawlProvider


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
    holder: dict[str, Any] = {"response": _FakeResponse({"success": True, "data": {"web": []}})}

    def _post(url: str, **kwargs: Any) -> _FakeResponse:
        captured.append({"url": url, **kwargs})
        reply = holder["response"]
        if isinstance(reply, Exception):
            raise reply
        return reply

    class _FakeRequests:
        post = staticmethod(_post)

    monkeypatch.setattr("deeptutor.services.search.providers.firecrawl.requests", _FakeRequests)
    return captured, holder


# ---------------------------------------------------------------------------
# Request assembly
# ---------------------------------------------------------------------------


def test_firecrawl_posts_bearer_auth_and_json_headers_to_the_v2_endpoint(transport) -> None:
    captured, _ = transport
    FirecrawlProvider(api_key="fk").search("transformers", timeout=15)

    (call,) = captured
    assert call["url"] == FirecrawlProvider.BASE_URL
    assert call["headers"] == {
        "Authorization": "Bearer fk",
        "Content-Type": "application/json",
    }
    # The transport timeout passes through untouched; only the payload's own
    # millisecond timeout is derived from it.
    assert call["timeout"] == 15


def test_firecrawl_result_cap_clamps_into_the_documented_band(transport) -> None:
    captured, _ = transport
    provider = FirecrawlProvider(api_key="k")

    provider.search("q", max_results=0)
    assert captured[-1]["json"]["limit"] == 1

    provider.search("q", max_results=250)
    assert captured[-1]["json"]["limit"] == 100


def test_firecrawl_payload_timeout_tracks_just_under_the_transport_timeout(transport) -> None:
    captured, _ = transport
    FirecrawlProvider(api_key="k").search("q", timeout=30)

    assert captured[-1]["json"]["timeout"] == 29000


def test_firecrawl_honors_a_custom_base_url_override(transport) -> None:
    captured, _ = transport
    mirror = "https://mirror.example.com/v2/search"

    FirecrawlProvider(api_key="k").search("q", base_url=mirror)

    (call,) = captured
    assert call["url"] == mirror


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def test_firecrawl_rows_map_to_results_and_sequentially_numbered_citations(transport) -> None:
    _, holder = transport
    holder["response"] = _FakeResponse(
        {
            "success": True,
            "creditsUsed": 2,
            "data": {
                "web": [
                    {
                        "title": "Attention Is All You Need",
                        "url": "https://arxiv.org/abs/1706.03762",
                        "description": "The dominant sequence transduction models...",
                        "markdown": "# Attention\nfull text",
                    },
                    {"title": "Second", "url": "https://e/2"},
                ]
            },
        }
    )

    response = FirecrawlProvider(api_key="k").search("attention")

    assert response.provider == "firecrawl"
    assert response.model == "firecrawl-search"
    assert response.query == "attention"
    assert response.answer == ""
    assert response.metadata == {"finish_reason": "stop"}
    assert response.usage == {"credits_used": 2}

    (first, second) = response.search_results
    assert first.title == "Attention Is All You Need"
    assert first.url == "https://arxiv.org/abs/1706.03762"
    assert first.snippet == "The dominant sequence transduction models..."
    assert first.content == "# Attention\nfull text"
    assert first.source == "Firecrawl"

    assert [c.id for c in response.citations] == [1, 2]
    assert [c.reference for c in response.citations] == ["[1]", "[2]"]
    for citation, result in zip(response.citations, response.search_results):
        assert citation.url == result.url
        assert citation.title == result.title
        assert citation.snippet == result.snippet
        assert citation.content == result.content
        assert citation.source == "Firecrawl"


def test_firecrawl_null_data_and_web_levels_yield_an_empty_response(transport) -> None:
    _, holder = transport
    provider = FirecrawlProvider(api_key="k")

    holder["response"] = _FakeResponse({"success": True, "data": None})
    null_data = provider.search("q")
    assert null_data.search_results == []
    assert null_data.citations == []

    holder["response"] = _FakeResponse({"success": True, "data": {"web": None}})
    null_web = provider.search("q")
    assert null_web.search_results == []
    assert null_web.citations == []


def test_firecrawl_null_row_fields_coerce_to_empty_strings(transport) -> None:
    _, holder = transport
    holder["response"] = _FakeResponse(
        {
            "success": True,
            "data": {"web": [{"title": None, "url": None, "description": None, "markdown": None}]},
        }
    )

    response = FirecrawlProvider(api_key="k").search("q")

    (row,) = response.search_results
    assert row.title == ""
    assert row.url == ""
    assert row.snippet == ""
    assert row.content == ""

    (citation,) = response.citations
    assert citation.title == ""
    assert citation.url == ""


# ---------------------------------------------------------------------------
# Failure branches
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (401, "invalid api key"),
        (429, "rate limited"),
        (502, "<html>Bad Gateway</html>"),
    ],
)
def test_firecrawl_non_200_raises_with_status_and_body(transport, status, body) -> None:
    captured, holder = transport
    holder["response"] = _FakeResponse(None, status_code=status, text=body)

    with pytest.raises(Exception, match=f"Firecrawl API error: {status}.*{body}"):
        FirecrawlProvider(api_key="k").search("q")

    assert captured  # the failing status came from the fake transport


def test_firecrawl_malformed_json_inside_a_200_surfaces(transport) -> None:
    """A garbled 200 body must not quietly become "no results"."""
    _, holder = transport
    holder["response"] = _FakeResponse(None, status_code=200, text="<html>oops</html>")

    with pytest.raises(ValueError, match="invalid json"):
        FirecrawlProvider(api_key="k").search("q")


def test_firecrawl_success_flag_defaults_to_true_when_absent(transport) -> None:
    _, holder = transport
    holder["response"] = _FakeResponse({"data": {"web": [{"title": "T", "url": "https://e/1"}]}})

    response = FirecrawlProvider(api_key="k").search("q")

    assert [r.title for r in response.search_results] == ["T"]
    assert response.usage == {"credits_used": 0}


def test_firecrawl_error_payload_without_an_error_key_echoes_the_payload(transport) -> None:
    _, holder = transport
    holder["response"] = _FakeResponse({"success": False, "creditsUsed": 1})

    with pytest.raises(Exception, match="creditsUsed"):
        FirecrawlProvider(api_key="k").search("q")


def test_firecrawl_network_errors_propagate(transport) -> None:
    _, holder = transport
    holder["response"] = requests.ConnectionError("connection refused")

    with pytest.raises(requests.ConnectionError, match="connection refused"):
        FirecrawlProvider(api_key="k").search("q")


def test_missing_api_key_fails_fast_at_construction(monkeypatch) -> None:
    from deeptutor.services.search import base as search_base

    monkeypatch.setattr(search_base, "search_provider_credentials", lambda name: ("", ""))

    with pytest.raises(ValueError, match="firecrawl requires an api_key"):
        FirecrawlProvider()


def test_blank_api_key_still_fails_fast_at_construction(monkeypatch) -> None:
    """An empty key is not a key: the credential lookup still runs and raises."""
    from deeptutor.services.search import base as search_base

    monkeypatch.setattr(search_base, "search_provider_credentials", lambda name: ("", ""))

    with pytest.raises(ValueError, match="firecrawl requires an api_key"):
        FirecrawlProvider(api_key="")


def test_provider_without_a_key_reports_unavailable(monkeypatch) -> None:
    from deeptutor.services.search import base as search_base

    monkeypatch.setattr(search_base, "search_provider_credentials", lambda name: ("", ""))

    provider = FirecrawlProvider(api_key="k")
    provider.api_key = ""

    assert provider.is_available() is False
    assert FirecrawlProvider(api_key="k").is_available() is True
