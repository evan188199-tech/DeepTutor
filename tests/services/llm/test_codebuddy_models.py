"""Tests for the CodeBuddy model catalog wrapper (provider_core.codebuddy_models)."""

from __future__ import annotations

import importlib.util
import sys
from types import SimpleNamespace

import pytest

import deeptutor.services.llm.provider_core.codebuddy_models as codebuddy_models
from deeptutor.services.codebuddy_credentials import FALLBACK_MODEL_CATALOG
from deeptutor.services.llm.provider_core.codebuddy_models import fetch_codebuddy_models
from deeptutor.services.llm.provider_core import codebuddy_provider

_REAL_FIND_SPEC = importlib.util.find_spec


class ProbeRecorder:
    """Stands in for the CLI subprocess probe; never touches the network."""

    def __init__(self, result: list[str] | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[str | None] = []

    async def __call__(self, api_key: str | None = None) -> list[str]:
        self.calls.append(api_key)
        if self.error is not None:
            raise self.error
        return self.result if self.result is not None else []


def _install_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cached: list[str],
    sdk_installed: bool,
    probe: ProbeRecorder | None = None,
) -> None:
    monkeypatch.setattr(codebuddy_models, "cached_model_catalog", lambda: cached)

    def fake_find_spec(name: str, *args: object, **kwargs: object):
        if name == "codebuddy_agent_sdk":
            return SimpleNamespace(name="codebuddy_agent_sdk") if sdk_installed else None
        return _REAL_FIND_SPEC(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    monkeypatch.delitem(sys.modules, "codebuddy_agent_sdk", raising=False)
    if probe is not None:
        monkeypatch.setattr(
            codebuddy_provider,
            "fetch_codebuddy_models",
            probe,
        )


@pytest.mark.asyncio
async def test_cached_catalog_short_circuits_cli_probe(monkeypatch) -> None:
    probe = ProbeRecorder(result=["probe-model"])
    _install_env(
        monkeypatch,
        cached=["hy3", "glm-5.2"],
        sdk_installed=True,
        probe=probe,
    )

    assert await fetch_codebuddy_models("secret") == ["hy3", "glm-5.2"]
    assert probe.calls == []


@pytest.mark.parametrize(
    ("cached_models", "expected"),
    [
        (["hy3"], ["hy3"]),
        (["glm-4.5", "hy3", "default"], ["glm-4.5", "hy3", "default"]),
        (["only-one"], ["only-one"]),
    ],
)
@pytest.mark.asyncio
async def test_cached_catalog_passthrough_table(monkeypatch, cached_models, expected) -> None:
    _install_env(monkeypatch, cached=cached_models, sdk_installed=False)

    assert await fetch_codebuddy_models() == expected


@pytest.mark.asyncio
async def test_cli_probe_result_returned_and_api_key_forwarded(monkeypatch) -> None:
    probe = ProbeRecorder(result=["hy3", "glm-5.2"])
    _install_env(monkeypatch, cached=[], sdk_installed=True, probe=probe)

    assert await fetch_codebuddy_models("secret") == ["hy3", "glm-5.2"]
    assert probe.calls == ["secret"]


@pytest.mark.asyncio
async def test_cli_probe_forwards_default_none_api_key(monkeypatch) -> None:
    probe = ProbeRecorder(result=["m1"])
    _install_env(monkeypatch, cached=[], sdk_installed=True, probe=probe)

    assert await fetch_codebuddy_models() == ["m1"]
    assert probe.calls == [None]


@pytest.mark.parametrize(
    ("probe_result", "probe_error", "expected"),
    [
        (["hy3"], None, ["hy3"]),
        ([], None, list(FALLBACK_MODEL_CATALOG)),
        (None, RuntimeError("probe exploded"), list(FALLBACK_MODEL_CATALOG)),
    ],
)
@pytest.mark.asyncio
async def test_probe_outcome_table_falls_back(monkeypatch, probe_result, probe_error, expected) -> None:
    probe = ProbeRecorder(result=probe_result, error=probe_error)
    _install_env(monkeypatch, cached=[], sdk_installed=True, probe=probe)

    assert await fetch_codebuddy_models("key") == expected


@pytest.mark.asyncio
async def test_sdk_missing_skips_probe_and_uses_fallback(monkeypatch) -> None:
    probe = ProbeRecorder(result=["should-not-run"])
    _install_env(monkeypatch, cached=[], sdk_installed=False, probe=probe)

    assert await fetch_codebuddy_models("secret") == list(FALLBACK_MODEL_CATALOG)
    assert probe.calls == []


@pytest.mark.asyncio
async def test_fallback_catalog_returns_fresh_copy_each_call(monkeypatch) -> None:
    _install_env(monkeypatch, cached=[], sdk_installed=False)

    first = await fetch_codebuddy_models()
    first.append("mutated")
    second = await fetch_codebuddy_models()

    assert second == list(FALLBACK_MODEL_CATALOG)
    assert FALLBACK_MODEL_CATALOG == ("default",)
