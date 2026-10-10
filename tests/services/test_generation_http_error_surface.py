"""Regression tests for the generation_http provider error surface.

``raise_for_provider`` produces the message that adapters propagate to callers
which may expose it to the model or end users. These tests lock the contract
that the raised error carries only the action and the HTTP status code, while
the provider-controlled response body stays in server-side logs.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from deeptutor.services.generation_http import (
    GenerationProviderError,
    raise_for_provider,
)


def _resp(status: int, text: str = "") -> httpx.Response:
    return httpx.Response(status_code=status, text=text)


@pytest.mark.parametrize("status", [200, 201, 204, 302, 399])
def test_raise_for_provider_allows_success_statuses(status: int) -> None:
    raise_for_provider(_resp(status, "ok"), "Image generation")


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 502, 503])
def test_error_message_contains_only_action_and_status(status: int) -> None:
    body = '{"error": {"message": "provider detail", "code": 12345}}'
    with pytest.raises(GenerationProviderError) as excinfo:
        raise_for_provider(_resp(status, body), "Image generation")
    assert str(excinfo.value) == f"Image generation failed with HTTP {status}."


def test_error_message_excludes_response_body_content() -> None:
    body = "internal-provider-detail-token"
    with pytest.raises(GenerationProviderError) as excinfo:
        raise_for_provider(_resp(502, body), "Video download")
    assert "internal-provider-detail-token" not in str(excinfo.value)
    assert str(excinfo.value) == "Video download failed with HTTP 502."


def test_response_body_is_logged_server_side(caplog: pytest.LogCaptureFixture) -> None:
    body = "internal-provider-detail-token"
    with caplog.at_level(logging.WARNING, logger="deeptutor.services.generation_http"):
        with pytest.raises(GenerationProviderError):
            raise_for_provider(_resp(500, body), "Video task status")
    record_bodies = [r.getMessage() for r in caplog.records]
    assert any("internal-provider-detail-token" in msg for msg in record_bodies)
    assert any("HTTP 500" in msg for msg in record_bodies)


def test_empty_body_raises_stable_message_without_body_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="deeptutor.services.generation_http"):
        with pytest.raises(GenerationProviderError) as excinfo:
            raise_for_provider(_resp(429), "Image generation")
    assert str(excinfo.value) == "Image generation failed with HTTP 429."
    assert not caplog.records


def test_whitespace_only_body_treated_as_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="deeptutor.services.generation_http"):
        with pytest.raises(GenerationProviderError) as excinfo:
            raise_for_provider(_resp(503, "   \n\t "), "Image download")
    assert str(excinfo.value) == "Image download failed with HTTP 503."
    assert not caplog.records


def test_logged_body_is_trimmed_to_400_chars(
    caplog: pytest.LogCaptureFixture,
) -> None:
    body = "x" * 1000
    with caplog.at_level(logging.WARNING, logger="deeptutor.services.generation_http"):
        with pytest.raises(GenerationProviderError):
            raise_for_provider(_resp(500, body), "Image generation")
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "x" * 401 not in joined
