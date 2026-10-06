"""Tests for LLM error mapping helpers."""

from datetime import datetime, timezone
import logging

import pytest

from deeptutor.services.llm.error_mapping import (
    map_error,
    parse_retry_after_seconds,
    retry_after_seconds,
)
from deeptutor.services.llm.exceptions import (
    LLMAPIError,
    LLMAuthenticationError,
    LLMProviderTransportError,
    LLMRateLimitError,
    LLMTimeoutError,
    ProviderContextWindowError,
)


class DummyError(Exception):
    """Custom error used for mapping tests."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def test_map_error_status_code_auth() -> None:
    """401 errors should map to authentication failures."""
    mapped = map_error(DummyError("auth failed", status_code=401), provider="openai")
    assert isinstance(mapped, LLMAuthenticationError)


def test_map_error_status_code_rate_limit() -> None:
    """429 errors should map to rate limit failures."""
    mapped = map_error(DummyError("rate limited", status_code=429), provider="openai")
    assert isinstance(mapped, LLMRateLimitError)


def test_map_error_preserves_retry_after_header() -> None:
    error = DummyError("rate limited", status_code=429)
    error.response = type(
        "Response",
        (),
        {"headers": {"Retry-After": "12.5"}},
    )()

    mapped = map_error(error, provider="openai")

    assert isinstance(mapped, LLMRateLimitError)
    assert mapped.retry_after == 12.5


def test_retry_after_seconds_parses_http_date() -> None:
    error = DummyError("temporarily unavailable", status_code=503)
    error.response = type(
        "Response",
        (),
        {"headers": {"Retry-After": "Wed, 21 Oct 2015 07:28:10 GMT"}},
    )()

    delay = retry_after_seconds(
        error,
        now=datetime(2015, 10, 21, 7, 28, tzinfo=timezone.utc),
    )

    assert delay == 10.0


@pytest.mark.parametrize("value", ["", "tomorrow", "-1", "nan", True, None])
def test_parse_retry_after_seconds_rejects_invalid_values(value: object) -> None:
    assert parse_retry_after_seconds(value) is None


def test_map_error_message_context_window() -> None:
    """Context length errors should map to the provider context window error."""
    mapped = map_error(DummyError("maximum context length exceeded"), provider="openai")
    assert isinstance(mapped, ProviderContextWindowError)


def test_map_error_falls_back_to_api_error() -> None:
    """Unknown errors should fall back to generic API error mapping."""
    mapped = map_error(DummyError("boom", status_code=500), provider="openai")
    assert isinstance(mapped, LLMAPIError)
    assert mapped.status_code == 500


def test_map_error_preserves_structured_transport_error() -> None:
    error = LLMProviderTransportError("provider connection failed")

    mapped = map_error(error, provider="openai_codex")

    assert mapped is error
    assert mapped.provider == "openai_codex"


_PROVIDER_ERROR_TEXT = (
    "Error code: 429 - rate limit reached for requests, please try again in "
    "12s. Contact us at https://help.example.com/ if the issue persists. "
    "(Request ID: req_9f8e7d6c5b4a.)"
)


def test_map_error_rate_limit_message_is_neutral() -> None:
    """Rate-limit mapping keeps retry semantics but drops provider error text."""
    error = DummyError(_PROVIDER_ERROR_TEXT, status_code=429)
    error.response = type(
        "Response",
        (),
        {"headers": {"Retry-After": "12.5"}},
    )()

    mapped = map_error(error, provider="openai")

    assert isinstance(mapped, LLMRateLimitError)
    assert "https://" not in str(mapped)
    assert "req_9f8e7d6c5b4a" not in str(mapped)
    assert "rate limit reached" not in str(mapped)
    assert mapped.retry_after == 12.5
    assert mapped.status_code == 429


def test_map_error_authentication_message_is_neutral() -> None:
    error = DummyError(
        "401 Incorrect API key provided (Key: sk-****). "
        "See https://help.example.com/ (Request ID: req_9f8e7d6c5b4a).",
        status_code=401,
    )

    mapped = map_error(error, provider="openai")

    assert isinstance(mapped, LLMAuthenticationError)
    assert "https://" not in str(mapped)
    assert "req_9f8e7d6c5b4a" not in str(mapped)
    assert "sk-" not in str(mapped)


def test_map_error_timeout_message_is_neutral() -> None:
    error = TimeoutError(
        "Read from https://api.example.com/v1 timed out (Request ID: req_9f8e7d6c5b4a)."
    )

    mapped = map_error(error, provider="openai")

    assert isinstance(mapped, LLMTimeoutError)
    assert "https://" not in str(mapped)
    assert "req_9f8e7d6c5b4a" not in str(mapped)


def test_map_error_context_window_message_is_neutral() -> None:
    error = DummyError(
        "This model's maximum context length is 128000 tokens. "
        "See https://help.example.com/ (Request ID: req_9f8e7d6c5b4a)."
    )

    mapped = map_error(error, provider="openai")

    assert isinstance(mapped, ProviderContextWindowError)
    assert "https://" not in str(mapped)
    assert "req_9f8e7d6c5b4a" not in str(mapped)


def test_map_error_fallback_message_is_neutral() -> None:
    error = DummyError(
        "The server had an error while processing your request. "
        "See https://help.example.com/ (Request ID: req_9f8e7d6c5b4a).",
        status_code=500,
    )

    mapped = map_error(error, provider="openai")

    assert isinstance(mapped, LLMAPIError)
    assert "https://" not in str(mapped)
    assert "req_9f8e7d6c5b4a" not in str(mapped)
    assert mapped.status_code == 500


def test_map_error_logs_original_exception_server_side(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The raw provider text is preserved in server logs, not user messages."""
    with caplog.at_level(
        logging.WARNING,
        logger="deeptutor.services.llm.error_mapping",
    ):
        mapped = map_error(DummyError(_PROVIDER_ERROR_TEXT, status_code=429), provider="openai")

    assert "req_9f8e7d6c5b4a" not in str(mapped)
    assert any("req_9f8e7d6c5b4a" in record.getMessage() for record in caplog.records)
