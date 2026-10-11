"""Keyless provider contract tests: SearXNG / DuckDuckGo.

The two providers that run without an API key get their own batch here,
matching the per-provider coverage of ``test_search_providers_batch2.py`` /
``batch3.py``: request construction, the response-parsing contract, and the
malformed / empty response branches. SearXNG talks to a self-hosted endpoint
over ``requests``; DuckDuckGo goes through the lazily imported ``ddgs`` library.
Everything runs offline against scripted fakes -- no test here may touch the
network.
"""

from __future__ import annotations

from datetime import datetime
import sys
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from deeptutor.services.search.providers.duckduckgo import DuckDuckGoProvider
from deeptutor.services.search.providers.searxng import (
    SearxngProvider,
    SearxngResponseError,
    _validate_base_url,
)

PROXY = "http://127.0.0.1:7890"


class _FakeResponse:
    def __init__(
        self,
        payload: Any = None,
        status_code: int = 200,
        json_error: ValueError | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = ""
        self._payload = payload
        self._json_error = json_error

    def json(self) -> Any:
        if self._json_error is not None:
            raise self._json_error
        return self._payload


# ---------------------------------------------------------------------------
# SearXNG -- GET <base_url>/search?format=json against a self-hosted instance.
# ---------------------------------------------------------------------------


def _patch_searxng(monkeypatch, responder) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    def _get(url: str, **kwargs: Any) -> _FakeResponse:
        captured.append({"url": url, **kwargs})
        return responder(captured[-1])

    class _FakeRequests:
        get = staticmethod(_get)

    # The provider raises these off the (patched) requests module itself.
    _FakeRequests.HTTPError = requests.HTTPError
    _FakeRequests.exceptions = requests.exceptions

    monkeypatch.setattr("deeptutor.services.search.providers.searxng.requests", _FakeRequests)
    return captured


_SEARXNG_ROWS = [
    {
        "title": "Attention Is All You Need",
        "url": "https://arxiv.org/abs/1706.03762",
        "content": "The dominant sequence transduction models...",
        "engine": "arxiv",
    },
    {"title": "Transformer paper", "url": "https://e/2", "content": "s2", "engine": "duckduckgo"},
    {"title": "Third hit", "url": "https://e/3"},  # no engine field
]


def test_searxng_builds_the_json_search_request(monkeypatch) -> None:
    captured = _patch_searxng(monkeypatch, lambda call: _FakeResponse({"results": _SEARXNG_ROWS}))

    response = SearxngProvider().search(
        "attention", base_url="https://searx.example.com/", timeout=7
    )

    call = captured[-1]
    assert call["url"] == "https://searx.example.com/search"
    assert call["params"] == {"q": "attention", "format": "json"}
    assert call["timeout"] == 7
    # No proxy configured -> the request must not carry one.
    assert "proxies" not in call
    assert response.provider == "searxng"
    assert response.model == "searxng"
    assert response.answer == ""
    assert response.metadata["finish_reason"] == "stop"
    datetime.fromisoformat(response.timestamp)


def test_searxng_forwards_the_profile_proxy(monkeypatch) -> None:
    captured = _patch_searxng(monkeypatch, lambda call: _FakeResponse({"results": []}))

    SearxngProvider(proxy=PROXY).search("q", base_url="https://searx.example.com")

    assert captured[-1]["proxies"] == {"http": PROXY, "https": PROXY}


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://searx.example.com", "https://searx.example.com/search"),
        ("https://searx.example.com/", "https://searx.example.com/search"),
        ("searx.lan", "http://searx.lan/search"),
    ],
)
def test_searxng_normalizes_the_base_url(monkeypatch, base_url, expected) -> None:
    captured = _patch_searxng(monkeypatch, lambda call: _FakeResponse({"results": []}))

    SearxngProvider().search("q", base_url=base_url)

    assert captured[-1]["url"] == expected


@pytest.mark.parametrize("base_url", ["ftp://searx.example.com", "http://[::1"])
def test_searxng_rejects_an_invalid_base_url(base_url) -> None:
    with pytest.raises(requests.exceptions.InvalidURL):
        SearxngProvider().search("q", base_url=base_url)


def test_searxng_requires_a_base_url(monkeypatch) -> None:
    captured = _patch_searxng(monkeypatch, lambda call: _FakeResponse({"results": []}))

    with pytest.raises(ValueError, match="base_url"):
        SearxngProvider().search("q")

    assert captured == []  # rejected before any request is attempted


