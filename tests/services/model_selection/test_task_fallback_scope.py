"""Fallback ordering when the task model is unavailable — inherit, never fail.

Every layer of ``model_selection.tasks``/``.runtime`` answers "unusable task
model" the same way: fall back (to the global chat model / to the caller's own
model) instead of raising. These tests pin the order in which each fallback
triggers, with every boundary mocked so nothing real is loaded or called.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import deeptutor.services.config.provider_runtime as provider_runtime
import deeptutor.services.llm.config as llm_config_module
import deeptutor.services.model_selection.runtime as selection_runtime
from deeptutor.services.model_selection.tasks import (
    TASK_SERVICE,
    TaskKind,
    task_llm_scope,
    task_service_configured,
)

TASK_CATALOG = {
    "services": {
        "llm": {
            "active_profile_id": "chat-1",
            "active_model_id": "chat-model",
            "profiles": [
                {
                    "id": "chat-1",
                    "binding": "openai",
                    "api_key": "sk-chat",
                    "models": [{"id": "chat-model", "model": "gpt-5"}],
                }
            ],
        },
        "task": {
            "active_profile_id": "task-1",
            "active_model_id": "task-model",
            "profiles": [
                {
                    "id": "task-1",
                    "binding": "openai",
                    "api_key": "sk-task",
                    "models": [{"id": "task-model", "model": "gpt-5-mini"}],
                }
            ],
        },
    }
}


class _StubCatalogService:
    def __init__(self, catalog: Any = None, error: Exception | None = None) -> None:
        self._catalog = catalog
        self._error = error

    def load(self) -> Any:
        if self._error is not None:
            raise self._error
        return self._catalog


@pytest.fixture()
def scope_mocks(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub every boundary ``task_llm_scope`` crosses; nothing real runs."""
    calls: dict[str, Any] = {
        "resolved": SimpleNamespace(model="gpt-5-mini"),
        "config": SimpleNamespace(model="gpt-5-mini", marker="task-config"),
        "token": object(),
        "resolve_calls": 0,
        "scoped_set_with": None,
        "scoped_reset_with": None,
    }

    def _fail_resolve(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("resolve_llm_runtime_config must not be reached")

    monkeypatch.setattr(
        "deeptutor.services.model_selection.tasks.get_model_catalog_service",
        lambda: _StubCatalogService(TASK_CATALOG),
    )
    monkeypatch.setattr(provider_runtime, "resolve_llm_runtime_config", _fail_resolve)
    monkeypatch.setattr(
        selection_runtime, "llm_config_from_resolved", lambda _resolved: calls["config"]
    )
    monkeypatch.setattr(
        llm_config_module,
        "set_scoped_llm_config",
        lambda config: calls.__setitem__("scoped_set_with", config) or calls["token"],
    )
    monkeypatch.setattr(
        llm_config_module,
        "reset_scoped_llm_config",
        lambda token: calls.__setitem__("scoped_reset_with", token),
    )
    return calls


class TestTaskLlmScopeFallbackOrder:
    def test_unreadable_catalog_inherits_before_any_resolution(
        self, scope_mocks, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "deeptutor.services.model_selection.tasks.get_model_catalog_service",
            lambda: _StubCatalogService(error=RuntimeError("catalog unreadable")),
        )

        with task_llm_scope(TaskKind.SESSION_TITLE) as config:
            assert config is None

        assert scope_mocks["resolve_calls"] == 0
        assert scope_mocks["scoped_set_with"] is None

    def test_unconfigured_task_service_inherits_without_resolution(
        self, scope_mocks, monkeypatch
    ) -> None:
        empty = {"services": {"llm": TASK_CATALOG["services"]["llm"], "task": {}}}
        monkeypatch.setattr(
            "deeptutor.services.model_selection.tasks.get_model_catalog_service",
            lambda: _StubCatalogService(empty),
        )

        with task_llm_scope(TaskKind.SESSION_TITLE) as config:
            assert config is None

        assert scope_mocks["scoped_set_with"] is None

    def test_activation_failure_inherits_instead_of_raising(self, scope_mocks, monkeypatch) -> None:
        monkeypatch.setattr(
            provider_runtime,
            "resolve_llm_runtime_config",
            lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("provider gone")),
        )

        with task_llm_scope(TaskKind.SESSION_TITLE) as config:
            assert config is None

        assert scope_mocks["scoped_set_with"] is None
        assert scope_mocks["scoped_reset_with"] is None

    def test_working_task_model_yields_the_config_and_resets_afterwards(
        self, scope_mocks, monkeypatch
    ) -> None:
        def _resolve(_catalog: Any, *, service_name: str) -> Any:
            scope_mocks["resolve_calls"] += 1
            assert service_name == TASK_SERVICE
            return scope_mocks["resolved"]

        monkeypatch.setattr(provider_runtime, "resolve_llm_runtime_config", _resolve)

        with task_llm_scope(TaskKind.SESSION_TITLE) as config:
            assert config is scope_mocks["config"]
            assert scope_mocks["scoped_set_with"] is config
            assert scope_mocks["scoped_reset_with"] is None

        assert scope_mocks["resolve_calls"] == 1
        assert scope_mocks["scoped_reset_with"] is scope_mocks["token"]

    def test_scope_resets_even_when_the_body_raises(self, scope_mocks, monkeypatch) -> None:
        monkeypatch.setattr(
            provider_runtime,
            "resolve_llm_runtime_config",
            lambda *_a, **_kw: scope_mocks["resolved"],
        )

        with pytest.raises(RuntimeError, match="caller failed"):
            with task_llm_scope(TaskKind.MASTERY_GOAL_NAME):
                raise RuntimeError("caller failed")

        assert scope_mocks["scoped_reset_with"] is scope_mocks["token"]


class TestConfiguredFallbacks:
    def test_unknown_active_profile_reads_as_not_configured(self) -> None:
        catalog = {
            "services": {
                "task": {
                    "active_profile_id": "ghost",
                    "active_model_id": "task-model",
                    "profiles": [
                        {
                            "id": "task-1",
                            "models": [{"id": "task-model", "model": "gpt-5-mini"}],
                        }
                    ],
                }
            }
        }

        assert task_service_configured(catalog) is False

    def test_reference_selection_failing_validation_reads_as_not_configured(self) -> None:
        catalog = {
            "services": {
                "llm": {
                    "profiles": [
                        {
                            "id": "chat-1",
                            "models": [{"id": "chat-model", "model": "gpt-5"}],
                        }
                    ]
                },
                "task": {
                    "mode": "reference",
                    "selection": {"profile_id": "chat-1", "model_id": "missing-model"},
                },
            }
        }

        assert task_service_configured(catalog) is False

    def test_valid_reference_selection_is_configured(self) -> None:
        catalog = {
            "services": {
                "llm": {
                    "active_profile_id": "chat-1",
                    "active_model_id": "chat-model",
                    "profiles": [
                        {
                            "id": "chat-1",
                            "models": [{"id": "chat-model", "model": "gpt-5"}],
                        }
                    ],
                },
                "task": {
                    "mode": "reference",
                    "selection": {"profile_id": "chat-1", "model_id": "chat-model"},
                },
            }
        }

        assert task_service_configured(catalog) is True

    def test_catalog_service_failure_falls_back_to_not_configured(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "deeptutor.services.model_selection.tasks.get_model_catalog_service",
            lambda: _StubCatalogService(error=RuntimeError("disk gone")),
        )

        assert task_service_configured() is False
