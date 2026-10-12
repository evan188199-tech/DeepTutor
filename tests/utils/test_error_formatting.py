"""Focused tests for ``deeptutor.utils.error_utils`` error formatting."""

from __future__ import annotations

import pytest

from deeptutor.utils.error_utils import _find_json_block, format_exception_message


class TestFindJsonBlock:
    def test_no_brace_returns_none(self) -> None:
        assert _find_json_block("plain error text without braces") is None

    def test_unclosed_block_returns_none(self) -> None:
        assert _find_json_block('prefix {"error": {"message": "x"}') is None

    def test_returns_first_balanced_block_with_nesting(self) -> None:
        message = 'before {"error": {"code": 7}, "ok": true} trailing'
        assert _find_json_block(message) == '{"error": {"code": 7}, "ok": true}'

    def test_braces_inside_strings_do_not_confuse_depth(self) -> None:
        message = '{"message": "value with } and { inside", "n": 1}'
        assert _find_json_block(message) == message

    def test_escaped_quotes_inside_strings(self) -> None:
        message = r'{"message": "quote \" then brace } stays", "n": 2}'
        assert _find_json_block(message) == message

    def test_empty_braces_return_block(self) -> None:
        assert _find_json_block("noise {} noise") == "{}"


class TestFormatExceptionMessagePassthrough:
    def test_plain_message_unchanged(self) -> None:
        assert format_exception_message(ValueError("boom")) == "boom"

    def test_message_without_parseable_json_unchanged(self) -> None:
        exc = RuntimeError('prefix {"error": broken}')
        assert format_exception_message(exc) == 'prefix {"error": broken}'

    def test_json_without_error_key_unchanged(self) -> None:
        exc = ValueError('{"detail": "no error key"}')
        assert format_exception_message(exc) == '{"detail": "no error key"}'

    def test_error_value_not_a_dict_unchanged(self) -> None:
        exc = ValueError('{"error": "plain string error"}')
        assert format_exception_message(exc) == '{"error": "plain string error"}'

    def test_json_array_block_unchanged(self) -> None:
        exc = ValueError('prefix [1, 2, 3] suffix')
        assert format_exception_message(exc) == 'prefix [1, 2, 3] suffix'


class TestFormatExceptionMessageExtraction:
    def test_full_error_dict_parts_joined(self) -> None:
        exc = RuntimeError(
            'request failed: {"error": {"message": "rate limited",'
            ' "type": "quota", "code": 429}}'
        )
        formatted = format_exception_message(exc)
        assert formatted == "Message: rate limited | Type: quota | Code: 429"

    def test_partial_error_dict_parts_only(self) -> None:
        exc = RuntimeError('{"error": {"message": "only message", "other": 1}}')
        assert format_exception_message(exc) == "Message: only message"

    def test_message_with_braces_in_value_survives_parsing(self) -> None:
        exc = ValueError('{"error": {"message": "bad {shape} given", "code": "E1"}}')
        assert format_exception_message(exc) == "Message: bad {shape} given | Code: E1"

    def test_empty_error_dict_falls_back_to_original(self) -> None:
        raw = '{"error": {}}'
        exc = ValueError(raw)
        assert format_exception_message(exc) == raw


class TestExceptionSubclasses:
    @pytest.mark.parametrize("exc_cls", [ValueError, KeyError, RuntimeError])
    def test_works_for_any_exception_type(self, exc_cls: type[Exception]) -> None:
        exc = exc_cls('{"error": {"code": "x1"}}')
        assert format_exception_message(exc) == "Code: x1"