def test_searxng_raises_on_non_200_response(monkeypatch) -> None:
    captured = _patch_searxng(monkeypatch, lambda call: _FakeResponse(status_code=403))

    with pytest.raises(requests.HTTPError, match="HTTP 403"):
        SearxngProvider().search("q", base_url="https://searx.example.com")

    assert captured[-1]["url"].endswith("/search")


def test_searxng_rejects_a_non_json_body(monkeypatch) -> None:
    _patch_searxng(
        monkeypatch,
        lambda call: _FakeResponse(json_error=ValueError("Expecting value")),
    )

    with pytest.raises(SearxngResponseError, match="valid JSON"):
        SearxngProvider().search("q", base_url="https://searx.example.com")


@pytest.mark.parametrize(
    "payload",
    [
        "just a string",
        ["a", "list"],
        {},
        {"results": None},
        {"results": "not-a-list"},
        {"results": [{"title": "ok"}, "not-a-dict"]},
    ],
)
def test_searxng_rejects_a_malformed_results_envelope(payload, monkeypatch) -> None:
    _patch_searxng(monkeypatch, lambda call: _FakeResponse(payload))

    with pytest.raises(SearxngResponseError, match="results list"):
        SearxngProvider().search("q", base_url="https://searx.example.com")


def test_searxng_empty_results_yield_an_empty_response(monkeypatch) -> None:
    _patch_searxng(monkeypatch, lambda call: _FakeResponse({"results": []}))

    response = SearxngProvider().search("q", base_url="https://searx.example.com")

    assert response.search_results == []
    assert response.citations == []


def test_searxng_maps_rows_onto_results_and_citations(monkeypatch) -> None:
    _patch_searxng(monkeypatch, lambda call: _FakeResponse({"results": _SEARXNG_ROWS}))

    response = SearxngProvider().search("attention", base_url="https://searx.example.com")

    assert [r.url for r in response.search_results] == [
        "https://arxiv.org/abs/1706.03762",
        "https://e/2",
        "https://e/3",
    ]
    assert response.search_results[0].snippet == "The dominant sequence transduction models..."
    assert response.search_results[0].source == "arxiv"
    # A row without an engine falls back to the instance name.
    assert response.search_results[2].source == "SearXNG"
    assert [c.id for c in response.citations] == [1, 2, 3]
    assert [c.reference for c in response.citations] == ["[1]", "[2]", "[3]"]
    # Citations mirror their result row.
    assert response.citations[1].url == response.search_results[1].url
    assert response.citations[1].title == response.search_results[1].title


@pytest.mark.parametrize(
    ("max_results", "expected"),
    [
        (2, 2),
        (99, 10),  # hard cap at 10
        (0, 1),  # never fewer than one row
    ],
)
def test_searxng_clamps_max_results(monkeypatch, max_results, expected) -> None:
    rows = [{"title": f"t{i}", "url": f"https://e/{i}"} for i in range(12)]
    _patch_searxng(monkeypatch, lambda call: _FakeResponse({"results": rows}))

    response = SearxngProvider().search(
        "q", base_url="https://searx.example.com", max_results=max_results
    )

    assert len(response.search_results) == expected
    assert len(response.citations) == expected
    assert [c.id for c in response.citations] == list(range(1, expected + 1))


def test_searxng_metadata_matches_the_spec_table() -> None:
    from deeptutor.services.config import SEARCH_PROVIDERS

    spec = SEARCH_PROVIDERS["searxng"]
    assert SearxngProvider.name == "searxng"
    assert SearxngProvider.display_name == spec.label
    assert SearxngProvider.requires_api_key is False  # keyless: base_url only
    assert SearxngProvider.supports_answer is False


# ---------------------------------------------------------------------------
# DuckDuckGo -- zero-config search through the lazily imported `ddgs` library.
# ---------------------------------------------------------------------------


def _install_fake_ddgs(monkeypatch, text_result):
    """Swap in a fake ``ddgs`` module; the provider must import it lazily."""
    instances: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []

    class _FakeDDGS:
        def __init__(self, proxy: str | None = None, timeout: int | None = None) -> None:
            instances.append({"proxy": proxy, "timeout": timeout})

        def text(self, query: str, max_results: int | None = None):
            calls.append({"query": query, "max_results": max_results})
            if text_result is None:
                return None
            rows = list(text_result)
            if max_results is not None:
                rows = rows[:max_results]  # the library caps client-side
            return iter(rows)

    monkeypatch.delitem(sys.modules, "ddgs", raising=False)
    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=_FakeDDGS))
    return instances, calls


