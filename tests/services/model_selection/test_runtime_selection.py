"""``model_selection.runtime`` — request-scoped selection ↔ config conversion.

The fallback here: no selection means the caller's ambient global config; a
selection means resolution through ``resolve_llm_runtime_config``. All
boundaries are stubbed, so no catalog is read and no network is touched.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.config.provider_runtime import ResolvedLLMConfig
import deeptutor.services.llm.config as llm_config_module
from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.model_selection import LLMSelection
import deeptutor.services.model_selection.runtime as selection_runtime
from deeptutor.services.model_selection.runtime import (
    activate_llm_selection,
    llm_config_from_resolved,
    reset_llm_selection,
    resolve_llm_config_for_selection,
)

_RESOLVED = ResolvedLLMConfig(
    model="gpt-5-mini",
    provider_name="openai",
    provider_mode="standard",
    binding_hint="openai",
    binding="openai",
    api_key="sk-task",
    base_url="https://api.openai.com/v1",
    effective_url="https://api.openai.com/v1",
    api_version=None,
    extra_headers={"x-task": "1"},
    reasoning_effort="low",
    context_window=128000,
)


class TestResolvedToConfigMapping:
    def test_every_resolved_field_lands_on_the_config(self) -> None:
        config = llm_config_from_resolved(_RESOLVED)

        assert isinstance(config, LLMConfig)
        assert config.model == "gpt-5-mini"
        assert config.api_key == "sk-task"
        assert config.base_url == "https://api.openai.com/v1"
        assert config.effective_url == "https://api.openai.com/v1"
        assert config.binding == "openai"
        assert config.provider_name == "openai"
        assert config.provider_mode == "standard"
        assert config.api_version is None
        assert config.extra_headers == {"x-task": "1"}
        assert config.reasoning_effort == "low"
        assert config.context_window == 128000


class TestSelectionFallback:
    def test_no_selection_falls_back_to_the_global_config(self, monkeypatch) -> None:
        sentinel = LLMConfig(model="global-model", api_key="sk-global")
        monkeypatch.setattr(llm_config_module, "get_llm_config", lambda: sentinel)

        def _fail_resolve(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("no selection must not resolve a runtime config")

        monkeypatch.setattr(selection_runtime, "resolve_llm_runtime_config", _fail_resolve)

        assert resolve_llm_config_for_selection(None) is sentinel

    def test_selection_resolves_through_the_runtime_config(self, monkeypatch) -> None:
        seen: dict[str, Any] = {}

        def _fake_resolve(catalog: Any = None, *, llm_selection: Any = None) -> Any:
            seen["catalog"] = catalog
            seen["llm_selection"] = llm_selection
            return _RESOLVED

        monkeypatch.setattr(selection_runtime, "resolve_llm_runtime_config", _fake_resolve)

        selection = LLMSelection(profile_id="p1", model_id="m1")
        config = resolve_llm_config_for_selection(selection)

        assert seen["catalog"] is None
        assert seen["llm_selection"] is selection
        assert config.model == "gpt-5-mini"
        assert config.reasoning_effort == "low"


class TestScopedActivation:
    def test_activate_resolves_then_installs_and_returns_the_token(self, monkeypatch) -> None:
        token = object()
        installed: list[Any] = []
        monkeypatch.setattr(
            llm_config_module,
            "set_scoped_llm_config",
            lambda config: installed.append(config) or token,
        )
        monkeypatch.setattr(
            selection_runtime, "resolve_llm_runtime_config", lambda *a, **kw: _RESOLVED
        )

        config, returned = activate_llm_selection(
            {"profile_id": "p1", "model_id": "m1", "reasoning_effort": "high"}
        )

        assert returned is token
        assert installed == [config]
        assert config.model == "gpt-5-mini"

    def test_reset_clears_the_scoped_config_token(self, monkeypatch) -> None:
        token = object()
        reset_with: list[Any] = []
        monkeypatch.setattr(llm_config_module, "reset_scoped_llm_config", reset_with.append)

        reset_llm_selection(token)

        assert reset_with == [token]

    def test_reset_without_a_token_is_a_no_op(self, monkeypatch) -> None:
        def _fail(_token: Any) -> None:
            raise AssertionError("None token must not be reset")

        monkeypatch.setattr(llm_config_module, "reset_scoped_llm_config", _fail)

        reset_llm_selection(None)
