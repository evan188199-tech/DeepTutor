"""Regression tests for shared retrieval-mode resolution (kb_config.json handling)."""

from __future__ import annotations

import json
import logging

from deeptutor.services.rag.pipelines.modes import resolve_kb_mode

SUPPORTED = ("hybrid", "local", "global")
LOGGER_NAME = "deeptutor.services.rag.pipelines.modes"


def _write_config(tmp_path, payload) -> None:
    (tmp_path / "kb_config.json").write_text(
        payload if isinstance(payload, str) else json.dumps(payload),
        encoding="utf-8",
    )


def test_missing_config_returns_default_without_warning(tmp_path, caplog) -> None:
    """A missing kb_config.json is a legal state: default mode, no log noise."""
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        mode = resolve_kb_mode(
            tmp_path, "kb", "lightrag", explicit=None, supported=SUPPORTED, default="hybrid"
        )

    assert mode == "hybrid"
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_valid_config_still_resolves_kb_level_mode(tmp_path) -> None:
    _write_config(tmp_path, {"knowledge_bases": {"kb": {"search_mode": "local"}}})

    mode = resolve_kb_mode(
        tmp_path, "kb", "lightrag", explicit=None, supported=SUPPORTED, default="hybrid"
    )

    assert mode == "local"


def test_corrupt_config_warns_and_returns_default(tmp_path, caplog) -> None:
    """An existing but unparseable kb_config.json must not fail silently."""
    _write_config(tmp_path, "{not valid json")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        mode = resolve_kb_mode(
            tmp_path, "kb", "lightrag", explicit=None, supported=SUPPORTED, default="hybrid"
        )

    assert mode == "hybrid"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "corrupt kb_config.json must be reported"
    assert "kb_config.json" in warnings[0].getMessage()


def test_non_object_config_warns_and_returns_default(tmp_path, caplog) -> None:
    """JSON that parses but is not an object is unusable for mode resolution."""
    _write_config(tmp_path, "[1, 2, 3]")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        mode = resolve_kb_mode(
            tmp_path, "kb", "lightrag", explicit=None, supported=SUPPORTED, default="hybrid"
        )

    assert mode == "hybrid"
    assert [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_corrupt_config_keeps_explicit_override(tmp_path, caplog) -> None:
    _write_config(tmp_path, "{not valid json")

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        mode = resolve_kb_mode(
            tmp_path, "kb", "lightrag", explicit="global", supported=SUPPORTED, default="hybrid"
        )

    assert mode == "global"