_DDGS_ROWS = [
    {
        "title": "Attention Is All You Need",
        "href": "https://arxiv.org/abs/1706.03762",
        "body": "The dominant sequence transduction models...",
    },
    {"title": "Second hit", "href": "https://e/2", "body": "s2"},
]


def test_duckduckgo_maps_rows_onto_results_and_citations(monkeypatch) -> None:
    _install_fake_ddgs(monkeypatch, iter(_DDGS_ROWS))

    response = DuckDuckGoProvider().search("attention", timeout=9)

    assert response.provider == "duckduckgo"
    assert response.model == "duckduckgo"
    assert response.answer == ""
    assert response.metadata["finish_reason"] == "stop"
    datetime.fromisoformat(response.timestamp)
    assert [r.title for r in response.search_results] == [
        "Attention Is All You Need",
        "Second hit",
    ]
    assert [r.url for r in response.search_results] == [
        "https://arxiv.org/abs/1706.03762",
        "https://e/2",
    ]
    assert [r.snippet for r in response.search_results] == [
        "The dominant sequence transduction models...",
        "s2",
    ]
    # Every row is sourced from DuckDuckGo itself, not a per-engine string.
    assert all(r.source == "DuckDuckGo" for r in response.search_results)
    assert [c.id for c in response.citations] == [1, 2]
    assert [c.reference for c in response.citations] == ["[1]", "[2]"]
    assert response.citations[0].url == response.search_results[0].url


def test_duckduckgo_forwards_proxy_timeout_and_clamped_count(monkeypatch) -> None:
    instances, calls = _install_fake_ddgs(monkeypatch, iter(_DDGS_ROWS))

    DuckDuckGoProvider(proxy=PROXY).search("attention", max_results=3, timeout=9)

    assert instances == [{"proxy": PROXY, "timeout": 9}]
    assert calls[-1] == {"query": "attention", "max_results": 3}


@pytest.mark.parametrize(
    ("max_results", "expected"),
    [
        (99, 10),  # hard cap at 10
        (0, 1),  # never fewer than one row
    ],
)
def test_duckduckgo_clamps_max_results(monkeypatch, max_results, expected) -> None:
    rows = [{"title": f"t{i}", "href": f"https://e/{i}", "body": "s"} for i in range(12)]
    _, calls = _install_fake_ddgs(monkeypatch, iter(rows))

    response = DuckDuckGoProvider().search("q", max_results=max_results)

    assert calls[-1]["max_results"] == expected
    assert len(response.search_results) == expected


@pytest.mark.parametrize(
    "rows",
    [
        None,  # ddgs.text() returning None degrades to an empty response
        [],
        [{"title": 42, "href": None, "body": 7}],  # non-string values are coerced
    ],
)
def test_duckduckgo_tolerates_empty_and_odd_rows(monkeypatch, rows) -> None:
    _install_fake_ddgs(monkeypatch, rows)

    response = DuckDuckGoProvider().search("q")

    if not rows:
        assert response.search_results == []
        assert response.citations == []
    else:
        (row,) = response.search_results
        assert row.title == "42"
        assert row.url == "None"
        assert row.snippet == "7"
        (citation,) = response.citations
        assert citation.url == "None"


def test_duckduckgo_propagates_ddgs_failures(monkeypatch) -> None:
    """A backend failure must surface, never be swallowed into empty results."""

    class _FakeDDGS:
        def __init__(self, proxy=None, timeout=None) -> None:
            pass

        def text(self, query, max_results=None):
            raise RuntimeError("ddgs backend unavailable")

    monkeypatch.delitem(sys.modules, "ddgs", raising=False)
    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=_FakeDDGS))

    with pytest.raises(RuntimeError, match="ddgs backend unavailable"):
        DuckDuckGoProvider().search("q")


def test_duckduckgo_metadata_matches_the_spec_table() -> None:
    from deeptutor.services.config import SEARCH_PROVIDERS

    spec = SEARCH_PROVIDERS["duckduckgo"]
    assert DuckDuckGoProvider.name == "duckduckgo"
    assert DuckDuckGoProvider.display_name == spec.label
    assert DuckDuckGoProvider.requires_api_key is False
    assert DuckDuckGoProvider.supports_answer is False
    # It is the designated soft-fallback engine, so nothing here is paid.
    assert spec.soft_fallback is True
