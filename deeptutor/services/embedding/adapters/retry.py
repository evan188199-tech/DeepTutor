"""Bounded retry policy shared by the embedding adapters.

Two in-repo patterns anchor this module:

* ``openai_compatible.py`` retries ``httpx.TransportError`` with exponential
  backoff;
* ``services/rag/pipelines/lightrag/config.py`` keeps a bounded attempt
  budget, a small retryable-status set, honors ``Retry-After`` but caps the
  wait, and classifies failures without inspecting provider payloads.

Adapters that issue raw httpx calls (cohere, jina, ollama) pass one-attempt
closures to :func:`run_with_bounded_retry`; the DashScope adapter wraps its
SDK-in-thread calls the same way with duck-typed status/header extractors so
this module never imports the SDK.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
from typing import TypeVar

from deeptutor.services.llm.error_mapping import parse_retry_after_seconds
from deeptutor.services.llm.request_compat import is_transient_transport_error

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

# Bounded budget: one attempt plus at most 3 retries.
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.0
MAX_RETRY_DELAY_SECONDS = 60.0
RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504, 529})

# ``requests``-based SDKs (DashScope) raise transport failures whose types are
# not builtin ``ConnectionError``; classify them by module + name along the
# exception chain instead of importing the SDK here.
_TRANSIENT_REQUESTS_ERRORS = frozenset(
    {"ConnectionError", "ConnectTimeout", "ReadTimeout", "Timeout", "RetryError"}
)


def is_retryable_status(status_code: int | None) -> bool:
    """Whether an HTTP status is a transient server/rate signal worth retrying."""
    return status_code in RETRYABLE_STATUS_CODES


def retry_delay_seconds(attempt: int, retry_after: object) -> float:
    """Exponential backoff for 0-based *attempt*; a safe ``Retry-After`` wins.

    A server-provided ``Retry-After`` is honored but capped so a hostile or
    misconfigured header cannot stall the embedding pipeline.
    """
    requested = parse_retry_after_seconds(retry_after)
    if requested is not None:
        return min(requested, MAX_RETRY_DELAY_SECONDS)
    return RETRY_BACKOFF_SECONDS * (2**attempt)


def is_transient_exception(exc: BaseException) -> bool:
    """Transport-only classification; provider payloads are never inspected."""
    if is_transient_transport_error(exc):
        return True
    current: BaseException | None = exc
    while current is not None:
        error_type = type(current)
        if (
            error_type.__module__.split(".")[0] == "requests"
            and error_type.__name__ in _TRANSIENT_REQUESTS_ERRORS
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def retry_after_from_headers(headers: object) -> object:
    """Read ``Retry-After`` from any headers mapping without assuming httpx."""
    get_header = getattr(headers, "get", None)
    if callable(get_header):
        value = get_header("Retry-After")
        if value is None:
            value = get_header("retry-after")
        return value
    return None


def log_retry(provider: str, reason: str, attempt: int, delay: float) -> None:
    """Warn about a retry with provider name and status/type only — never bodies."""
    logger.warning(
        "%s embedding request failed (%s) on attempt %d/%d, retrying in %.1fs",
        provider,
        reason,
        attempt + 1,
        1 + MAX_RETRIES,
        delay,
    )


async def run_with_bounded_retry(
    call: Callable[[], Awaitable[_T]],
    *,
    provider: str,
    status_of: Callable[[_T], int | None],
    retry_after_of: Callable[[_T], object] | None = None,
) -> _T:
    """Run one adapter call, retrying transient statuses/transport errors.

    ``status_of`` / ``retry_after_of`` let SDK response objects (DashScope)
    participate in the same policy. After the bounded budget is spent the last
    response/exception is handed back so each adapter keeps its own error
    surface (``raise_for_status`` or structured translation).
    """
    for attempt in range(1 + MAX_RETRIES):
        try:
            result = await call()
        except Exception as exc:
            if attempt < MAX_RETRIES and is_transient_exception(exc):
                delay = retry_delay_seconds(attempt, None)
                log_retry(provider, type(exc).__name__, attempt, delay)
                await asyncio.sleep(delay)
                continue
            raise
        status = status_of(result)
        if attempt < MAX_RETRIES and is_retryable_status(status):
            retry_after = retry_after_of(result) if retry_after_of is not None else None
            delay = retry_delay_seconds(attempt, retry_after)
            log_retry(provider, f"http_{status}", attempt, delay)
            await asyncio.sleep(delay)
            continue
        return result
    raise AssertionError("unreachable")
