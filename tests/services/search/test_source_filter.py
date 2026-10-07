"""Unit tests for the shared web-search reference source filter."""

from __future__ import annotations

from deeptutor.services.search.source_filter import (
    _domains,
    filter_web_search_response,
    resolve_moderation_api_key,
    resolve_web_risk_api_key,
    settings_from_config,
)
from deeptutor.services.search.types import Citation, SearchResult, WebSearchResponse


def _response(
    citations: list[Citation], results: list[SearchResult], answer: str = ""
) -> WebSearchResponse:
    return WebSearchResponse(
        query="source filter",
        answer=answer,
        provider="test",
        citations=citations,
        search_results=results,
    )


def test_blocked_domains_match_subdomains_but_not_superstrings() -> None:
    response = _response(
        [
            Citation(id=1, reference="[1]", url="https://spam.example/a"),
            Citation(id=2, reference="[2]", url="https://news.spam.example/b"),
            Citation(id=3, reference="[3]", url="https://notspam.example/c"),
        ],
        [],
    )

    filtered = filter_web_search_response(response, blocked_domains=["spam.example"])

    assert [c.url for c in filtered.citations] == ["https://notspam.example/c"]
    assert [(c.id, c.reference) for c in filtered.citations] == [(1, "[1]")]
    meta = filtered.metadata["source_filter"]
    assert meta["removed_citations"] == 2
    assert meta["rejected_reasons"] == ["blocked_domain"]
    assert meta["rejected_hosts"] == ["spam.example", "news.spam.example"]
    assert meta["citations_renumbered"] is True


def test_trusted_allowlist_rejects_hosts_outside_it() -> None:
    response = _response(
        [
            Citation(id=1, reference="[1]", url="https://classroom.edu/x"),
            Citation(id=2, reference="[2]", url="https://sub.classroom.edu/y"),
            Citation(id=3, reference="[3]", url="https://elsewhere.example/z"),
        ],
        [],
    )

    filtered = filter_web_search_response(response, trusted_domains=["classroom.edu"])

    assert [c.url for c in filtered.citations] == [
        "https://classroom.edu/x",
        "https://sub.classroom.edu/y",
    ]
    meta = filtered.metadata["source_filter"]
    assert meta["rejected_reasons"] == ["untrusted_domain"]
    assert meta["rejected_hosts"] == ["elsewhere.example"]


def test_empty_or_blank_domain_lists_do_not_filter_by_domain() -> None:
    citations = [
        Citation(id=1, reference="[1]", url="https://a.example/1"),
        Citation(id=2, reference="[2]", url="https://b.example/2"),
        Citation(id=3, reference="[3]", url="https://c.example/3"),
    ]

    open_policy = filter_web_search_response(_response(list(citations), []))
    blank_policy = filter_web_search_response(
        _response(list(citations), []), blocked_domains="", trusted_domains=" , "
    )

    for filtered in (open_policy, blank_policy):
        assert [c.url for c in filtered.citations] == [c.url for c in citations]
        meta = filtered.metadata["source_filter"]
        assert meta["removed_citations"] == 0
        assert meta["removed_search_results"] == 0
        assert meta["rejected_reasons"] == []


def test_malformed_and_unroutable_urls_are_rejected_with_reasons() -> None:
    response = _response(
        [
            Citation(id=1, reference="[1]", url=""),
            Citation(id=2, reference="[2]", url="https://x.example/a b"),
            Citation(id=3, reference="[3]", url="https://x.example:99999/p"),
            Citation(id=4, reference="[4]", url="https:///path"),
            Citation(id=5, reference="[5]", url="file:///etc/passwd"),
        ],
        [
            SearchResult(title="Loopback", url="http://localhost/", snippet=""),
            SearchResult(title="Bare host", url="https://intranet/", snippet=""),
            SearchResult(title="Suffix host", url="https://printer.lan/", snippet=""),
        ],
    )

    filtered = filter_web_search_response(response)

    assert filtered.citations == []
    assert filtered.search_results == []
    meta = filtered.metadata["source_filter"]
    assert meta["removed_citations"] == 5
    assert meta["removed_search_results"] == 3
    assert meta["rejected_reasons"] == [
        "missing_url",
        "malformed_url",
        "missing_hostname",
        "unsupported_scheme",
        "non_public_hostname",
    ]
    assert meta["rejected_hosts"] == ["localhost", "intranet", "printer.lan"]


def test_unexpected_domain_input_types_are_tolerated() -> None:
    citations = [
        Citation(id=1, reference="[1]", url="https://a.example/1"),
        Citation(id=2, reference="[2]", url="https://b.example/2"),
    ]

    filtered = filter_web_search_response(
        _response(list(citations), []), blocked_domains=42, trusted_domains={"oops": True}
    )

    assert [c.url for c in filtered.citations] == [c.url for c in citations]
    meta = filtered.metadata["source_filter"]
    assert meta["removed_citations"] == 0
    assert meta["rejected_hosts"] == []


def test_domain_lists_normalize_wildcards_idna_and_duplicates() -> None:
    assert _domains(["*.Spam.Example.", "münchen.de", "MÜNCHEN.DE", "", None, 7]) == (
        "spam.example",
        "xn--mnchen-3ya.de",
        "7",
    )
    assert _domains("a.example, b.example") == ("a.example", "b.example")

    response = _response([Citation(id=1, reference="[1]", url="https://sub.spam.example/x")], [])

    filtered = filter_web_search_response(response, blocked_domains="*.spam.example")

    assert filtered.citations == []
    assert filtered.metadata["source_filter"]["rejected_reasons"] == ["blocked_domain"]


