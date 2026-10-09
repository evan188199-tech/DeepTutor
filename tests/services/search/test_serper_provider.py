"""Behavior contract tests for the Serper search provider.

Serper is a paid SERP API, so every failure mode the runtime can hit — an
expired key, a rate-limited quota, a gateway hiccup — has to surface as a
`SerperAPIError` carrying the status and the server's message instead of an
empty result set. These tests pin the request construction (endpoint per mode,
auth header, payload knobs, proxy attachment), the organic-row parsing
(including the `url`/`description` fallback keys and scholar attributes), and
the failure branches, all through a fake transport.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.search.providers.serper import SerperAPIError, SerperProvider


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
    """Fake requests transport: records each POST, replies with `holder["response"]`."""
    captured: list[dict[str, Any]] = []
    holder: dict[str, Any] = {"response": _FakeResponse({"organic": []})}

    def _post(url: str, **kwargs: Any) -> _FakeResponse:
        captured.append({"url": url, **kwargs})
        return holder["response"]

    class _FakeRequests:
        post = staticmethod(_post)

    monkeypatch.setattr("deeptutor.services.search.providers.serper.requests", _FakeRequests)
    return captured, holder


def test_default_search_hits_search_endpoint_with_default_payload(transport) -> None:
    captured, _ = transport
    SerperProvider(api_key="k").search("attention")

    (call,) = captured
    assert call["url"] == "https://google.serper.dev/search"
    assert call["headers"] == {"X-API-KEY": "k", "Content-Type": "application/json"}
    assert call["json"] == {
        "q": "attention",
        "num": 10,
        "gl": "us",
        "hl": "en",
        "page": 1,
        "autocorrect": True,
    }
    assert call["timeout"] == 30


def test_mode_gl_hl_page_and_autocorrect_reach_the_request(transport) -> None:
    captured, _ = transport
    SerperProvider(api_key="k").search(
        "attention",
        mode="scholar",
        gl="cn",
        hl="zh-cn",
        page=2,
        autocorrect=False,
        num=5,
        timeout=7,
    )

    call = captured[-1]
    assert call["url"] == "https://google.serper.dev/scholar"
    assert call["json"] == {
        "q": "attention",
        "num": 5,
        "gl": "cn",
        "hl": "zh-cn",
        "page": 2,
        "autocorrect": False,
    }
    assert call["timeout"] == 7


def test_max_results_wins_over_num_and_never_drops_below_one(transport) -> None:
    captured, _ = transport
    provider = SerperProvider(api_key="k")

    provider.search("q", num=10, max_results=3)
    assert captured[-1]["json"]["num"] == 3

    provider.search("q", max_results=0)
    assert captured[-1]["json"]["num"] == 1


def test_proxy_is_attached_only_when_configured(transport) -> None:
    captured, _ = transport
    proxy = "http://127.0.0.1:7890"

    SerperProvider(api_key="k", proxy=proxy).search("q")
    assert captured[-1]["proxies"] == {"http": proxy, "https": proxy}

    SerperProvider(api_key="k").search("q")
    assert "proxies" not in captured[-1]


def test_organic_rows_become_results_and_numbered_citations(transport) -> None:
    captured, holder = transport
    holder["response"] = _FakeResponse(
        {
            "organic": [
                {
                    "title": "Attention Is All You Need",
                    "link": "https://arxiv.org/abs/1706.03762",
                    "snippet": "The dominant sequence transduction models...",
                    "date": "2017-06-12",
                    "source": "arXiv",
                },
                {
                    "title": "Second",
                    "link": "https://e/2",
                    "snippet": "s2",
                },
            ]
        }
    )

    response = SerperProvider(api_key="k").search("attention")

    assert response.provider == "serper"
    assert response.model == "serper-search"
    assert response.query == "attention"
    assert [r.title for r in response.search_results] == ["Attention Is All You Need", "Second"]
    assert [r.url for r in response.search_results] == [
        "https://arxiv.org/abs/1706.03762",
        "https://e/2",
    ]
    assert response.search_results[0].snippet.startswith("The dominant")
    assert response.search_results[0].date == "2017-06-12"
    assert response.search_results[0].source == "arXiv"

    assert [c.id for c in response.citations] == [1, 2]
    assert [c.reference for c in response.citations] == ["[1]", "[2]"]
    assert response.citations[0].url == "https://arxiv.org/abs/1706.03762"
    assert response.citations[0].title == "Attention Is All You Need"
    assert response.citations[0].source == "arXiv"


def test_rows_fall_back_to_url_and_description_keys(transport) -> None:
    _, holder = transport
    holder["response"] = _FakeResponse(
        {
            "organic": [
                {"title": "Alt", "url": "https://e/alt", "description": "alt body"},
                {"title": "Bare"},
            ]
        }
    )

    response = SerperProvider(api_key="k").search("q")

    assert response.search_results[0].url == "https://e/alt"
    assert response.search_results[0].snippet == "alt body"
    assert response.search_results[1].url == ""
    assert response.search_results[1].snippet == ""
    assert response.citations[0].url == "https://e/alt"


def test_sitelinks_and_attributes_survive_parsing(transport) -> None:
    _, holder = transport
    sitelink = {"title": "PDF", "link": "https://arxiv.org/pdf/1706.03762"}
    holder["response"] = _FakeResponse(
        {
            "organic": [
                {
                    "title": "T",
                    "link": "https://e/1",
                    "sitelinks": [sitelink, {"title": "NoLink"}],
                    "attributes": {"favicon": "https://e/fav.png"},
                },
                {"title": "No attrs", "link": "https://e/2"},
            ]
        }
    )

    response = SerperProvider(api_key="k").search("q")

    first = response.search_results[0]
    assert first.sitelinks == [
        {"title": "PDF", "link": "https://arxiv.org/pdf/1706.03762"},
        {"title": "NoLink", "link": ""},
    ]
    assert first.attributes == {"favicon": "https://e/fav.png"}
    assert response.search_results[1].sitelinks == []
    assert response.search_results[1].attributes == {}


def test_scholar_fields_land_in_attributes_and_rename_the_provider(transport) -> None:
    _, holder = transport
    holder["response"] = _FakeResponse(
        {
            "organic": [
                {
                    "title": "Attention Is All You Need",
                    "link": "https://doi.org/10.5555/3295222",
                    "publicationInfo": "A Vaswani, N Shazeer - NeurIPS, 2017",
                    "citedBy": 120000,
                    "pdfUrl": "https://arxiv.org/pdf/1706.03762",
                    "year": 2017,
                    "id": "W2626778328",
                }
            ]
        }
    )

    response = SerperProvider(api_key="k").search("attention", mode="scholar")

    assert response.provider == "serper_scholar"
    assert response.model == "serper-scholar"
    (row,) = response.search_results
    assert row.attributes == {
        "publicationInfo": "A Vaswani, N Shazeer - NeurIPS, 2017",
        "citedBy": 120000,
        "pdfUrl": "https://arxiv.org/pdf/1706.03762",
        "year": 2017,
        "paperId": "W2626778328",
    }


def test_answer_box_wins_and_rich_serp_data_lands_in_metadata(transport) -> None:
    _, holder = transport
    answer_box = {"answer": "42"}
    knowledge_graph = {"description": "a paper"}
    people_also_ask = [{"question": "why?"}]
    related = [{"query": "transformer"}]
    params = {"num": 10}
    holder["response"] = _FakeResponse(
        {
            "organic": [],
            "searchParameters": params,
            "answerBox": answer_box,
            "knowledgeGraph": knowledge_graph,
            "peopleAlsoAsk": people_also_ask,
            "relatedSearches": related,
        }
    )

    response = SerperProvider(api_key="k").search("meaning of life")

    assert response.answer == "42"
    assert response.metadata["finish_reason"] == "stop"
    assert response.metadata["mode"] == "search"
    assert response.metadata["searchParameters"] == params
    assert response.metadata["answerBox"] == answer_box
    assert response.metadata["knowledgeGraph"] == knowledge_graph
    assert response.metadata["peopleAlsoAsk"] == people_also_ask
    assert response.metadata["relatedSearches"] == related


def test_answer_falls_back_to_snippet_then_knowledge_graph(transport) -> None:
    _, holder = transport
    provider = SerperProvider(api_key="k")

    holder["response"] = _FakeResponse({"organic": [], "answerBox": {"snippet": "answer-ish"}})
    assert provider.search("q").answer == "answer-ish"

    holder["response"] = _FakeResponse(
        {"organic": [], "knowledgeGraph": {"description": "kg body"}}
    )
    assert provider.search("q").answer == "kg body"

    holder["response"] = _FakeResponse({"organic": []})
    assert provider.search("q").answer == ""


def test_missing_rich_serp_keys_are_absent_from_metadata(transport) -> None:
    _, holder = transport
    holder["response"] = _FakeResponse({"organic": [], "searchParameters": {"q": "q"}})

    metadata = SerperProvider(api_key="k").search("q").metadata

    assert metadata["searchParameters"] == {"q": "q"}
    assert "answerBox" not in metadata
    assert "knowledgeGraph" not in metadata
    assert "peopleAlsoAsk" not in metadata
    assert "relatedSearches" not in metadata


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (429, "Too many requests"),
        (401, "Invalid API key"),
    ],
)
def test_rate_limit_and_auth_failures_raise_api_error_with_server_message(
    transport, status, message
) -> None:
    captured, holder = transport
    holder["response"] = _FakeResponse({"message": message}, status_code=status)

    with pytest.raises(SerperAPIError, match=f"{status}.*{message}"):
        SerperProvider(api_key="bad").search("q")

    assert captured  # the failing status code came from the fake transport


def test_non_json_error_body_falls_back_to_raw_text(transport) -> None:
    _, holder = transport
    holder["response"] = _FakeResponse(None, status_code=502, text="<html>Bad Gateway</html>")

    with pytest.raises(SerperAPIError, match="502.*Bad Gateway"):
        SerperProvider(api_key="k").search("q")
