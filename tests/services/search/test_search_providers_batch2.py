"""Batch-2 provider contract tests: serply / aliyun_iqs / qianfan / bocha.

The shared-knob tests in ``test_search_providers.py`` cover request
construction for these modules; this batch targets the branches that file
leaves dark: non-200 and in-band error branches, malformed / empty response
envelopes, parameter clamping and per-row fallbacks. Everything runs offline
against scripted ``requests`` fakes -- no test here may touch the network.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.search.providers.aliyun_iqs import AliyunIQSProvider, _publish_date
from deeptutor.services.search.providers.bocha import BochaProvider
from deeptutor.services.search.providers.qianfan import QianfanProvider
from deeptutor.services.search.providers.serply import SerplyProvider


class _FakeResponse:
    def __init__(
        self, payload: dict[str, Any] | None = None, status_code: int = 200, text: str = ""
    ) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload if payload is not None else {}

    def json(self) -> dict[str, Any]:
        return self._payload


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    module: str,
    method: str,
    responder,
) -> list[dict[str, Any]]:
    """Replace ``requests`` in a provider module with a scripted fake.

    ``responder`` receives the captured call (method/url/kwargs) and returns a
    ``_FakeResponse``; the captured calls are returned for assertions.
    """
    captured: list[dict[str, Any]] = []

    def _call(url: str, **kwargs: Any) -> _FakeResponse:
        call = {"method": method.upper(), "url": url, **kwargs}
        captured.append(call)
        return responder(call)

    class _FakeRequests:
        pass

    setattr(_FakeRequests, method, staticmethod(_call))
    monkeypatch.setattr(f"deeptutor.services.search.providers.{module}.requests", _FakeRequests)
    return captured


# ---------------------------------------------------------------------------
# Serply -- GET api, three verticals behind one key.
# ---------------------------------------------------------------------------


def test_serply_raises_on_non_200_response(monkeypatch) -> None:
    captured = _patch(
        monkeypatch,
        "serply",
        "get",
        lambda call: _FakeResponse(status_code=503, text="upstream unavailable"),
    )

    with pytest.raises(Exception, match="Serply API error: 503"):
        SerplyProvider(api_key="k").search("q")

    assert captured[-1]["headers"]["X-Api-Key"] == "k"


@pytest.mark.parametrize("payload", [{}, {"feed": None}, {"feed": "not-a-dict"}])
def test_serply_malformed_news_feed_returns_empty_response(payload, monkeypatch) -> None:
    """A missing or non-dict ``feed`` must degrade to zero rows, not crash."""
    _patch(monkeypatch, "serply", "get", lambda call: _FakeResponse(payload))

    response = SerplyProvider(api_key="k").search("q", mode="news")

    assert response.search_results == []
    assert response.citations == []
    assert response.metadata["mode"] == "news"


@pytest.mark.parametrize(
    ("max_results", "expected_num"),
    [(250, 100), (0, 1), (-5, 1)],
)
def test_serply_clamps_num_to_the_documented_range(max_results, expected_num, monkeypatch) -> None:
    """Serply's ``num`` only accepts 1-100; out-of-range caps must be clamped."""
    captured = _patch(monkeypatch, "serply", "get", lambda call: _FakeResponse({}))

    SerplyProvider(api_key="k").search("q", max_results=max_results)

    assert captured[-1]["url"].endswith(f"/search/q=q&num={expected_num}")


def test_serply_news_source_variants_and_junk_rows(monkeypatch) -> None:
    """News rows: dict sources use their title, missing ones fall back, and
    non-dict entries in the feed are dropped instead of raising."""
    payload = {
        "feed": {
            "entries": [
                {"title": "A", "link": "https://e/1", "source": {"title": "Dict Times"}},
                {"title": "B", "link": "https://e/2"},
                "junk",
                None,
            ]
        }
    }
    _patch(monkeypatch, "serply", "get", lambda call: _FakeResponse(payload))

    response = SerplyProvider(api_key="k").search("q", mode="news")

    assert [row.source for row in response.search_results] == ["Dict Times", "Google News"]
    assert len(response.citations) == 2


