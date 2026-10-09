"""Boundary tests for deeptutor.utils.json_parser truncation and fallback paths.

Complements the existing ``tests/utils/test_json_parser.py`` coverage: this
file pins the truncation/repair interplay, the ``safe_json_loads`` non-string
TypeError branch, the public ``repair_json`` patch hook, the raw_decode scan
boundary, and the ``logger_instance`` routing contract.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from deeptutor.utils.json_parser import (
    parse_json_response,
    repair_json,
    safe_json_loads,
)

_requires_repair = pytest.mark.skipif(repair_json is None, reason="json-repair not installed")


class TestParseJsonResponseTruncation:
    """Truncated payloads are completed by the repair pass."""

    @_requires_repair
    def test_truncated_object_is_completed(self) -> None:
        assert parse_json_response('{"key": "valu', fallback=None) == {"key": "valu"}

    @_requires_repair
    def test_truncated_array_is_completed(self) -> None:
        assert parse_json_response("[1, 2,", fallback=None) == [1, 2]

    @_requires_repair
    def test_truncated_nested_structure_is_completed(self) -> None:
        raw = '{"a": {"b": [1, 2'
        assert parse_json_response(raw, fallback=None) == {"a": {"b": [1, 2]}}

    @_requires_repair
    def test_truncated_payload_inside_fence_is_completed(self) -> None:
        raw = '```json\n{"key": "valu'
        assert parse_json_response(raw, fallback=None) == {"key": "valu"}

    def test_truncated_payload_with_repair_disabled_returns_fallback(self) -> None:
        with patch("deeptutor.utils.json_parser.repair_json", None):
            result = parse_json_response("[1, 2,", fallback=["none"])
        assert result == ["none"]


class TestParseJsonResponseRepairHook:
    """The module-level ``repair_json`` alias is the documented patch point."""

    def test_custom_repair_hook_result_is_parsed(self) -> None:
        calls: list[str] = []

        def fake_repair(raw: str) -> str:
            calls.append(raw)
            return '{"fixed": true}'

        with patch("deeptutor.utils.json_parser.repair_json", fake_repair):
            result = parse_json_response("@@broken@@", fallback=None)

        assert result == {"fixed": True}
        assert calls == ["@@broken@@"]

    def test_repair_hook_failure_returns_fallback(self) -> None:
        def broken_repair(raw: str) -> str:
            return "still not json"

        with patch("deeptutor.utils.json_parser.repair_json", broken_repair):
            result = parse_json_response("@@broken@@", fallback={"kept": 1})

        assert result == {"kept": 1}


class TestParseJsonResponseDecodeScan:
    """raw_decode scan boundary: payload bytes the strict decoder rejects."""

    def test_bom_prefixed_payload_is_decoded(self) -> None:
        raw = "﻿" + '{"a": 1}'
        assert parse_json_response(raw, fallback=None) == {"a": 1}


class TestParseJsonResponseLoggerContract:
    def test_empty_response_warning_uses_provided_logger(self, caplog) -> None:
        provided = logging.getLogger("test.json_parser_boundary.provided")

        with caplog.at_level(logging.WARNING, logger=provided.name):
            result = parse_json_response("", logger_instance=provided, fallback=None)

        assert result is None
        from_provided = [r for r in caplog.records if r.name == provided.name]
        assert from_provided
        assert "empty response" in from_provided[-1].getMessage().lower()


class TestSafeJsonLoadsNonString:
    """Non-string input hits the TypeError branch, not a crash."""

    def test_none_returns_default_fallback(self) -> None:
        assert safe_json_loads(None) == {}  # type: ignore[arg-type]

    def test_mapping_returns_custom_fallback(self) -> None:
        assert safe_json_loads({"already": 1}, fallback=[]) == []  # type: ignore[arg-type]

    def test_bytes_payload_parses_natively(self) -> None:
        assert safe_json_loads(b'{"b": 2}') == {"b": 2}

    def test_truncated_string_returns_explicit_fallback(self) -> None:
        assert safe_json_loads('{"a": 1', fallback=[42]) == [42]

    def test_parse_error_logs_warning(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="deeptutor.utils.json_parser"):
            safe_json_loads("not json", fallback=None)

        warnings = [
            r
            for r in caplog.records
            if r.name == "deeptutor.utils.json_parser" and r.levelno == logging.WARNING
        ]
        assert warnings
        assert "json parse error" in warnings[-1].getMessage().lower()
