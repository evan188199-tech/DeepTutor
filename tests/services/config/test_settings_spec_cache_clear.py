"""Failure-injection tests for _clear_runtime_caches in settings_spec.

The cache drop after a catalog write is best effort: a failure must not fail
the write, but it delays the effect of the change and so must be logged.
"""

from __future__ import annotations

import logging

import pytest

from deeptutor.services.config.settings_spec import _clear_runtime_caches

_LOGGER_NAME = "deeptutor.services.config.settings_spec"


def test_cache_clear_failure_is_logged_and_not_fatal(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _broken_clear() -> None:
        raise RuntimeError("cache drop offline")

    monkeypatch.setattr("deeptutor.services.llm.clear_llm_config_cache", _broken_clear)

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        _clear_runtime_caches()

    warnings = [
        record
        for record in caplog.records
        if record.name == _LOGGER_NAME and record.levelno >= logging.WARNING
    ]
    assert any("runtime config caches" in record.getMessage() for record in warnings)
    assert any("cache drop offline" in record.getMessage() for record in warnings)


def test_cache_clear_success_stays_silent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[bool] = []

    monkeypatch.setattr("deeptutor.services.llm.clear_llm_config_cache", lambda: calls.append(True))

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        _clear_runtime_caches()

    assert calls == [True]
    assert not [
        record
        for record in caplog.records
        if record.name == _LOGGER_NAME and record.levelno >= logging.WARNING
    ]