def test_blocked_policy_matches_unicode_and_trailing_dot_hosts() -> None:
    response = _response(
        [
            Citation(id=1, reference="[1]", url="https://münchen.de/p"),
            Citation(id=2, reference="[2]", url="https://xn--mnchen-3ya.de./q"),
            Citation(id=3, reference="[3]", url="https://other.example/r"),
        ],
        [],
    )

    filtered = filter_web_search_response(response, blocked_domains=["münchen.de"])

    assert [c.url for c in filtered.citations] == ["https://other.example/r"]
    meta = filtered.metadata["source_filter"]
    assert meta["rejected_reasons"] == ["blocked_domain"]
    assert meta["rejected_hosts"] == ["xn--mnchen-3ya.de"]


def test_filtering_everything_leaves_empty_results_and_invalidates_answer() -> None:
    response = _response(
        [
            Citation(id=1, reference="[1]", url="https://spam.example/a"),
            Citation(id=2, reference="[2]", url="https://ads.spam.example/b"),
        ],
        [SearchResult(title="Loopback", url="http://localhost/", snippet="")],
        answer="See [1] and [2].",
    )

    filtered = filter_web_search_response(response, blocked_domains=["spam.example"])

    assert filtered.citations == []
    assert filtered.search_results == []
    assert filtered.answer == ""
    meta = filtered.metadata["source_filter"]
    assert meta["removed_citations"] == 2
    assert meta["removed_search_results"] == 1
    assert meta["answer_invalidated"] is True
    assert meta["citations_renumbered"] is True


def test_search_result_only_removal_keeps_answer_and_labels() -> None:
    response = _response(
        [Citation(id=1, reference="[1]", url="https://a.example/1")],
        [
            SearchResult(title="Good", url="https://b.example/2", snippet=""),
            SearchResult(title="Loopback", url="http://localhost/", snippet=""),
        ],
        answer="Text citing [1].",
    )

    filtered = filter_web_search_response(response)

    assert [c.id for c in filtered.citations] == [1]
    assert [r.title for r in filtered.search_results] == ["Good"]
    assert filtered.answer == "Text citing [1]."
    meta = filtered.metadata["source_filter"]
    assert meta["removed_search_results"] == 1
    assert meta["answer_invalidated"] is False
    assert "citations_renumbered" not in meta


def test_disabled_filter_returns_response_untouched() -> None:
    response = _response(
        [
            Citation(id=1, reference="[1]", url="javascript:alert(1)"),
            Citation(id=2, reference="[2]", url="http://localhost/"),
        ],
        [],
        answer="Untouched prose.",
    )

    filtered = filter_web_search_response(response, enabled=False, blocked_domains=["spam.example"])

    assert filtered is response
    assert [c.url for c in filtered.citations] == ["javascript:alert(1)", "http://localhost/"]
    assert filtered.answer == "Untouched prose."
    assert "source_filter" not in filtered.metadata


def test_clean_response_keeps_labels_and_records_policy_metadata() -> None:
    response = _response(
        [
            Citation(id=1, reference="[1]", url="https://a.example/1"),
            Citation(id=2, reference="[2]", url="https://b.example/2"),
        ],
        [SearchResult(title="Good", url="https://c.example/3", snippet="")],
    )

    filtered = filter_web_search_response(response)

    assert [c.id for c in filtered.citations] == [1, 2]
    assert [c.reference for c in filtered.citations] == ["[1]", "[2]"]
    assert filtered.answer == ""
    meta = filtered.metadata["source_filter"]
    assert meta["removed_citations"] == 0
    assert meta["removed_search_results"] == 0
    assert meta["answer_invalidated"] is False
    assert meta["content_filtering"] is True
    assert "citations_renumbered" not in meta


def test_settings_from_config_tolerates_malformed_sections(monkeypatch) -> None:
    for name in (
        "OPENAI_API_KEY",
        "DEEPTUTOR_OPENAI_API_KEY",
        "GOOGLE_WEB_RISK_API_KEY",
        "WEB_RISK_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    defaults = settings_from_config(None)
    assert defaults["enabled"] is True
    assert defaults["blocked_domains"] == ()
    assert defaults["trusted_domains"] == ()
    assert defaults["moderation_api_key"] == ""
    assert defaults["web_risk_api_key"] == ""
    assert settings_from_config({"source_filtering": "junk"}) == defaults

    monkeypatch.setenv("OPENAI_API_KEY", "sk-mod")
    monkeypatch.setenv("WEB_RISK_API_KEY", "wr-key")
    assert resolve_moderation_api_key() == "sk-mod"
    assert resolve_web_risk_api_key() == "wr-key"

    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.delenv("WEB_RISK_API_KEY")
    monkeypatch.setenv("DEEPTUTOR_OPENAI_API_KEY", "sk-alt")
    monkeypatch.setenv("GOOGLE_WEB_RISK_API_KEY", "wr-alt")
    assert resolve_moderation_api_key() == "sk-alt"
    assert resolve_web_risk_api_key() == "wr-alt"

    strict = settings_from_config(
        {"source_filtering": {"use_moderation": True, "use_web_risk": "0"}}
    )
    assert strict["moderation_api_key"] == "sk-alt"
    assert strict["web_risk_api_key"] == ""
