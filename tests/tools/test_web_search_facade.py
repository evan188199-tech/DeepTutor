"""Tests for the ``deeptutor.tools.web_search`` agent-facing facade.

``deeptutor/tools/web_search.py`` is a deliberate re-export facade over
:mod:`deeptutor.services.search` — agents import the tool from here, so the
facade surface and its delegation into the service layer are contracts of
their own. These tests pin them from the tool-layer entry point:

- surface: ``__all__`` entries resolve and are the services-layer objects
- normal path: structured response shape, provider kwargs, output file
- empty results: consolidation degrades to a "no results" answer
- failures: aggregated error after the fallback chain, per-provider skip
- validation: unknown/deprecated/none providers, disabled configuration
- introspection: ``get_current_config`` delegation without secret leakage

Every delegation test stubs the provider boundary: a facade unit test must
never touch the network.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

import deeptutor.services.search as search_service
from deeptutor.services.search import WebSearchResponse
from deeptutor.services.search.providers import _DEPRECATED_UNSUPPORTED
from deeptutor.services.search.types import Citation, SearchResult
import deeptutor.tools.web_search as facade

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _FakeProvider:
    """Records ``search`` calls; never performs IO."""

    def __init__(
        self,
        name: str,
        answer: str = "stub answer",
        supports_answer: bool = True,
    ) -> None:
        self.name = name
        self._answer = answer
        self.supports_answer = supports_answer
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def search(self, query: str, **kwargs: Any) -> WebSearchResponse:
        self.calls.append((query, kwargs))
        return WebSearchResponse(
            query=query,
            answer=self._answer,
            provider=self.name,
            citations=[],
            search_results=[],
        )


class _ResultsProvider(_FakeProvider):
    """Returns one citation plus one search result, like a real engine."""

    def search(self, query: str, **kwargs: Any) -> WebSearchResponse:
        self.calls.append((query, kwargs))
        return WebSearchResponse(
            query=query,
            answer=self._answer,
            provider=self.name,
            citations=[Citation(id=1, reference="[1]", url="https://docs.example/a", title="Docs")],
            search_results=[
                SearchResult(
                    title="Docs",
                    url="https://docs.example/a",
                    snippet="Everything about it",
                    source="docs.example",
                )
            ],
        )


def _resolved(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "provider": "tavily",
        "requested_provider": "tavily",
        "api_key": "key-123",
        "base_url": "https://tavily.example",
        "max_results": 4,
        "proxy": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _stub_runtime(
    monkeypatch: pytest.MonkeyPatch,
    resolved: SimpleNamespace | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> None:
    """Silence config/credential IO and the post-provider filter."""
    search = "deeptutor.services.search"
    monkeypatch.setattr(f"{search}._get_web_search_config", lambda: config or {"enabled": True})
    monkeypatch.setattr(f"{search}._get_source_filter_settings", lambda: {})
    monkeypatch.setattr(f"{search}.filter_web_search_response", lambda response, **kw: response)
    monkeypatch.setattr(f"{search}.search_missing_credential", lambda *a, **k: None)
    monkeypatch.setattr(f"{search}.search_provider_credentials", lambda provider: ("", ""))
    if resolved is not None:
        monkeypatch.setattr(f"{search}.resolve_search_runtime_config", lambda: resolved)


# ---------------------------------------------------------------------------
# Facade surface
# ---------------------------------------------------------------------------


class TestFacadeSurface:
    def test_all_entries_resolve_on_the_module(self) -> None:
        """Every ``__all__`` entry exists — no stale exports for agents to hit."""
        for name in facade.__all__:
            assert hasattr(facade, name), f"tools.web_search.{name} is missing"

    def test_reexports_are_identity_with_the_services_layer(self) -> None:
        """The facade must re-export, never shadow: callers share one object."""
        for name in facade.__all__:
            assert getattr(facade, name) is getattr(search_service, name), (
                f"tools.web_search.{name} is not the services-layer object"
            )
        assert facade.web_search is search_service.web_search


# ---------------------------------------------------------------------------
# Normal path: structured response and parameter assembly
# ---------------------------------------------------------------------------


class TestNormalSearchContract:
    def test_returns_structured_response_with_parsed_results(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Citations, results and the answer survive the tool-layer round trip."""
        _stub_runtime(monkeypatch, _resolved())
        provider = _ResultsProvider("tavily")
        monkeypatch.setattr("deeptutor.services.search.get_provider", lambda name, **kw: provider)

        result = facade.web_search("what is retrieval", provider="tavily")

        assert result["provider"] == "tavily"
        assert result["query"] == "what is retrieval"
        assert result["answer"] == "stub answer"
        assert result["response"]["content"] == "stub answer"
        assert [row["url"] for row in result["search_results"]] == ["https://docs.example/a"]
        assert result["citations"][0]["reference"] == "[1]"

    def test_assembles_provider_credentials_and_width(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Profile credentials, base URL and the configured width reach the engine."""
        _stub_runtime(monkeypatch, _resolved())
        provider = _ResultsProvider("tavily")
        monkeypatch.setattr("deeptutor.services.search.get_provider", lambda name, **kw: provider)

        facade.web_search("q", provider="tavily")

        kwargs = provider.calls[0][1]
        assert kwargs["api_key"] == "key-123"
        assert kwargs["base_url"] == "https://tavily.example"
        assert kwargs["max_results"] == 4

    def test_caller_max_results_override_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An explicit width beats the runtime-configured default."""
        _stub_runtime(monkeypatch, _resolved(max_results=4))
        provider = _ResultsProvider("tavily")
        monkeypatch.setattr("deeptutor.services.search.get_provider", lambda name, **kw: provider)

        facade.web_search("q", provider="tavily", max_results=7)

        assert provider.calls[0][1]["max_results"] == 7

    def test_provider_argument_is_normalized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Case and surrounding whitespace in the provider name are tolerated."""
        _stub_runtime(monkeypatch, _resolved())
        provider = _ResultsProvider("tavily")
        monkeypatch.setattr("deeptutor.services.search.get_provider", lambda name, **kw: provider)

        facade.web_search("q", provider="  TAVILY ")

        assert provider.calls[0][1]["api_key"] == "key-123"

    def test_output_dir_persists_a_result_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """``output_dir`` adds a readable ``result_file`` to the response."""
        _stub_runtime(monkeypatch, _resolved())
        provider = _ResultsProvider("tavily")
        monkeypatch.setattr("deeptutor.services.search.get_provider", lambda name, **kw: provider)

        result = facade.web_search("q", provider="tavily", output_dir=str(tmp_path))

        saved = tmp_path / result["result_file"].rsplit("/", 1)[-1]
        assert saved.exists()
        assert json.loads(saved.read_text(encoding="utf-8"))["query"] == "q"


# ---------------------------------------------------------------------------
# Empty results
# ---------------------------------------------------------------------------


class TestEmptyResults:
    def test_empty_result_set_consolidates_to_no_results_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A SERP provider returning nothing still yields a structured response."""
        _stub_runtime(monkeypatch, _resolved())
        provider = _FakeProvider("tavily", answer="", supports_answer=False)
        monkeypatch.setattr("deeptutor.services.search.get_provider", lambda name, **kw: provider)

        result = facade.web_search("obscure topic", provider="tavily")

        assert result["search_results"] == []
        assert result["citations"] == []
        assert "No results found" in result["answer"]
        assert result["response"]["content"] == result["answer"]


# ---------------------------------------------------------------------------
# Failure branches
# ---------------------------------------------------------------------------


class TestFailureBranches:
    def test_falls_back_and_reports_the_skipped_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failing engine costs its own query; the fallback is recorded."""
        _stub_runtime(monkeypatch, _resolved())
        monkeypatch.setattr(
            "deeptutor.services.search.search_fallback_candidates",
            lambda provider: ["duckduckgo"],
        )
        monkeypatch.setattr(
            "deeptutor.services.search.get_provider",
            lambda name, **kw: _ResultsProvider(name),
        )

        def failing_first(name: str, **kwargs: Any) -> _FakeProvider:
            if name == "tavily":
                raise RuntimeError("tavily down")
            return _ResultsProvider(name, answer="fallback answer")

        monkeypatch.setattr("deeptutor.services.search.get_provider", failing_first)

        result = facade.web_search("q", provider="tavily")

        assert result["provider"] == "duckduckgo"
        assert result["answer"] == "fallback answer"
        assert result["search_fallback"]["requested"] == "tavily"
        assert result["search_fallback"]["used"] == "duckduckgo"
        assert "tavily down" in result["search_fallback"]["failures"][0]

    def test_raises_aggregated_failure_when_every_provider_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no engine left, the caller sees one aggregated error."""
        _stub_runtime(monkeypatch, _resolved())
        monkeypatch.setattr(
            "deeptutor.services.search.search_fallback_candidates",
            lambda provider: ["duckduckgo"],
        )
        monkeypatch.setattr(
            "deeptutor.services.search.get_provider",
            lambda name, **kw: (_ for _ in ()).throw(RuntimeError(f"{name} down")),
        )

        with pytest.raises(Exception, match="web search failed") as excinfo:
            facade.web_search("q", provider="tavily")

        assert "tavily down" in str(excinfo.value)
        assert "duckduckgo down" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------


class TestParameterValidation:
    def test_unknown_provider_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_runtime(monkeypatch, _resolved())
        with pytest.raises(ValueError, match="Unknown search provider"):
            facade.web_search("q", provider="not_a_real_engine")

    def test_deprecated_providers_are_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_runtime(monkeypatch, _resolved())
        for name in _DEPRECATED_UNSUPPORTED:
            with pytest.raises(ValueError, match="deprecated/unsupported"):
                facade.web_search("q", provider=name)

    def test_none_provider_reports_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``provider="none"`` is valid but means no engine is configured."""
        _stub_runtime(monkeypatch, _resolved(provider="none", requested_provider="none"))

        result = facade.web_search("q", provider="none")

        assert result["error_code"] == "search_provider_not_configured"
        assert result["provider"] == "none"
        assert result["search_results"] == []

    def test_disabled_configuration_returns_sentinel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A disabled tool returns a structured sentinel, not an exception."""
        _stub_runtime(monkeypatch, config={"enabled": False})

        result = facade.web_search("q")

        assert result["error_code"] == "web_search_disabled"
        assert result["provider"] == "disabled"
        assert result["citations"] == []


# ---------------------------------------------------------------------------
# Config introspection
# ---------------------------------------------------------------------------


class TestConfigIntrospection:
    def test_get_current_config_delegates_and_never_leaks_secrets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The UI-facing config exposes presence flags, never key material."""
        monkeypatch.setattr(
            "deeptutor.services.search._get_web_search_config",
            lambda: {"enabled": True, "consolidation_template": "tpl"},
        )
        monkeypatch.setattr(
            "deeptutor.services.search.resolve_search_runtime_config",
            lambda: _resolved(
                status="ok", missing_credentials=[], fallback_reason=None, base_url=""
            ),
        )
        monkeypatch.setattr(
            "deeptutor.services.search._get_source_filter_settings",
            lambda: {"moderation_api_key": "secret", "web_risk_api_key": ""},
        )
        monkeypatch.setattr("deeptutor.services.search.get_providers_info", lambda: [])

        config = facade.get_current_config()

        assert config["enabled"] is True
        assert config["provider"] == "tavily"
        assert config["max_results"] == 4
        assert config["consolidation_template"] == "tpl"
        assert config["source_filtering"]["moderation_configured"] is True
        assert config["source_filtering"]["web_risk_configured"] is False
        assert "moderation_api_key" not in config["source_filtering"]
        assert "web_risk_api_key" not in config["source_filtering"]
