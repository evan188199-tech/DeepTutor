"""Neutral-log regression tests for the web-search failure path.

Provider exception messages can echo the query, request URLs, or response
bodies. The fallback chain must surface provider names and exception type
names only — in the error log, the raised aggregate error, and the
``search_fallback`` metadata that reaches UI surfaces.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.services import search as search_module
from deeptutor.services.search.source_filter import (
    _lookup_web_risk,
    _moderation_rejections,
)

_MARKER = "PROVIDER-ECHO-MARKER-4f1c"


class _StubConsolidator:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def consolidate(self, response: Any) -> Any:
        return response


class _StubResponse:
    def __init__(self) -> None:
        self.metadata: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        return {"metadata": self.metadata, "citations": []}


def _patch_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    resolved = SimpleNamespace(
        provider="provA",
        requested_provider="provA",
        api_key="",
        base_url="",
        max_results=5,
        proxy=None,
    )
    monkeypatch.setattr(search_module, "_get_web_search_config", lambda: {"enabled": True})
    monkeypatch.setattr(search_module, "resolve_search_runtime_config", lambda: resolved)
    monkeypatch.setattr(search_module, "SUPPORTED_SEARCH_PROVIDERS", {"prova", "provb"})
    monkeypatch.setattr(search_module, "search_missing_credential", lambda *a, **k: None)
    monkeypatch.setattr(search_module, "search_fallback_candidates", lambda p: ["provB"])
    monkeypatch.setattr(search_module, "_credentials_for", lambda name, res: ("", ""))
    monkeypatch.setattr(search_module, "_get_source_filter_settings", lambda: {})
    monkeypatch.setattr(search_module, "filter_web_search_response", lambda r, **k: r)
    monkeypatch.setattr(search_module, "AnswerConsolidator", _StubConsolidator)


def test_all_providers_failing_raises_type_names_only(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _patch_runtime(monkeypatch)

    def _boom(name: str, query: str, kwargs: dict) -> Any:
        raise RuntimeError(f"provider transport failed: {_MARKER}")

    monkeypatch.setattr(search_module, "_run_provider", _boom)

    with caplog.at_level(logging.ERROR, logger="deeptutor.services.search"):
        with pytest.raises(Exception) as excinfo:
            search_module.web_search("hello")

    message = str(excinfo.value)
    assert "prova: RuntimeError" in message
    assert "provB: RuntimeError" in message
    assert _MARKER not in message

    logged = [record.getMessage() for record in caplog.records]
    assert any("[prova] Search failed: RuntimeError" in entry for entry in logged)
    assert not any(_MARKER in entry for entry in logged)


def test_fallback_metadata_records_type_names_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime(monkeypatch)
    stub = _StubResponse()

    def _flaky(name: str, query: str, kwargs: dict) -> Any:
        if name == "prova":
            raise RuntimeError(f"provider transport failed: {_MARKER}")
        return stub, False

    monkeypatch.setattr(search_module, "_run_provider", _flaky)

    result = search_module.web_search("hello")

    failures = result["metadata"]["search_fallback"]["failures"]
    assert failures == ["prova: RuntimeError"]
    assert _MARKER not in str(result)


def test_moderation_failure_log_keeps_type_name_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _failing_requester(payloads: list[str], *, api_key: str) -> list[bool]:
        raise RuntimeError(f"moderation upstream failed: {_MARKER}")

    with caplog.at_level(logging.WARNING, logger="deeptutor.services.search.source_filter"):
        decisions = _moderation_rejections(
            ["some text"], api_key="test-key", request_moderation=_failing_requester
        )

    assert decisions == {}
    logged = [record.getMessage() for record in caplog.records]
    assert any("Moderation skipped after error: RuntimeError" in entry for entry in logged)
    assert not any(_MARKER in entry for entry in logged)


def test_web_risk_failure_log_keeps_type_name_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _failing_requester(url: str, *, api_key: str) -> bool:
        raise RuntimeError(f"web risk upstream failed: {_MARKER}")

    with caplog.at_level(logging.WARNING, logger="deeptutor.services.search.source_filter"):
        outcome = _lookup_web_risk(_failing_requester, "https://example.test/a", "test-key")

    assert outcome is None
    logged = [record.getMessage() for record in caplog.records]
    assert any("Web Risk lookup skipped after error: RuntimeError" in entry for entry in logged)
    assert not any(_MARKER in entry for entry in logged)
