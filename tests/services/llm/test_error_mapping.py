"""Tests for LLM error mapping helpers."""

import asyncio
from datetime import datetime, timezone

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


class AuthenticationError(Exception):
    """Stands in for an SDK auth exception matched only by class name."""


class AuthenticationStatusError(AuthenticationError):
    """Stands in for the alternative SDK auth exception name."""


class RateLimitError(Exception):
    """Stands in for an SDK rate-limit exception matched only by class name."""


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


def test_map_error_passthrough_does_not_overwrite_known_provider() -> None:
    error = LLMProviderTransportError("provider connection failed")
    error.provider = "anthropic"

    mapped = map_error(error, provider="openai")

    assert mapped is error
    assert mapped.provider == "anthropic"


def test_map_error_asyncio_timeout_maps_to_timeout_error() -> None:
    mapped = map_error(asyncio.TimeoutError("timed out"), provider="openai")

    assert isinstance(mapped, LLMTimeoutError)
    assert mapped.provider == "openai"
    assert mapped.status_code == 408


def test_map_error_builtin_timeout_maps_to_timeout_error() -> None:
    mapped = map_error(TimeoutError("socket read timed out"), provider="groq")

    assert isinstance(mapped, LLMTimeoutError)
    assert mapped.provider == "groq"


def test_map_error_timeout_empty_message_gets_default_text() -> None:
    mapped = map_error(TimeoutError(), provider="openai")

    assert isinstance(mapped, LLMTimeoutError)
    assert mapped.message == "Request timed out"


def test_map_error_sdk_authentication_error_by_class_name() -> None:
    mapped = map_error(AuthenticationError("invalid api key"), provider="openai")

    assert isinstance(mapped, LLMAuthenticationError)
    assert mapped.provider == "openai"
    assert mapped.status_code == 401


def test_map_error_sdk_authentication_status_error_by_class_name() -> None:
    mapped = map_error(AuthenticationStatusError("bad session"), provider="anthropic")

    assert isinstance(mapped, LLMAuthenticationError)


def test_map_error_class_name_match_uses_mro() -> None:
    class SessionExpiredError(AuthenticationError):
        pass

    mapped = map_error(SessionExpiredError("session expired"), provider="anthropic")

    assert isinstance(mapped, LLMAuthenticationError)


def test_map_error_sdk_rate_limit_error_by_class_name() -> None:
    error = RateLimitError("too many requests")
    error.retry_after = 7

    mapped = map_error(error, provider="openai")

    assert isinstance(mapped, LLMRateLimitError)
    assert mapped.retry_after == 7.0


@pytest.mark.parametrize(
    "message",
    [
        "Rate limit reached for requests",
        "Request failed with HTTP 429",
        "quota exceeded for this project",
    ],
)
def test_map_error_message_rate_limit_variants(message: str) -> None:
    mapped = map_error(DummyError(message), provider="openai")

    assert isinstance(mapped, LLMRateLimitError)
    assert mapped.provider == "openai"


def test_map_error_message_rate_limit_without_hint_has_none_retry_after() -> None:
    mapped = map_error(DummyError("rate limit hit"), provider="openai")

    assert isinstance(mapped, LLMRateLimitError)
    assert mapped.retry_after is None


def test_map_error_message_context_length_only() -> None:
    mapped = map_error(DummyError("this model supports 8192 context length tokens"))

    assert isinstance(mapped, ProviderContextWindowError)


def test_map_error_status_401_wins_over_rate_limit_message() -> None:
    mapped = map_error(DummyError("rate limit", status_code=401), provider="openai")

    assert isinstance(mapped, LLMAuthenticationError)


def test_map_error_fallback_without_status_keeps_provider() -> None:
    mapped = map_error(DummyError("mystery failure"), provider="together")

    assert type(mapped) is LLMAPIError
    assert mapped.status_code is None
    assert mapped.provider == "together"


def test_map_error_status_429_keeps_retry_after_attribute() -> None:
    error = DummyError("slow down", status_code=429)
    error.retry_after = 2.5

    mapped = map_error(error, provider="openai")

    assert isinstance(mapped, LLMRateLimitError)
    assert mapped.retry_after == 2.5


def test_retry_after_prefers_attribute_over_header() -> None:
    error = DummyError("rate limited", status_code=429)
    error.retry_after = 3
    error.response = type(
        "Response",
        (),
        {"headers": {"Retry-After": "99"}},
    )()

    assert retry_after_seconds(error) == 3.0


def test_retry_after_seconds_accepts_lowercase_header() -> None:
    error = DummyError("rate limited", status_code=429)
    error.response = type(
        "Response",
        (),
        {"headers": {"retry-after": "5"}},
    )()

    assert retry_after_seconds(error) == 5.0


def test_retry_after_seconds_without_any_hint_returns_none() -> None:
    assert retry_after_seconds(DummyError("nothing here")) is None


@pytest.mark.parametrize("value", [-1, float("inf"), float("-inf"), True])
def test_parse_retry_after_seconds_rejects_out_of_range_numeric(value: object) -> None:
    assert parse_retry_after_seconds(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [(3, 3.0), (2.5, 2.5), ("8", 8.0), (" 4.5 ", 4.5)],
)
def test_parse_retry_after_seconds_accepts_numeric_values(value: object, expected: float) -> None:
    assert parse_retry_after_seconds(value) == expected


def test_parse_retry_after_seconds_http_date_in_past_clamps_to_zero() -> None:
    delay = parse_retry_after_seconds(
        "Wed, 21 Oct 2015 07:28:10 GMT",
        now=datetime(2016, 1, 1, tzinfo=timezone.utc),
    )

    assert delay == 0.0


def test_parse_retry_after_seconds_naive_http_date_treated_as_utc() -> None:
    delay = parse_retry_after_seconds(
        "Wed, 21 Oct 2015 07:28:10",
        now=datetime(2015, 10, 21, 7, 28, tzinfo=timezone.utc),
    )

    assert delay == 10.0


def test_parse_retry_after_seconds_rejects_unsupported_types() -> None:
    assert parse_retry_after_seconds({"seconds": 5}) is None
    assert parse_retry_after_seconds([5]) is None
