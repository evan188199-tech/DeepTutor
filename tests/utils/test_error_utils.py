"""format_exception_message must only surface whitelisted, length-capped envelope fields."""

from __future__ import annotations

import json

import pytest

from deeptutor.utils.error_utils import (
    _FALLBACK_MESSAGE,
    _MAX_ENVELOPE_CODE_LENGTH,
    _MAX_ENVELOPE_MESSAGE_LENGTH,
    format_exception_message,
)


def test_standard_envelope_is_reorganized():
    payload = {
        "error": {"message": "Rate limit reached", "type": "rate_limit_error", "code": "429"}
    }
    result = format_exception_message(Exception(json.dumps(payload)))
    assert result == "Message: Rate limit reached | Type: rate_limit_error | Code: 429"


def test_envelope_embedded_in_provider_text_is_reorganized():
    payload = json.dumps({"error": {"message": "Quota exceeded", "code": "insufficient_quota"}})
    result = format_exception_message(Exception(f"Provider said: {payload} please retry"))
    assert result == "Message: Quota exceeded | Code: insufficient_quota"


def test_envelope_with_non_string_code():
    payload = {"error": {"message": "Bad request", "code": 400}}
    result = format_exception_message(Exception(json.dumps(payload)))
    assert result == "Message: Bad request | Code: 400"


def test_envelope_message_is_capped():
    payload = {"error": {"message": "a" * (_MAX_ENVELOPE_MESSAGE_LENGTH + 50)}}
    result = format_exception_message(Exception(json.dumps(payload)))
    assert result == f"Message: {'a' * _MAX_ENVELOPE_MESSAGE_LENGTH}..."


def test_envelope_type_and_code_are_capped():
    payload = {"error": {"type": "t" * (_MAX_ENVELOPE_CODE_LENGTH + 10), "code": 12345}}
    result = format_exception_message(Exception(json.dumps(payload)))
    assert result == (f"Type: {'t' * _MAX_ENVELOPE_CODE_LENGTH}... | Code: 12345")


def test_envelope_values_are_collapsed_to_single_line():
    payload = {"error": {"message": "line one\nline two\ttabbed", "type": "x"}}
    result = format_exception_message(Exception(json.dumps(payload)))
    assert result == "Message: line one line two tabbed | Type: x"


@pytest.mark.parametrize(
    "raw",
    [
        "Connection reset by peer while reading upstream data",
        "[Errno 2] No such file or directory: /srv/shared/notes.txt",
        "Request to https://internal-gw.example.net/v1 failed with status 502",
        "",
        "Error code: 400 - {'error': {'message': 'missing api_key parameter'}}",
        json.dumps({"error": "plain string error"}),
        json.dumps({"detail": "unhandled exception in worker"}),
        json.dumps({"error": {"param": "model", "status": 400}}),
    ],
)
def test_non_envelope_text_is_replaced_with_neutral_copy(raw):
    result = format_exception_message(Exception(raw))
    assert result == _FALLBACK_MESSAGE
    if raw:
        assert raw not in result


def test_fallback_copy_mentions_no_internal_details():
    assert "This request could not be completed" in _FALLBACK_MESSAGE
