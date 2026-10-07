"""Consolidation contract: raw SERP rows must merge into one stable answer.

`AnswerConsolidator` turns a `WebSearchResponse` into the answer string the
user sees. Three contracts matter:

* merge — every section the provider returned (knowledge graph, answer box,
  content previews, links, academic attributes) shows up in one answer;
* order — rows keep the provider's ranking with stable ``[n]`` numbering and
  respect ``max_results`` in template, fallback and LLM-prompt modes alike;
* degrade — a provider without a template, rows with missing optional fields
  and empty result sets still produce a coherent answer instead of crashing.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.search import consolidation
from deeptutor.services.search.consolidation import AnswerConsolidator
from deeptutor.services.search.types import SearchResult, WebSearchResponse


def _result(**overrides: Any) -> SearchResult:
    fields: dict[str, Any] = {
        "title": "row-a",
        "url": "https://example.org/a",
        "snippet": "snippet-a",
    }
    fields.update(overrides)
    return SearchResult(**fields)


def _response(**overrides: Any) -> WebSearchResponse:
    fields: dict[str, Any] = {
        "query": "attention",
        "answer": "",
        "provider": "acme",
        "search_results": [_result()],
    }
    fields.update(overrides)
    return WebSearchResponse(**fields)


# ---------------------------------------------------------------------------
# Merge: provider-specific sections land in one answer
# ---------------------------------------------------------------------------


def test_serper_merges_knowledge_graph_answerbox_results_and_paa() -> None:
    response = _response(
        provider="serper",
        search_results=[_result(title="Attention Is All You Need")],
        metadata={
            "knowledgeGraph": {
                "title": "Transformer",
                "type": "model",
                "description": "A neural architecture.",
                "attributes": {"Layers": "6"},
            },
            "answerBox": {"answer": "12 layers", "title": "Wiki", "link": "https://wiki"},
            "peopleAlsoAsk": [
                {
                    "question": "Who wrote it?",
                    "snippet": "Vaswani et al.",
                    "title": "W",
                    "link": "https://w",
                }
            ],
            "relatedSearches": [{"query": "bert"}, {"query": "gpt"}],
        },
    )

    answer = AnswerConsolidator(max_results=5).consolidate(response).answer

    assert "## Transformer (model)" in answer
    assert "A neural architecture." in answer
    assert "- **Layers**: 6" in answer
    assert "### Direct Answer" in answer
    assert "12 layers" in answer
    assert "**[1] Attention Is All You Need**" in answer
    assert "### People Also Ask" in answer
    assert "**Q: Who wrote it?**" in answer
    assert "Related searches: bert, gpt" in answer


def test_serper_omits_absent_metadata_sections() -> None:
    response = _response(provider="serper", metadata={})

    answer = AnswerConsolidator().consolidate(response).answer

    assert "### Search Results" in answer
    assert "**[1] row-a**" in answer
    assert "Direct Answer" not in answer
    assert "People Also Ask" not in answer
    assert "Related searches" not in answer


def test_serper_merges_per_result_optional_fields_and_sitelinks() -> None:
    response = _response(
        provider="serper",
        search_results=[
            _result(
                title="dated",
                date="2017-06-12",
                sitelinks=[{"title": "PDF", "link": "https://example.org/pdf"}],
            ),
            _result(title="bare"),
        ],
    )

    answer = AnswerConsolidator(max_results=5).consolidate(response).answer

    assert "📅 2017-06-12" in answer
    assert "└ Related: [PDF](https://example.org/pdf)" in answer
    # The bare row renders without either marker, so each appears exactly once.
    assert answer.count("📅") == 1
    assert answer.count("└ Related:") == 1


def test_jina_merges_content_preview_and_date() -> None:
    # The provider puts enrichment data on result attributes and never fills
    # metadata["links"]/["images"], so those template sections must stay absent
    # rather than render (or crash) on data that does not exist.
    response = _response(
        provider="jina",
        search_results=[
            _result(
                title="Doc",
                content="Full text body",
                attributes={"date": "2026-01-01", "tokens": 42},
            )
        ],
    )

    answer = AnswerConsolidator().consolidate(response).answer

    assert "## [1] Doc" in answer
    assert "📅 *2026-01-01*" in answer
    assert "*snippet-a*" in answer
    assert "### Content Preview" in answer
    assert "Full text body" in answer
    assert "1 results via Jina Reader" in answer
    assert "(no-content mode)" not in answer
    assert "### Extracted Links" not in answer
    assert "### Images Found" not in answer


def test_jina_caps_long_content_previews() -> None:
    response = _response(provider="jina", search_results=[_result(content="x" * 2500)])

    answer = AnswerConsolidator().consolidate(response).answer

    assert "x" * 2000 in answer
    assert "x" * 2001 not in answer
    assert "Content truncated" in answer
    assert "many tokens total" in answer


def test_jina_marks_no_content_mode() -> None:
    response = _response(provider="jina", search_results=[_result(content="")])

    answer = AnswerConsolidator().consolidate(response).answer

    assert "### Content Preview" not in answer
    assert "*snippet-a*" in answer
    assert "1 results via Jina Reader (no-content mode)" in answer


def test_scholar_template_merges_academic_attributes() -> None:
    response = _response(
        provider="serper_scholar",
        search_results=[
            _result(
                title="Attention Is All You Need",
                attributes={
                    "year": 2017,
                    "publicationInfo": "A Vaswani, N Shazeer - 2017",
                    "pdfUrl": "https://example.org/attention.pdf",
                    "citedBy": 120000,
                },
            )
        ],
    )

    answer = AnswerConsolidator().consolidate(response).answer

    assert '### Academic Results for "attention"' in answer
    assert "**[1] Attention Is All You Need** (2017)" in answer
    assert "*A Vaswani, N Shazeer - 2017*" in answer
    assert "📄 [PDF](https://example.org/attention.pdf)" in answer
    assert "Cited by: 120000" in answer
    assert "1 academic papers found via Google Scholar" in answer


def test_scholar_template_serves_the_serply_scholar_alias() -> None:
    response = _response(provider="serply_scholar")

    answer = AnswerConsolidator().consolidate(response).answer

    assert "academic papers found via Google Scholar" in answer


def test_provider_matching_is_case_insensitive() -> None:
    response = _response(provider="SERPER")

    answer = AnswerConsolidator().consolidate(response).answer

    assert '### Search Results for "attention"' in answer
    assert "Academic Results" not in answer


def test_custom_template_overrides_provider_template_and_escapes_html() -> None:
    response = _response(
        provider="serper",
        search_results=[_result(title="<b>bold</b>"), _result(title="row-b")],
    )

    consolidator = AnswerConsolidator(custom_template="Q={{ query }} T={{ results[0].title }}")
    answer = consolidator.consolidate(response).answer

    assert answer == "Q=attention T=&lt;b&gt;bold&lt;/b&gt;"


# ---------------------------------------------------------------------------
# Order: provider ranking is preserved and max_results is honored everywhere
# ---------------------------------------------------------------------------


def test_results_keep_provider_order_with_stable_numbering() -> None:
    response = _response(
        provider="serper",
        search_results=[_result(title="first"), _result(title="second"), _result(title="third")],
    )

    answer = AnswerConsolidator(max_results=5).consolidate(response).answer

    assert (
        answer.index("**[1] first**")
        < answer.index("**[2] second**")
        < answer.index("**[3] third**")
    )


def test_max_results_truncates_rendered_rows_in_template_and_fallback() -> None:
    rows = [_result(title=f"row-{i}") for i in "abcd"]

    template_answer = (
        AnswerConsolidator(max_results=2)
        .consolidate(_response(provider="serper", search_results=rows))
        .answer
    )
    fallback_answer = (
        AnswerConsolidator(max_results=2)
        .consolidate(_response(provider="acme", search_results=rows))
        .answer
    )

    for answer in (template_answer, fallback_answer):
        assert "**[1] row-a**" in answer
        assert "**[2] row-b**" in answer
        assert "[3] row-c" not in answer
        assert "[4] row-d" not in answer
    # The fallback footer reports how many rows the provider returned.
    assert "4 results via acme" in fallback_answer


# ---------------------------------------------------------------------------
# Degrade: missing templates, missing fields and empty result sets
# ---------------------------------------------------------------------------


def test_unknown_provider_falls_back_to_simple_formatting() -> None:
    response = _response(
        provider="acme",
        search_results=[
            _result(title="row-a", source="example.org"),
            _result(title="row-b", source="example.org"),
        ],
    )

    answer = AnswerConsolidator(max_results=5).consolidate(response).answer

    assert '### Search Results for "attention"' in answer
    assert "**[1] row-a**" in answer
    assert "snippet-a" in answer
    assert "*Source: example.org*" in answer
    assert "🔗 [https://example.org/a](https://example.org/a)" in answer
    assert "---\n*2 results via acme*" in answer


def test_fallback_skips_missing_optional_fields_per_row() -> None:
    response = _response(
        provider="acme",
        search_results=[
            _result(title="full", source="example.org"),
            _result(title="bare", snippet="", source=""),
        ],
    )

    answer = AnswerConsolidator(max_results=5).consolidate(response).answer

    assert "**[1] full**" in answer
    assert "**[2] bare**" in answer
    # Only the full row carries snippet/source lines; the bare row still renders.
    assert answer.count("*Source:") == 1
    assert answer.count("snippet-a") == 1


def test_empty_results_render_the_no_results_contract() -> None:
    response = _response(provider="acme", search_results=[])

    answer = AnswerConsolidator().consolidate(response).answer

    assert answer == '### Search Results for "attention"\n\n*No results found.*'


def test_broken_custom_template_fails_loudly() -> None:
    syntax = AnswerConsolidator(custom_template="{% for %}")
    with pytest.raises(Exception):
        syntax.consolidate(_response())

    runtime = AnswerConsolidator(custom_template="{{ 1 / (results|length - results|length) }}")
    with pytest.raises(ZeroDivisionError):
        runtime.consolidate(_response())


# ---------------------------------------------------------------------------
# LLM synthesis mode: offline fake client
# ---------------------------------------------------------------------------


class _FakeLLMClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def complete_sync(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return "SYNTHESIZED"


def test_llm_mode_synthesizes_through_the_configured_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeLLMClient()
    monkeypatch.setattr(consolidation, "get_llm_client", lambda: fake)

    response = _response(
        search_results=[
            _result(title="first"),
            _result(title="second", content="y" * 5001),
            _result(title="third"),
        ]
    )
    consolidator = AnswerConsolidator(
        use_llm=True,
        llm_config={"max_tokens": 77, "temperature": 0.9, "system_prompt": "Be terse."},
        max_results=2,
    )

    assert consolidator.consolidate(response).answer == "SYNTHESIZED"

    (call,) = fake.calls
    assert call["max_tokens"] == 77
    assert call["temperature"] == 0.9
    assert call["system_prompt"] == "Be terse."
    assert "Query: attention" in call["prompt"]
    assert "[1] first" in call["prompt"]
    assert "[2] second" in call["prompt"]
    assert "third" not in call["prompt"]
    assert "y" * 5000 in call["prompt"]
    assert "y" * 5001 not in call["prompt"]


def test_llm_mode_applies_default_knobs_without_config(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeLLMClient()
    monkeypatch.setattr(consolidation, "get_llm_client", lambda: fake)

    response = _response()
    AnswerConsolidator(use_llm=True).consolidate(response)

    (call,) = fake.calls
    assert call["max_tokens"] == 1000
    assert call["temperature"] == 0.3
    assert "search result consolidator" in call["system_prompt"]
