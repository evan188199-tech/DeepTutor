"""``task_llm_scope``: per-kind installation and inherit-on-failure fallbacks."""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.llm.config import _SCOPED_LLM_CONFIG
from deeptutor.services.model_selection.tasks import (
    TASK_KINDS,
    TaskKind,
    task_kind_payload,
    task_llm_scope,
)


class _FixedCatalog:
    """Stand-in for the global catalog service, serving one in-memory catalog."""

    def __init__(self, catalog: dict[str, Any]) -> None:
        self._catalog = catalog

    def load(self) -> dict[str, Any]:
        return self._catalog


def _catalog_with_task_model(tmp_path: Any, model: str = "gpt-5-mini") -> dict[str, Any]:
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    catalog = service.load()
    catalog["services"]["llm"]["profiles"] = [
        {
            "id": "llm-1",
            "name": "OpenAI",
            "binding": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-live",
            "models": [{"id": "llm-model", "model": "gpt-5"}],
        }
    ]
    catalog["services"]["llm"]["active_profile_id"] = "llm-1"
    catalog["services"]["llm"]["active_model_id"] = "llm-model"
    catalog["services"]["task"].update(
        {
            "profiles": [
                {
                    "id": "task-1",
                    "name": "OpenAI",
                    "binding": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "sk-task",
                    "models": [{"id": "task-model", "model": model}],
                }
            ],
            "active_profile_id": "task-1",
            "active_model_id": "task-model",
        }
    )
    return catalog


def test_task_kind_payload_lists_every_kind_in_page_order():
    payload = task_kind_payload()

    assert payload == [{"id": str(spec.kind), "group": spec.group} for spec in TASK_KINDS]
    assert {item["id"] for item in payload} == {str(kind) for kind in TaskKind}
    assert all(item["group"] for item in payload)


def test_scope_yields_none_when_the_catalog_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
):
    def _boom() -> None:
        raise RuntimeError("unreadable catalog")

    monkeypatch.setattr(
        "deeptutor.services.model_selection.tasks.get_model_catalog_service", _boom
    )

    with task_llm_scope(TaskKind.SESSION_TITLE) as config:
        assert config is None
    assert _SCOPED_LLM_CONFIG.get() is None


def test_scope_yields_none_when_no_task_model_is_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
):
    empty = ModelCatalogService(path=tmp_path / "model_catalog.json").load()
    monkeypatch.setattr(
        "deeptutor.services.model_selection.tasks.get_model_catalog_service",
        lambda: _FixedCatalog(empty),
    )

    with task_llm_scope(TaskKind.SESSION_TITLE) as config:
        assert config is None
    assert _SCOPED_LLM_CONFIG.get() is None


def test_scope_installs_the_task_model_and_restores_the_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
):
    catalog = _catalog_with_task_model(tmp_path)
    monkeypatch.setattr(
        "deeptutor.services.model_selection.tasks.get_model_catalog_service",
        lambda: _FixedCatalog(catalog),
    )
    assert _SCOPED_LLM_CONFIG.get() is None

    with task_llm_scope(TaskKind.SESSION_TITLE) as config:
        assert config is not None
        assert config.model == "gpt-5-mini"
        assert _SCOPED_LLM_CONFIG.get() is config

    assert _SCOPED_LLM_CONFIG.get() is None


def test_scope_yields_none_when_activation_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
):
    catalog = _catalog_with_task_model(tmp_path)
    monkeypatch.setattr(
        "deeptutor.services.model_selection.tasks.get_model_catalog_service",
        lambda: _FixedCatalog(catalog),
    )

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("provider gone")

    monkeypatch.setattr(
        "deeptutor.services.config.provider_runtime.resolve_llm_runtime_config", _boom
    )

    with task_llm_scope(TaskKind.SESSION_TITLE) as config:
        assert config is None
    assert _SCOPED_LLM_CONFIG.get() is None
