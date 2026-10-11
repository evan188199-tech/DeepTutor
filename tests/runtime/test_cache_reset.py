"""Focused behavior contract for ``deeptutor.runtime.cache_reset``.

The shared reset seam runs after ``--home`` / ``DEEPTUTOR_HOME`` selection:
every home-dependent cache must be refreshed, a single failure must be logged
without skipping its peers, and the whole operation must be repeatable.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import pytest


class _RecordingClearDict(dict):
    """Dict that records whether ``clear`` was actually attempted."""

    def __init__(self, *args: Any, calls: list[str], label: str) -> None:
        super().__init__(*args)
        self.calls = calls
        self.label = label

    def clear(self) -> None:
        self.calls.append(self.label)
        super().clear()


class _ExplodingClearDict(dict):
    """Dict whose ``clear`` always fails, simulating a broken cache reset."""

    def clear(self) -> None:
        raise RuntimeError("cache clear exploded")


def _patch_account_paths(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    """Point ``deeptutor.multi_user.paths`` module caches at a fake old home."""
    from deeptutor.multi_user import paths

    for name, value in {
        "PROJECT_ROOT": home,
        "ADMIN_WORKSPACE_ROOT": home / "data",
        "USERS_ROOT": home / "data" / "users",
        "SYSTEM_ROOT": home / "data" / "system",
        "LEGACY_MULTI_USER_ROOT": home / "multi-user",
        "_path_services": {"admin": object()},
        "_legacy_migration_done": True,
    }.items():
        monkeypatch.setattr(paths, name, value)


def test_full_reset_rebinds_every_home_boundary(tmp_path, monkeypatch):
    """A completed reset drops all service caches and rebinds multi-user paths."""
    from deeptutor.multi_user import paths
    from deeptutor.runtime import cache_reset
    from deeptutor.services.config.model_catalog import ModelCatalogService
    from deeptutor.services.config.runtime_settings import RuntimeSettingsService
    from deeptutor.services.path_service import PathService

    old_home = tmp_path / "old"
    new_home = tmp_path / "new"
    _patch_account_paths(monkeypatch, old_home)
    monkeypatch.setenv("DEEPTUTOR_HOME", str(new_home))

    reset_calls: list[str] = []

    def _recording_reset() -> None:
        reset_calls.append("pathservice")
        PathService._instance = None

    monkeypatch.setattr(PathService, "reset_instance", _recording_reset)
    monkeypatch.setattr(
        RuntimeSettingsService, "_instances", {"stale": object()}
    )
    monkeypatch.setattr(
        ModelCatalogService, "_instances", {"stale": object()}
    )

    cache_reset.reset_runtime_singletons()

    assert reset_calls == ["pathservice"]
    assert RuntimeSettingsService._instances == {}
    assert ModelCatalogService._instances == {}
    expected_home = Path(str(new_home)).resolve()
    assert paths.PROJECT_ROOT == expected_home
    assert paths.ADMIN_WORKSPACE_ROOT == expected_home / "data"
    assert paths.USERS_ROOT == expected_home / "data" / "users"
    assert paths.SYSTEM_ROOT == expected_home / "data" / "system"
    assert paths.LEGACY_MULTI_USER_ROOT == expected_home / "multi-user"
    assert paths._path_services == {}
    assert paths._legacy_migration_done is False


def test_pathservice_failure_is_logged_and_does_not_skip_peers(tmp_path, monkeypatch, caplog):
    """One failing reset must surface as an error while every peer still runs."""
    from deeptutor.multi_user import paths
    from deeptutor.runtime import cache_reset
    from deeptutor.services.config.model_catalog import ModelCatalogService
    from deeptutor.services.config.runtime_settings import RuntimeSettingsService
    from deeptutor.services.path_service import PathService

    old_home = tmp_path / "old"
    new_home = tmp_path / "new"
    _patch_account_paths(monkeypatch, old_home)
    monkeypatch.setenv("DEEPTUTOR_HOME", str(new_home))

    def _boom() -> None:
        raise RuntimeError("reset exploded")

    monkeypatch.setattr(PathService, "reset_instance", _boom)
    calls: list[str] = []
    monkeypatch.setattr(
        RuntimeSettingsService,
        "_instances",
        _RecordingClearDict({"stale": object()}, calls=calls, label="runtime_settings"),
    )
    monkeypatch.setattr(
        ModelCatalogService,
        "_instances",
        _RecordingClearDict({"stale": object()}, calls=calls, label="model_catalog"),
    )
    monkeypatch.setattr(
        paths,
        "_path_services",
        _RecordingClearDict({"admin": object()}, calls=calls, label="multi_user_paths"),
    )

    with caplog.at_level(logging.WARNING, logger="deeptutor.runtime.cache_reset"):
        cache_reset.reset_runtime_singletons()

    assert calls == ["runtime_settings", "model_catalog", "multi_user_paths"]
    error_records = [
        record
        for record in caplog.records
        if "PathService" in record.getMessage()
    ]
    assert error_records, "failed PathService reset was swallowed silently"
    assert any(record.levelno >= logging.ERROR for record in error_records)


@pytest.mark.parametrize(
    ("module_name", "owner_name", "service_label"),
    [
        (
            "deeptutor.services.config.runtime_settings",
            "RuntimeSettingsService",
            "RuntimeSettings",
        ),
        (
            "deeptutor.services.config.model_catalog",
            "ModelCatalogService",
            "ModelCatalog",
        ),
    ],
)
def test_cache_clear_failure_is_logged_without_raising(
    module_name: str, owner_name: str, service_label: str, monkeypatch, caplog
):
    """An exploding ``_instances.clear()`` must warn and must not propagate."""
    import importlib

    from deeptutor.runtime import cache_reset

    owner = getattr(importlib.import_module(module_name), owner_name)
    monkeypatch.setattr(
        owner, "_instances", _ExplodingClearDict({"stale": object()})
    )

    with caplog.at_level(logging.WARNING, logger="deeptutor.runtime.cache_reset"):
        cache_reset.reset_runtime_singletons()

    records = [
        record for record in caplog.records if service_label in record.getMessage()
    ]
    assert records, f"failed {service_label} cache clear was swallowed silently"
    assert all(record.levelno == logging.WARNING for record in records)


def test_multi_user_rebind_failure_is_logged_without_raising(tmp_path, monkeypatch, caplog):
    """A failing multi-user rebind must warn and must not propagate."""
    from deeptutor.runtime import cache_reset
    from deeptutor.runtime import home as runtime_home

    def _boom(*_args: Any, **_kwargs: Any) -> Path:
        raise RuntimeError("home exploded")

    monkeypatch.setattr(runtime_home, "get_runtime_home", _boom)
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "new"))

    with caplog.at_level(logging.WARNING, logger="deeptutor.runtime.cache_reset"):
        cache_reset.reset_runtime_singletons()

    records = [
        record
        for record in caplog.records
        if "Multi-user path cache reset failed" in record.getMessage()
    ]
    assert records, "failed multi-user rebind was swallowed silently"
    assert all(record.levelno == logging.WARNING for record in records)


def test_multi_user_rebind_skipped_when_module_not_imported(monkeypatch):
    """The rebind block must not run before multi-user paths were imported."""
    from deeptutor.multi_user import paths
    from deeptutor.runtime import cache_reset

    sentinel = Path("/sentinel-not-imported")
    _patch_account_paths(monkeypatch, sentinel)
    monkeypatch.delitem(sys.modules, "deeptutor.multi_user.paths")

    cache_reset.reset_runtime_singletons()

    assert paths.PROJECT_ROOT == sentinel
    assert paths._legacy_migration_done is True


def test_reset_is_idempotent(tmp_path, monkeypatch):
    """Calling the reset twice must be safe and produce the same clean state."""
    from deeptutor.multi_user import paths
    from deeptutor.runtime import cache_reset
    from deeptutor.services.config.model_catalog import ModelCatalogService
    from deeptutor.services.config.runtime_settings import RuntimeSettingsService
    from deeptutor.services.path_service import PathService

    new_home = Path(str(tmp_path / "new")).resolve()
    monkeypatch.setenv("DEEPTUTOR_HOME", str(new_home))

    reset_calls: list[str] = []

    def _recording_reset() -> None:
        reset_calls.append("pathservice")
        PathService._instance = None

    monkeypatch.setattr(PathService, "reset_instance", _recording_reset)

    for _ in range(2):
        monkeypatch.setattr(
            RuntimeSettingsService, "_instances", {"stale": object()}
        )
        monkeypatch.setattr(
            ModelCatalogService, "_instances", {"stale": object()}
        )
        monkeypatch.setattr(paths, "_path_services", {"admin": object()})
        monkeypatch.setattr(paths, "_legacy_migration_done", True)

        cache_reset.reset_runtime_singletons()

        assert RuntimeSettingsService._instances == {}
        assert ModelCatalogService._instances == {}
        assert paths.PROJECT_ROOT == new_home
        assert paths.USERS_ROOT == new_home / "data" / "users"
        assert paths.SYSTEM_ROOT == new_home / "data" / "system"
        assert paths._path_services == {}
        assert paths._legacy_migration_done is False

    assert reset_calls == ["pathservice", "pathservice"]
