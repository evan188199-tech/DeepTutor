"""Unit tests for the PageIndex client adapter and credential/config surface.

Every SDK touchpoint runs against fakes, so the adapter's calling contract is
verified without network access or a real PageIndex deployment.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.services.rag.pipelines.pageindex import client as client_mod
from deeptutor.services.rag.pipelines.pageindex.client import PageIndexClient
from deeptutor.services.rag.pipelines.pageindex.config import (
    PageIndexConfig,
    get_pageindex_config,
    is_pageindex_configured,
)


# ---------------------------------------------------------------- client --
def _runtime_config(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "model": "claude-x",
        "binding": "anthropic",
        "provider_name": None,
        "api_key": "sk-ant",
        "base_url": "https://relay.example/v1",
        "api_version": "",
        "extra_headers": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _patch_runtime_config(monkeypatch: pytest.MonkeyPatch, cfg: SimpleNamespace) -> None:
    monkeypatch.setattr(
        "deeptutor.services.config.resolve_llm_runtime_config", lambda *a, **k: cfg
    )


def test_resolve_requires_an_active_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime_config(monkeypatch, _runtime_config(model="   "))
    with pytest.raises(RuntimeError, match="needs an active LLM"):
        client_mod.resolve_oss_sdk_config()


@pytest.mark.parametrize("binding", ["codebuddy", "no-such-binding"])
def test_resolve_rejects_oauth_and_unknown_bindings(
    monkeypatch: pytest.MonkeyPatch, binding: str
) -> None:
    _patch_runtime_config(monkeypatch, _runtime_config(binding=binding))
    with pytest.raises(RuntimeError, match="API-key or local LLM profile"):
        client_mod.resolve_oss_sdk_config()


def test_resolve_rejects_unsupported_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = SimpleNamespace(
        name="pigeon", is_oauth=False, backend="carrier_pigeon", strip_model_prefix=False
    )
    monkeypatch.setattr(client_mod, "find_by_name", lambda _name: spec)
    _patch_runtime_config(monkeypatch, _runtime_config())
    with pytest.raises(RuntimeError, match="not supported"):
        client_mod.resolve_oss_sdk_config()


def test_anthropic_binding_maps_prefix_and_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _runtime_config(api_version="2023-06-01")
    _patch_runtime_config(monkeypatch, cfg)

    model, backend = client_mod.resolve_oss_sdk_config()

    assert model == "anthropic/claude-x"
    assert backend == {
        "api_key": "sk-ant",
        "api_base": "https://relay.example/v1",
        "api_version": "2023-06-01",
    }


def test_model_keeps_existing_provider_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime_config(monkeypatch, _runtime_config(model="anthropic/claude-x"))

    model, _backend = client_mod.resolve_oss_sdk_config()

    assert model == "anthropic/claude-x"


def test_azure_binding_maps_azure_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime_config(
        monkeypatch,
        _runtime_config(binding="azure_openai", model="gpt-4o", api_version="2024-10-01"),
    )

    model, backend = client_mod.resolve_oss_sdk_config()

    assert model == "azure/gpt-4o"
    assert backend["api_version"] == "2024-10-01"


def test_openai_compat_binding_defaults_key_and_header_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _runtime_config(
        binding="custom",
        model="m1",
        api_key="",
        api_version="ignored",
        extra_headers={"X-A": "b"},
    )
    _patch_runtime_config(monkeypatch, cfg)

    model, backend = client_mod.resolve_oss_sdk_config()

    assert model == "openai/m1"
    assert backend["api_key"] == "sk-no-key-required"
    assert backend["default_headers"] == {"X-A": "b"}
    assert "api_version" not in backend
    assert "extra_headers" not in backend


def test_binding_falls_back_to_provider_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runtime_config(monkeypatch, _runtime_config(binding=None, provider_name="anthropic"))

    model, _backend = client_mod.resolve_oss_sdk_config()

    assert model == "anthropic/claude-x"


def test_local_client_binds_indexing_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[dict[str, Any]] = []

    class _LocalType:
        def __init__(self, **kwargs: Any) -> None:
            created.append(kwargs)
            self.storage_path = kwargs["storage_path"]

    monkeypatch.setattr(client_mod, "_sdk_types", lambda: (object, _LocalType))
    monkeypatch.setattr(
        client_mod, "resolve_oss_sdk_config", lambda: ("openai/m1", {"api_key": "k"})
    )

    client = PageIndexClient.local("/kb/pageindex")

    assert created == [
        {
            "storage_path": "/kb/pageindex",
            "index_model": "openai/m1",
            "summary_model": "openai/m1",
            "index_backend": {"api_key": "k"},
        }
    ]
    assert client.sdk_client.storage_path == "/kb/pageindex"


def test_local_read_skips_credential_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[dict[str, Any]] = []

    class _LocalType:
        def __init__(self, **kwargs: Any) -> None:
            created.append(kwargs)

    monkeypatch.setattr(client_mod, "_sdk_types", lambda: (object, _LocalType))

    def _boom() -> tuple[str, dict[str, Any]]:
        raise AssertionError("read-only clients must not resolve indexing credentials")

    monkeypatch.setattr(client_mod, "resolve_oss_sdk_config", _boom)

    PageIndexClient.local_read("/kb/pageindex")

    assert created == [{"storage_path": "/kb/pageindex"}]


@pytest.mark.parametrize("payload", [{}, {"doc_id": ""}, {"other": 1}, "not-a-dict", None])
def test_submit_document_requires_a_doc_id(payload: Any) -> None:
    class _SDK:
        def submit_document(self, path: str, *, mode: str | None, wait: bool):
            return payload

    with pytest.raises(RuntimeError, match="no doc_id"):
        asyncio.run(PageIndexClient(_SDK()).submit_document("a.pdf", mode="flash"))


def test_delete_document_delegates_to_sdk() -> None:
    deleted: list[str] = []

    class _SDK:
        def delete_document(self, doc_id: str) -> None:
            deleted.append(doc_id)

    assert asyncio.run(PageIndexClient(_SDK()).delete_document("doc-9")) is True
    assert deleted == ["doc-9"]


# ---------------------------------------------------------------- config --
def _patch_settings(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> None:
    class _Service:
        def load_pageindex(self) -> dict[str, Any]:
            if error is not None:
                raise error
            return payload if payload is not None else {"api_key": ""}

    monkeypatch.setattr(
        "deeptutor.services.config.get_runtime_settings_service", lambda: _Service()
    )


def test_config_requires_key_when_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, {"api_key": "   "})
    with pytest.raises(RuntimeError, match="API key is not configured"):
        get_pageindex_config()


def test_config_returns_stripped_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, {"api_key": " pi-key "})
    assert get_pageindex_config() == PageIndexConfig(api_key="pi-key")


def test_config_optional_key_allows_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, {})
    assert get_pageindex_config(require_key=False) == PageIndexConfig(api_key="")


def test_configured_flag_tracks_key_and_service_health(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, {"api_key": "k"})
    assert is_pageindex_configured() is True

    _patch_settings(monkeypatch, {"api_key": ""})
    assert is_pageindex_configured() is False

    _patch_settings(monkeypatch, error=RuntimeError("settings unavailable"))
    assert is_pageindex_configured() is False
