"""Tests for the ``deeptutor.tools.web_search`` agent-facing wrapper.

The module is a deliberate re-export facade over
:mod:`deeptutor.services.search` — agents import from here, so the wrapper
surface (``__all__``, re-export identity) and the delegation into the
service layer are contracts of their own. Every delegation test stubs the
provider boundary: a wrapper unit test must never touch the network.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import deeptutor.services.search as search_service
import deeptutor.tools.web_search as wrapper
from deeptutor.services.search import WebSearchResponse

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _FakeProvider:
    """Records ``search`` calls; never performs IO."""

    def __init__(self, name: str, answer: str) -> None:
        self.name = name
        self._answer = answer
        self.supports_answer = True
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def search(self, query: str, **kwargs: Any) -> WebSearchResponse:
        self.calls.append((query, kwargs))
        return WebSearchResponse(query=query, answer=self._answer, provider=self.name)


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
) -> None:
    """Silence config/credential IO and the post-provider filter."""
    search = "deeptutor.services.search"
    monkeypatch.setattr(f"{search}._get_web_search_config", lambda: {"enabled": True})
    monkeypatch.setattr(f"{search}._get_source_filter_settings", lambda: {})
    monkeypatch.setattr(f"{search}.filter_web_search_response", lambda response, **kw: response)
    monkeypatch.setattr(f"{search}.search_missing_credential", lambda *a, **k: None)
    if resolved is not None:
        monkeypatch.setattr(f"{search}.resolve_search_runtime_config", lambda: resolved)


# ---------------------------------------------------------------------------
# Wrapper surface
# ---------------------------------------------------------------------------


def test_wrapper_exposes_the_documented_surface() -> None:
    """Every ``__all__`` entry resolves on the module — no stale exports."""
    for name in wrapper.__all__:
        assert hasattr(wrapper, name), f"tools.web_search.{name} is missing"
        assert getattr(wrapper, name) is not None


def test_wrapper_reexports_are_identity_with_the_services_layer() -> None:
    """The facade must re-export, never shadow: callers share one object."""
    for name in wrapper.__all__:
        assert getattr(wrapper, name) is getattr(search_service, name), (
            f"tools.web_search.{name} is not the services-layer object"
        )


# ---------------------------------------------------------------------------
# Delegation: parameter assembly
# ---------------------------------------------------------------------------


def test_web_search_assembles_provider_kwargs_and_returns_structured_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Credentials, base URL and the runtime default width reach the provider."""
    resolved = _resolved()
    _stub_runtime(monkeypatch, resolved)
    provider = _FakeProvider("tavily", "stub")
    monkeypatch.setattr("deeptutor.services.search.get_provider", lambda name, **kw: provider)

    result = wrapper.web_search("what is retrieval", provider="tavily")

    assert len(provider.calls) == 1
    query, kwargs = provider.calls[0]
    assert query == "what is retrieval"
    assert kwargs["api_key"] == "key-123"
    assert kwargs["base_url"] == "https://tavily.example"
    assert kwargs["max_results"] == 4
    assert result["provider"] == "tavily"
    assert result["query"] == "what is retrieval"
    assert result["answer"] == "stub"
    assert result["response"]["content"] == "stub"


def test_web_search_lets_callers_override_max_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit width wins over the runtime-configured default."""
    _stub_runtime(monkeypatch, _resolved(max_results=4))
    provider = _FakeProvider("tavily", "stub")
    monkeypatch.setattr("deeptutor.services.search.get_provider", lambda name, **kw: provider)

    wrapper.web_search("q", provider="tavily", max_results=7)

    assert provider.calls[0][1]["max_results"] == 7


def test_web_search_injects_proxy_from_runtime_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The configured proxy is added unless the caller supplies one."""
    _stub_runtime(monkeypatch, _resolved(proxy="http://proxy.local:8080"))
    provider = _FakeProvider("tavily", "stub")
    monkeypatch.setattr("deeptutor.services.search.get_provider", lambda name, **kw: provider)

    wrapper.web_search("q", provider="tavily")
    assert provider.calls[0][1]["proxy"] == "http://proxy.local:8080"

    wrapper.web_search("q", provider="tavily", proxy="http://caller.local:3128")
    assert provider.calls[1][1]["proxy"] == "http://caller.local:3128"


# ---------------------------------------------------------------------------
# Delegation: disabled / unconfigured branches
# ---------------------------------------------------------------------------


def test_web_search_reports_disabled_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disabled tool returns a structured sentinel, not an exception."""
    monkeypatch.setattr(
        "deeptutor.services.search._get_web_search_config", lambda: {"enabled": False}
    )

    result = wrapper.web_search("q")

    assert result["error_code"] == "web_search_disabled"
    assert result["provider"] == "disabled"
    assert result["citations"] == []
    assert result["search_results"] == []


def test_web_search_without_provider_reports_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``provider="none"`` means search is enabled but no engine is chosen."""
    _stub_runtime(monkeypatch, _resolved(provider="none", requested_provider="none"))

    result = wrapper.web_search("q", provider="none")

    assert result["error_code"] == "search_provider_not_configured"
    assert result["provider"] == "none"
    assert result["search_results"] == []


# ---------------------------------------------------------------------------
# Delegation: failure branches
# ---------------------------------------------------------------------------


def test_web_search_falls_back_when_the_first_provider_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing engine costs its own query, not the whole turn."""
    _stub_runtime(monkeypatch, _resolved())
    monkeypatch.setattr(
        "deeptutor.services.search.search_fallback_candidates",
        lambda provider: ["duckduckgo"],
    )
    monkeypatch.setattr(
        "deeptutor.services.search._credentials_for",
        lambda name, resolved: ("key-123", None) if name == "tavily" else (None, None),
    )

    def get_provider(name: str, **kwargs: Any) -> _FakeProvider:
        if name == "tavily":
            raise RuntimeError("tavily down")
        return _FakeProvider(name, "fallback answer")

    monkeypatch.setattr("deeptutor.services.search.get_provider", get_provider)

    result = wrapper.web_search("q", provider="tavily")

    assert result["provider"] == "duckduckgo"
    assert result["answer"] == "fallback answer"
    assert result["search_fallback"] == {
        "requested": "tavily",
        "used": "duckduckgo",
        "failures": ["tavily: tavily down"],
    }


def test_web_search_raises_after_every_provider_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no engine left the caller sees the aggregated failure."""
    _stub_runtime(monkeypatch, _resolved())
    monkeypatch.setattr(
        "deeptutor.services.search.search_fallback_candidates",
        lambda provider: ["duckduckgo"],
    )

    def always_down(name: str, **kwargs: Any) -> _FakeProvider:
        raise RuntimeError(f"{name} down")

    monkeypatch.setattr("deeptutor.services.search.get_provider", always_down)

    with pytest.raises(Exception, match="web search failed"):
        wrapper.web_search("q", provider="tavily")


# ---------------------------------------------------------------------------
# Config introspection
# ---------------------------------------------------------------------------


def test_get_current_config_surfaces_runtime_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The UI-facing config never leaks secret material, only presence flags."""
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

    config = wrapper.get_current_config()

    assert config["enabled"] is True
    assert config["provider"] == "tavily"
    assert config["max_results"] == 4
    assert config["consolidation_template"] == "tpl"
    assert config["providers"] == []
    assert config["supported_providers"] == sorted(config["supported_providers"])
    assert config["source_filtering"]["moderation_configured"] is True
    assert config["source_filtering"]["web_risk_configured"] is False
    assert "moderation_api_key" not in config["source_filtering"]
    assert "web_risk_api_key" not in config["source_filtering"]
