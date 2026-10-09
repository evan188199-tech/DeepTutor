"""Failure-injection tests for the user-context branch of get_model_catalog_service.

The service resolves the catalog through the caller's context when one exists
and falls back to the deployment catalog otherwise. A broken context read must
degrade exactly like an absent one — same instance, same path — but leave a
warning instead of vanishing.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import deeptutor.multi_user.paths as paths_module
from deeptutor.services.config.model_catalog import (
    ModelCatalogService,
    get_model_catalog_service,
)
from deeptutor.services.path_service import get_path_service

_LOGGER_NAME = "deeptutor.services.config.model_catalog"


@pytest.fixture()
def isolated_catalog_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ModelCatalogService._instances.clear()
    monkeypatch.setattr(paths_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths_module, "USERS_ROOT", (tmp_path / "data" / "users").resolve())
    monkeypatch.setattr(paths_module, "SYSTEM_ROOT", (tmp_path / "data" / "system").resolve())
    monkeypatch.setattr(paths_module, "ADMIN_WORKSPACE_ROOT", (tmp_path / "data").resolve())
    monkeypatch.setattr(paths_module, "LEGACY_MULTI_USER_ROOT", tmp_path / "multi-user")
    monkeypatch.setattr(paths_module, "_path_services", {})
    return tmp_path


def _deployment_catalog_path() -> Path:
    return get_path_service().get_settings_file("model_catalog").resolve()


def test_broken_user_context_logs_and_falls_back_to_deployment_catalog(
    isolated_catalog_root: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _broken_context() -> None:
        raise RuntimeError("user context offline")

    monkeypatch.setattr("deeptutor.multi_user.context.get_current_user", _broken_context)

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        service = get_model_catalog_service()

    assert isinstance(service, ModelCatalogService)
    assert service.path == _deployment_catalog_path()
    warnings = [
        record
        for record in caplog.records
        if record.name == _LOGGER_NAME and record.levelno >= logging.WARNING
    ]
    assert any("model catalog" in record.getMessage() for record in warnings)
    assert any("user context offline" in record.getMessage() for record in warnings)


def test_local_admin_context_resolves_without_logging(
    isolated_catalog_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        service = get_model_catalog_service()

    assert isinstance(service, ModelCatalogService)
    assert service.path == _deployment_catalog_path()
    assert not [
        record
        for record in caplog.records
        if record.name == _LOGGER_NAME and record.levelno >= logging.WARNING
    ]