def test_serply_scholar_row_without_optional_fields_leaves_attributes_empty(monkeypatch) -> None:
    payload = {"articles": [{"title": "T", "link": "https://e/1"}]}
    _patch(monkeypatch, "serply", "get", lambda call: _FakeResponse(payload))

    response = SerplyProvider(api_key="k").search("q", mode="scholar")

    assert response.provider == "serply_scholar"
    (row,) = response.search_results
    assert row.attributes == {}
    assert row.source == "Google Scholar"


def test_serply_carries_related_searches_and_knowledge_graph_metadata(monkeypatch) -> None:
    payload = {
        "results": [],
        "related_searches": [{"query": "next"}],
        "knowledge_graph": {"title": "Transformer"},
    }
    _patch(monkeypatch, "serply", "get", lambda call: _FakeResponse(payload))

    response = SerplyProvider(api_key="k").search("q")

    assert response.metadata["relatedSearches"] == [{"query": "next"}]
    assert response.metadata["knowledgeGraph"] == {"title": "Transformer"}


# ---------------------------------------------------------------------------
# Aliyun IQS -- GET api, fixed page of 10, client-side cap.
# ---------------------------------------------------------------------------


def test_aliyun_iqs_rejects_invalid_time_range() -> None:
    with pytest.raises(ValueError, match="time_range"):
        AliyunIQSProvider(api_key="k").search("q", time_range="Fortnight")


def test_aliyun_iqs_rejects_invalid_industry() -> None:
    with pytest.raises(ValueError, match="industry"):
        AliyunIQSProvider(api_key="k").search("q", industry="sports")


def test_aliyun_iqs_raises_on_non_200_response(monkeypatch) -> None:
    _patch(
        monkeypatch,
        "aliyun_iqs",
        "get",
        lambda call: _FakeResponse(status_code=401, text="bad key"),
    )

    with pytest.raises(Exception, match="Aliyun IQS API error: 401"):
        AliyunIQSProvider(api_key="k").search("q")


def test_aliyun_iqs_request_params_serialize_bools_and_optional_fields(monkeypatch) -> None:
    """Booleans must serialize lowercase and ``industry`` only rides along
    when actually requested."""
    captured = _patch(monkeypatch, "aliyun_iqs", "get", lambda call: _FakeResponse({}))

    AliyunIQSProvider(api_key="k").search("q", page=2, industry="law")
    first = captured[-1]
    assert first["params"] == {
        "query": "q",
        "timeRange": "NoLimit",
        "page": 2,
        "returnMainText": "true",
        "returnMarkdownText": "false",
        "enableRerank": "true",
        "industry": "law",
    }
    assert first["headers"]["X-API-Key"] == "k"

    AliyunIQSProvider(api_key="k").search("q")
    assert "industry" not in captured[-1]["params"]


def test_aliyun_iqs_row_fallbacks_markdown_site_and_date(monkeypatch) -> None:
    """markdownText wins over mainText; displayLink beats pageMap.hostname;
    hostLogo and epoch dates map across."""
    payload = {
        "requestId": "req-1",
        "pageItems": [
            {
                "title": "T",
                "link": "https://e/1",
                "snippet": "s",
                "mainText": "plain",
                "markdownText": "# rich",
                "pageMap": {"hostname": "fallback.example", "hostLogo": "https://e/logo.png"},
                "publishTime": 1754006400000,
                "score": 0.75,
            }
        ],
        "searchInformation": {"total": 42},
    }
    _patch(monkeypatch, "aliyun_iqs", "get", lambda call: _FakeResponse(payload))

    response = AliyunIQSProvider(api_key="k").search("q")

    (row,) = response.search_results
    assert row.content == "# rich"
    assert row.source == "fallback.example"
    assert row.score == 0.75
    citation = response.citations[0]
    assert citation.icon == "https://e/logo.png"
    assert citation.website == "fallback.example"
    # Millisecond epoch must reach the model as a date, never a raw int.
    assert citation.date.count("-") == 2
    assert response.metadata["request_id"] == "req-1"
    assert response.metadata["total_results"] == 42


