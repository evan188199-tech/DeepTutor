"""Fallback contract for the settings router's silent read paths (DT-22).

``load_ui_settings`` (``deeptutor/api/routers/settings.py``, ``except
Exception: pass`` around the read/merge) and ``tour_status`` (the same
swallow around ``read_text``) reset every preference to defaults whenever
``interface.json`` / ``.tour_cache.json`` cannot be read — a corrupt file
or an unreadable one is then indistinguishable from a fresh install, and
nothing reaches the logs.

These tests pin the fallback *values* (green today) and require the
failure paths to emit a warning naming the file (red today — that is the
fix card's green target). No product code is changed by this branch.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from deeptutor.api.routers import settings as settings_router

TOUR_INACTIVE = {
    "active": False,
    "status": "none",
    "launch_at": None,
    "redirect_at": None,
}

CORRUPT_PAYLOADS = [
    pytest.param('{"theme": "snow", ', id="truncated-json"),
    pytest.param("\x00\x01binary-garbage{\x7f", id="binary-garbage"),
]

_permissions_can_fail_reads = pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="permission bits cannot make a read fail when running as root "
    "or on platforms without POSIX permission bits",
)


@contextlib.contextmanager
def _unreadable(path: Path) -> Iterator[None]:
    path.chmod(0o000)
    try:
        yield
    finally:
        path.chmod(0o644)


def _warning_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING
    ]


def test_missing_ui_settings_file_serves_defaults_without_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    settings_file = tmp_path / "interface.json"
    monkeypatch.setattr(settings_router, "_settings_file", lambda: settings_file)

    with caplog.at_level(logging.WARNING):
        loaded = settings_router.load_ui_settings()

    assert loaded == settings_router.DEFAULT_UI_SETTINGS.copy()
    assert _warning_messages(caplog) == []


@pytest.mark.parametrize("corrupt_payload", CORRUPT_PAYLOADS)
def test_corrupt_ui_settings_json_serves_defaults_and_warns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    corrupt_payload: str,
) -> None:
    settings_file = tmp_path / "interface.json"
    settings_file.write_text(corrupt_payload, encoding="utf-8")
    monkeypatch.setattr(settings_router, "_settings_file", lambda: settings_file)

    with caplog.at_level(logging.WARNING):
        loaded = settings_router.load_ui_settings()

    assert loaded == settings_router.DEFAULT_UI_SETTINGS.copy()
    warnings = _warning_messages(caplog)
    assert warnings, "corrupt interface.json fell back silently; the fix must log a warning"
    assert any("interface.json" in message for message in warnings)


@_permissions_can_fail_reads
def test_unreadable_ui_settings_file_serves_defaults_and_warns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    settings_file = tmp_path / "interface.json"
    settings_file.write_text('{"theme": "snow"}', encoding="utf-8")
    monkeypatch.setattr(settings_router, "_settings_file", lambda: settings_file)

    with _unreadable(settings_file), caplog.at_level(logging.WARNING):
        loaded = settings_router.load_ui_settings()

    assert loaded == settings_router.DEFAULT_UI_SETTINGS.copy()
    warnings = _warning_messages(caplog)
    assert warnings, "unreadable interface.json fell back silently; the fix must log a warning"
    assert any("interface.json" in message for message in warnings)


@pytest.mark.asyncio
async def test_missing_tour_cache_reports_inactive_without_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    tour_cache = tmp_path / ".tour_cache.json"
    monkeypatch.setattr(settings_router, "_tour_cache_file", lambda: tour_cache)

    with caplog.at_level(logging.WARNING):
        payload = await settings_router.tour_status()

    assert payload == TOUR_INACTIVE
    assert _warning_messages(caplog) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt_payload", CORRUPT_PAYLOADS)
async def test_corrupt_tour_cache_json_reports_inactive_and_warns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    corrupt_payload: str,
) -> None:
    tour_cache = tmp_path / ".tour_cache.json"
    tour_cache.write_text(corrupt_payload, encoding="utf-8")
    monkeypatch.setattr(settings_router, "_tour_cache_file", lambda: tour_cache)

    with caplog.at_level(logging.WARNING):
        payload = await settings_router.tour_status()

    assert payload == TOUR_INACTIVE
    warnings = _warning_messages(caplog)
    assert warnings, "corrupt .tour_cache.json fell back silently; the fix must log a warning"
    assert any(".tour_cache.json" in message for message in warnings)


@pytest.mark.asyncio
@_permissions_can_fail_reads
async def test_unreadable_tour_cache_reports_inactive_and_warns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    tour_cache = tmp_path / ".tour_cache.json"
    tour_cache.write_text('{"status": "completed"}', encoding="utf-8")
    monkeypatch.setattr(settings_router, "_tour_cache_file", lambda: tour_cache)

    with _unreadable(tour_cache), caplog.at_level(logging.WARNING):
        payload = await settings_router.tour_status()

    assert payload == TOUR_INACTIVE
    warnings = _warning_messages(caplog)
    assert warnings, "unreadable .tour_cache.json fell back silently; the fix must log a warning"
    assert any(".tour_cache.json" in message for message in warnings)
