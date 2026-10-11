"""Batch-3 provider contract tests: tavily / brave / perplexity.

The shared-knob tests in ``test_search_providers.py`` already prove
``max_results`` / ``proxy`` reach these providers' HTTP calls; this batch
targets what that file leaves dark: auth placement, optional request
fields, response mapping, empty / malformed envelopes and error branches.
Everything runs offline against scripted ``requests`` fakes and a fake
Perplexity client -- no test here may touch the network.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.services.search.providers.brave import BraveProvider
from deeptutor.services.search.providers.perplexity import PerplexityProvider
from deeptutor.services.search.providers.tavily import TavilyProvider


class _FakeResponse:
    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        status_code: int = 200,
        text: str = "",
        broken_json: bool = False,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload if payload is not None else {}
        self._broken_json = broken_json

    def json(self) -> dict[str, Any]:
        if self._broken_json:
            raise ValueError("body is not JSON")
        return self._payload


def _patch_requests(
    monkeypatch: pytest.MonkeyPatch,
    module: str,
    method: str,
    responder,
) -> list[dict[str, Any]]:
    """Replace ``requests`` in a provider module with a scripted fake."""
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
# Tavily -- POST api, auth lives in the JSON body.
# ---------------------------------------------------------------------------


def test_tavily_posts_auth_in_body_and_omits_unset_filters(monkeypatch) -> None:
    captured = _patch_requests(
        monkeypatch,
        "tavily",
        "post",
        lambda call: _FakeResponse({"results": []}),
    )

    TavilyProvider(api_key="secret-key").search("q")

    call = captured[-1]
    assert call["method"] == "POST"
    assert call["url"] == TavilyProvider.BASE_URL
    payload = call["json"]
    assert payload["api_key"] == "secret-key"
    assert payload["query"] == "q"
    assert payload["search_depth"] == "basic"
    assert payload["topic"] == "general"
    assert payload["include_answer"] is True
    for absent in ("days", "include_domains", "exclude_domains"):
        assert absent not in payload


def test_tavily_forwards_the_optional_topic_filters(monkeypatch) -> None:
    captured = _patch_requests(
        monkeypatch,
        "tavily",
        "post",
        lambda call: _FakeResponse({"results": []}),
    )

    TavilyProvider(api_key="k").search(
        "q",
        search_depth="advanced",
        topic="news",
        days=30,
        include_domains=["a.com"],
        exclude_domains=["b.org"],
        include_raw_content=True,
        include_images=True,
    )

    payload = captured[-1]["json"]
    assert payload["search_depth"] == "advanced"
    assert payload["topic"] == "news"
    assert payload["days"] == 30
    assert payload["include_domains"] == ["a.com"]
    assert payload["exclude_domains"] == ["b.org"]
    assert payload["include_raw_content"] is True
    assert payload["include_images"] is True


def test_tavily_maps_rows_answer_and_envelope_metadata(monkeypatch) -> None:
    rows = [
        {
            "title": "Row one",
            "url": "https://one",
            "content": "snippet one",
            "published_date": "2026-01-02",
            "source": "press",
            "raw_content": "full one",
            "score": 0.9,
        },
        {"url": "https://two"},
    ]
    _patch_requests(
        monkeypatch,
        "tavily",
        "post",
        lambda call: _FakeResponse(
            {
                "answer": "synthesized",
                "results": rows,
                "images": ["https://img"],
                "response_time": 0.42,
            }
        ),
    )

    response = TavilyProvider(api_key="k").search("q", search_depth="advanced")

    assert response.answer == "synthesized"
    assert response.provider == "tavily"
    assert response.model == "tavily-advanced"
    assert response.usage == {}
    assert [sr.title for sr in response.search_results] == ["Row one", ""]
    assert response.search_results[0].snippet == "snippet one"
    assert response.search_results[0].content == "full one"
    assert response.search_results[0].date == "2026-01-02"
    assert response.search_results[0].source == "press"
    assert response.search_results[0].score == 0.9
    assert [c.id for c in response.citations] == [1, 2]
    assert response.citations[0].reference == "[1]"
    assert response.citations[0].snippet == "snippet one"
    assert response.metadata["images"] == ["https://img"]
    assert response.metadata["response_time"] == 0.42
    assert response.metadata["finish_reason"] == "stop"


def test_tavily_surfaces_the_error_field_of_a_json_error_body(monkeypatch) -> None:
    _patch_requests(
        monkeypatch,
        "tavily",
        "post",
        lambda call: _FakeResponse(
            {"error": "invalid api key"}, status_code=401, text='{"error": "invalid api key"}'
        ),
    )

    with pytest.raises(Exception, match="Tavily API error: 401 - invalid api key"):
        TavilyProvider(api_key="bad").search("q")


def test_tavily_falls_back_to_raw_text_when_the_error_body_is_not_json(monkeypatch) -> None:
    _patch_requests(
        monkeypatch,
        "tavily",
        "post",
        lambda call: _FakeResponse(status_code=502, text="upstream exploded", broken_json=True),
    )

    with pytest.raises(Exception, match="Tavily API error: 502 - upstream exploded"):
        TavilyProvider(api_key="k").search("q")


# ---------------------------------------------------------------------------
# Brave -- GET api, auth lives in a header, count is clamped server-side.
# ---------------------------------------------------------------------------


def test_brave_sends_its_subscription_token_header(monkeypatch) -> None:
    captured = _patch_requests(
        monkeypatch,
        "brave",
        "get",
        lambda call: _FakeResponse({"web": {"results": []}}),
    )

    BraveProvider(api_key="secret-key").search("q")

    call = captured[-1]
    assert call["method"] == "GET"
    assert call["url"] == BraveProvider.BASE_URL
    assert call["headers"]["X-Subscription-Token"] == "secret-key"
    assert call["headers"]["Accept"] == "application/json"


@pytest.mark.parametrize(
    ("max_results", "expected"),
    [(25, 10), (3, 3), (0, 1)],
)
def test_brave_clamps_count_into_the_api_range(max_results, expected, monkeypatch) -> None:
    captured = _patch_requests(
        monkeypatch,
        "brave",
        "get",
        lambda call: _FakeResponse({"web": {"results": []}}),
    )

    BraveProvider(api_key="k").search("q", max_results=max_results)

    assert captured[-1]["params"] == {"q": "q", "count": expected}


def test_brave_maps_web_rows_onto_results_and_citations(monkeypatch) -> None:
    _patch_requests(
        monkeypatch,
        "brave",
        "get",
        lambda call: _FakeResponse(
            {
                "web": {
                    "results": [
                        {
                            "title": "Hit",
                            "url": "https://hit",
                            "description": "desc",
                            "age": "2 days ago",
                        },
                        {"url": "https://bare"},
                    ]
                }
            }
        ),
    )

    response = BraveProvider(api_key="k").search("q")

    assert response.provider == "brave"
    assert response.model == "brave-search"
    assert response.answer == ""
    assert [sr.title for sr in response.search_results] == ["Hit", ""]
    assert response.search_results[0].snippet == "desc"
    assert response.search_results[0].date == "2 days ago"
    assert response.search_results[0].source == "Brave"
    assert response.search_results[1].snippet == ""
    assert [c.id for c in response.citations] == [1, 2]
    assert response.citations[0].url == "https://hit"


@pytest.mark.parametrize("payload", [{}, {"web": {}}])
def test_brave_empty_envelope_yields_an_empty_response(payload, monkeypatch) -> None:
    _patch_requests(monkeypatch, "brave", "get", lambda call: _FakeResponse(payload))

    response = BraveProvider(api_key="k").search("q")

    assert response.search_results == []
    assert response.citations == []
    assert response.metadata == {"finish_reason": "stop"}


def test_brave_raises_on_non_200_response(monkeypatch) -> None:
    _patch_requests(
        monkeypatch,
        "brave",
        "get",
        lambda call: _FakeResponse(status_code=429, text="rate limited"),
    )

    with pytest.raises(Exception, match="Brave API error: 429 - rate limited"):
        BraveProvider(api_key="k").search("q")


# ---------------------------------------------------------------------------
# Perplexity -- SDK client behind a lazy property, not raw requests.
# ---------------------------------------------------------------------------


def _fake_client(completion):
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: completion))
    )


def test_perplexity_maps_choices_usage_and_citations_matched_by_url() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content="the answer"), finish_reason="stop")
        ],
        model="sonar",
        usage=SimpleNamespace(
            prompt_tokens=11,
            completion_tokens=7,
            total_tokens=18,
            cost=SimpleNamespace(
                total_cost=0.02, input_tokens_cost=0.015, output_tokens_cost=0.005
            ),
        ),
        search_results=[
            SimpleNamespace(
                title="Src", url="https://a", snippet="snip", date="2026-01-01", source="web"
            ),
        ],
        citations=["https://a", "https://b"],
    )
    provider = PerplexityProvider(api_key="k")
    provider._client = _fake_client(completion)

    response = provider.search("q")

    assert response.answer == "the answer"
    assert response.provider == "perplexity"
    assert response.model == "sonar"
    assert response.metadata == {"finish_reason": "stop"}
    assert response.usage["prompt_tokens"] == 11
    assert response.usage["completion_tokens"] == 7
    assert response.usage["total_tokens"] == 18
    assert response.usage["cost"]["total_cost"] == 0.02
    assert response.search_results[0].title == "Src"
    assert response.search_results[0].snippet == "snip"
    assert response.search_results[0].source == "web"
    assert [c.id for c in response.citations] == [1, 2]
    assert response.citations[0].title == "Src"
    assert response.citations[0].snippet == "snip"
    assert response.citations[1].title == ""
    assert response.citations[1].url == "https://b"


def test_perplexity_tolerates_a_completion_without_optional_fields() -> None:
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None), finish_reason="stop")],
        model="sonar",
    )
    provider = PerplexityProvider(api_key="k")
    provider._client = _fake_client(completion)

    response = provider.search("q")

    assert response.answer == ""
    assert response.usage == {}
    assert response.search_results == []
    assert response.citations == []


def test_perplexity_raises_when_the_api_returns_no_choices() -> None:
    completion = SimpleNamespace(choices=[], model="sonar")
    provider = PerplexityProvider(api_key="k")
    provider._client = _fake_client(completion)

    with pytest.raises(ValueError, match="no choices"):
        provider.search("q")


def test_perplexity_reraises_client_errors_and_marks_the_call_failed(monkeypatch) -> None:
    finished: list[str] = []

    class _FakeMeter:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def finish(self, response: Any = None, *, status: str = "completed") -> None:
            finished.append(status)

    monkeypatch.setattr("deeptutor.services.llm.metrics.CallMeasurement", _FakeMeter)

    class _FailingClient:
        chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("sdk exploded"))
            )
        )

    provider = PerplexityProvider(api_key="k")
    provider._client = _FailingClient()

    with pytest.raises(RuntimeError, match="sdk exploded"):
        provider.search("q")

    assert finished == ["failed"]


def test_perplexity_reports_a_helpful_error_without_the_sdk(monkeypatch) -> None:
    provider = PerplexityProvider(api_key="k")

    with monkeypatch.context() as ctx:
        ctx.setitem(sys.modules, "perplexity", None)
        with pytest.raises(ImportError, match="pip install perplexityai"):
            provider.client