def test_aliyun_iqs_missing_page_items_returns_empty_response(monkeypatch) -> None:
    _patch(monkeypatch, "aliyun_iqs", "get", lambda call: _FakeResponse({}))

    response = AliyunIQSProvider(api_key="k").search("q")

    assert response.search_results == []
    assert response.citations == []
    assert response.metadata["request_id"] == ""
    assert response.metadata["total_results"] == 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("", ""),
        (0, ""),
        ("soon", "soon"),
        ([], "[]"),
        (10**20, str(10**20)),
    ],
)
def test_aliyun_iqs_publish_date_passes_garbage_through(value, expected) -> None:
    """Unparseable publish stamps must pass through untouched, never raise."""
    assert _publish_date(value) == expected


# ---------------------------------------------------------------------------
# Qianfan -- POST api, errors ride inside a 200.
# ---------------------------------------------------------------------------


def test_qianfan_rejects_invalid_recency_filter() -> None:
    with pytest.raises(ValueError, match="search_recency_filter"):
        QianfanProvider(api_key="k").search("q", search_recency_filter="decade")


def test_qianfan_truncates_query_and_passes_recency_filter(monkeypatch) -> None:
    """The API rejects long queries instead of truncating, so the 72-char cut
    has to happen on our side; recency rides along only when requested."""
    captured = _patch(monkeypatch, "qianfan", "post", lambda call: _FakeResponse({}))

    QianfanProvider(api_key="k").search("x" * 100, search_recency_filter="week")

    payload = captured[-1]["json"]
    assert payload["messages"] == [{"role": "user", "content": "x" * 72}]
    assert payload["search_recency_filter"] == "week"

    QianfanProvider(api_key="k").search("short")
    assert "search_recency_filter" not in captured[-1]["json"]


@pytest.mark.parametrize(("max_results", "expected_top_k"), [(80, 50), (0, 1)])
def test_qianfan_clamps_top_k_to_the_api_ceiling(max_results, expected_top_k, monkeypatch) -> None:
    captured = _patch(monkeypatch, "qianfan", "post", lambda call: _FakeResponse({}))

    QianfanProvider(api_key="k").search("q", max_results=max_results)

    assert captured[-1]["json"]["resource_type_filter"] == [
        {"type": "web", "top_k": expected_top_k}
    ]


def test_qianfan_raises_on_error_code_inside_a_200(monkeypatch) -> None:
    payload = {"code": 2820002, "message": "quota exceeded"}
    _patch(monkeypatch, "qianfan", "post", lambda call: _FakeResponse(payload))

    with pytest.raises(Exception, match="quota exceeded"):
        QianfanProvider(api_key="k").search("q")


@pytest.mark.parametrize("code", [None, 0, 200, "0", "200"])
def test_qianfan_treats_documented_success_codes_as_success(code, monkeypatch) -> None:
    """``code`` is documented as error-only, but success spellings must never
    be mistaken for failures."""
    _patch(
        monkeypatch, "qianfan", "post", lambda call: _FakeResponse({"code": code, "references": []})
    )

    response = QianfanProvider(api_key="k").search("q")

    assert response.search_results == []


def test_qianfan_missing_references_returns_empty_response(monkeypatch) -> None:
    _patch(monkeypatch, "qianfan", "post", lambda call: _FakeResponse({}))

    response = QianfanProvider(api_key="k").search("q")

    assert response.citations == []
    assert response.search_results == []
    assert response.metadata["request_id"] == ""


