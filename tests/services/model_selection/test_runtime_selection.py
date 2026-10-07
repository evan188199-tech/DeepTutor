"""``runtime.py``: resolved-config conversion and request-scoped activation."""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.config.provider_runtime import ResolvedLLMConfig
from deeptutor.services.llm import config as llm_config_module
from deeptutor.services.llm.config import LLMConfig, _SCOPED_LLM_CONFIG
from deeptutor.services.model_selection import LLMSelection
from deeptutor.services.model_selection.runtime import (
    activate_llm_selection,
    llm_config_from_resolved,
    reset_llm_selection,
    resolve_llm_config_for_selection,
)


def _resolved() -> ResolvedLLMConfig:
    return ResolvedLLMConfig(
        model="gpt-5-mini",
        provider_name="OpenAI",
        provider_mode="cloud",
        binding="openai",
        api_key="sk-test",
        base_url="https://api.openai.com/v1",
        effective_url="https://api.openai.com/v1/chat/completions",
        api_version=None,
        extra_headers={"x-a": "b"},
        wire_api="chat",
        api_format="auto",
        reasoning_effort="low",
        context_window=400000,
    )


def test_llm_config_from_resolved_maps_every_field():
    config = llm_config_from_resolved(_resolved())

    assert isinstance(config, LLMConfig)
    assert config.model == "gpt-5-mini"
    assert config.api_key == "sk-test"
    assert config.base_url == "https://api.openai.com/v1"
    assert config.effective_url == "https://api.openai.com/v1/chat/completions"
    assert config.binding == "openai"
    assert config.provider_name == "OpenAI"
    assert config.provider_mode == "cloud"
    assert config.api_version is None
    assert config.extra_headers == {"x-a": "b"}
    # LLMConfig.__post_init__ normalizes the endpoint pair; "chat" on the
    # openai spec lands on "auto" with api_format derived alongside.
    assert config.wire_api == "auto"
    assert config.reasoning_effort == "low"
    assert config.context_window == 400000


def test_no_selection_falls_back_to_the_global_config(monkeypatch: pytest.MonkeyPatch):
    sentinel = LLMConfig(model="global-model", api_key="sk", base_url=None, effective_url=None)
    monkeypatch.setattr(llm_config_module, "get_llm_config", lambda: sentinel)

    assert resolve_llm_config_for_selection(None) is sentinel


def test_a_selection_resolves_through_provider_runtime(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    def fake_resolve(*args: Any, **kwargs: Any) -> ResolvedLLMConfig:
        captured.update(kwargs)
        return _resolved()

    monkeypatch.setattr(
        "deeptutor.services.model_selection.runtime.resolve_llm_runtime_config",
        fake_resolve,
    )
    selection = LLMSelection(profile_id="p1", model_id="m1")

    config = resolve_llm_config_for_selection(selection)

    assert captured["llm_selection"] is selection
    assert config.model == "gpt-5-mini"


def test_a_garbage_selection_is_rejected():
    with pytest.raises(ValueError, match="expected an object"):
        activate_llm_selection("not-a-selection")
    assert _SCOPED_LLM_CONFIG.get() is None


def test_activate_installs_a_scoped_config_and_reset_restores_the_context(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "deeptutor.services.model_selection.runtime.resolve_llm_runtime_config",
        lambda *args, **kwargs: _resolved(),
    )
    assert _SCOPED_LLM_CONFIG.get() is None

    config, token = activate_llm_selection(LLMSelection(profile_id="p1", model_id="m1"))

    assert config.model == "gpt-5-mini"
    assert _SCOPED_LLM_CONFIG.get() is config

    reset_llm_selection(token)

    assert _SCOPED_LLM_CONFIG.get() is None


def test_reset_tolerates_a_none_token():
    reset_llm_selection(None)
    assert _SCOPED_LLM_CONFIG.get() is None
