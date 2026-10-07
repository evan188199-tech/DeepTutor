"""Tests for error formatting utilities in deeptutor.utils.error_utils."""

from __future__ import annotations

from deeptutor.utils.error_utils import (
    _find_json_block,
    format_exception_message,
)


class TestFindJsonBlock:
    def test_returns_none_without_braces(self):
        assert _find_json_block("plain error message") is None

    def test_returns_none_for_empty_message(self):
        assert _find_json_block("") is None

    def test_extracts_bare_json_object(self):
        assert _find_json_block('{"a": 1}') == '{"a": 1}'

    def test_extracts_json_from_surrounding_text(self):
        message = 'API call failed with {"error": "rate limited"} after 3 retries'
        assert _find_json_block(message) == '{"error": "rate limited"}'

    def test_handles_nested_braces(self):
        message = 'outer {"error": {"message": "x"}} trailing'
        assert _find_json_block(message) == '{"error": {"message": "x"}}'

    def test_braces_inside_strings_do_not_close_block(self):
        message = '{"a": "literal } brace"} trailing'
        assert _find_json_block(message) == '{"a": "literal } brace"}'

    def test_open_braces_inside_strings_do_not_break_counting(self):
        message = '{"a": "keep { going"} tail'
        assert _find_json_block(message) == '{"a": "keep { going"}'

    def test_escaped_quotes_inside_strings(self):
        message = 'failed: {"a": "say \\"hi\\" ok"} end'
        assert _find_json_block(message) == '{"a": "say \\"hi\\" ok"}'

    def test_unterminated_json_returns_none(self):
        assert _find_json_block('{"error": {"message": "cut off"') is None

    def test_open_brace_only_returns_none(self):
        assert _find_json_block("{ unclosed") is None


class TestFormatExceptionMessage:
    def test_plain_message_passthrough(self):
        assert format_exception_message(ValueError("boom")) == "boom"

    def test_message_without_json_passthrough(self):
        assert format_exception_message(RuntimeError("connection reset")) == "connection reset"

    def test_full_error_dict_parts_joined_in_order(self):
        message = (
            '{"error": {"message": "quota exceeded", "type": "insufficient_quota", "code": "429"}}'
        )
        formatted = format_exception_message(ValueError(message))
        assert formatted == "Message: quota exceeded | Type: insufficient_quota | Code: 429"

    def test_message_only_error_dict(self):
        message = '{"error": {"message": "only message"}}'
        assert format_exception_message(ValueError(message)) == "Message: only message"

    def test_string_error_value_returns_original(self):
        message = '{"error": "rate limited"}'
        assert format_exception_message(ValueError(message)) == message

    def test_dict_without_error_key_returns_original(self):
        message = '{"status": "ok"}'
        assert format_exception_message(ValueError(message)) == message

    def test_empty_error_dict_returns_original(self):
        message = '{"error": {}}'
        assert format_exception_message(ValueError(message)) == message

    def test_malformed_json_returns_original(self):
        message = "broken {not json here} tail"
        assert format_exception_message(ValueError(message)) == message

    def test_unterminated_json_returns_original(self):
        message = '{"error": {"message": "cut'
        assert format_exception_message(ValueError(message)) == message

    def test_empty_braces_returns_original(self):
        message = "{}"
        assert format_exception_message(ValueError(message)) == message

    def test_json_embedded_in_prose_is_formatted(self):
        message = 'upstream said {"error": {"message": "bad key"}} while streaming'
        assert format_exception_message(ValueError(message)) == "Message: bad key"