def test_qianfan_keeps_native_citation_ids_with_position_fallback(monkeypatch) -> None:
    """Rows carrying their own id keep it; rows without fall back to position."""
    payload = {
        "request_id": "r1",
        "references": [
            {"id": 7, "title": "A", "url": "https://e/7"},
            {"title": "B", "url": "https://e/2"},
        ],
    }
    _patch(monkeypatch, "qianfan", "post", lambda call: _FakeResponse(payload))

    response = QianfanProvider(api_key="k").search("q")

    assert [c.id for c in response.citations] == [7, 2]
    assert [c.reference for c in response.citations] == ["[7]", "[2]"]


# ---------------------------------------------------------------------------
# Bocha -- POST api, failures also wrapped in a 200.
# ---------------------------------------------------------------------------


def test_bocha_rejects_invalid_freshness_word() -> None:
    with pytest.raises(ValueError, match="freshness"):
        BochaProvider(api_key="k").search("q", freshness="fortnight")


@pytest.mark.parametrize("freshness", ["2026-01-01", "2026-01-01..2026-01-31"])
def test_bocha_passes_dated_freshness_ranges_through(freshness, monkeypatch) -> None:
    """A dated range is legal even though it is not one of the bare words."""
    captured = _patch(monkeypatch, "bocha", "post", lambda call: _FakeResponse({}))

    BochaProvider(api_key="k").search("q", freshness=freshness)

    assert captured[-1]["json"]["freshness"] == freshness


def test_bocha_clamps_count_and_carries_summary_flag(monkeypatch) -> None:
    captured = _patch(monkeypatch, "bocha", "post", lambda call: _FakeResponse({}))

    BochaProvider(api_key="k").search("q", max_results=60)
    assert captured[-1]["json"]["count"] == 50

    BochaProvider(api_key="k").search("q", max_results=0, summary=False)
    assert captured[-1]["json"]["count"] == 1
    assert captured[-1]["json"]["summary"] is False


def test_bocha_raises_on_non_200_response(monkeypatch) -> None:
    _patch(
        monkeypatch,
        "bocha",
        "post",
        lambda call: _FakeResponse(status_code=500, text="boom"),
    )

    with pytest.raises(Exception, match="Bocha API error: 500"):
        BochaProvider(api_key="k").search("q")


def test_bocha_missing_web_pages_returns_empty_response(monkeypatch) -> None:
    """A 200 with no ``data.webPages.value`` envelope degrades to zero rows."""
    _patch(monkeypatch, "bocha", "post", lambda call: _FakeResponse({"code": 200}))

    response = BochaProvider(api_key="k").search("q")

    assert response.search_results == []
    assert response.citations == []
    assert response.provider == "bocha"


def test_bocha_maps_row_fields_onto_results_and_citations(monkeypatch) -> None:
    """name->title, summary->content, snippet stays the SERP blurb, and the
    siteName/siteIcon/datePublished trio maps onto both shapes."""
    payload = {
        "code": 200,
        "data": {
            "webPages": {
                "value": [
                    {
                        "name": "T",
                        "url": "https://e/1",
                        "snippet": "blurb",
                        "summary": "long extract",
                        "siteName": "Example",
                        "datePublished": "2026-08-01",
                        "siteIcon": "https://e/icon.png",
                    },
                    {"name": "NoSite", "url": "https://e/2"},
                ]
            }
        },
    }
    _patch(monkeypatch, "bocha", "post", lambda call: _FakeResponse(payload))

    response = BochaProvider(api_key="k").search("q")

    assert [row.title for row in response.search_results] == ["T", "NoSite"]
    assert response.search_results[0].content == "long extract"
    assert response.search_results[0].snippet == "blurb"
    assert [row.source for row in response.search_results] == ["Example", "Bocha"]
    citation = response.citations[0]
    assert citation.icon == "https://e/icon.png"
    assert citation.website == "Example"
    assert citation.date == "2026-08-01"
