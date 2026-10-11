"""The shared error envelope helper: one call site, both wire shapes.

``structured_error`` is the raise-side half of the structured error envelope
(``{"code", "message"}``): without a ``code`` the detail stays the historical
plain string so an unclassified site changes nothing on the wire; with one it
becomes the envelope, message verbatim, extras preserved. ``error_message``
reads either shape back out — the guarantee the in-process consumers
(WebSocket frames) rely on instead of stringifying a dict to its repr.
"""

from __future__ import annotations

from fastapi import HTTPException
import pytest

from deeptutor.api.utils.error_responses import error_message, structured_error


@pytest.mark.parametrize(
    ("status_code", "message", "code", "extra", "expected_detail"),
    [
        # Without a code the detail is the historical plain string.
        (404, "Partner not found", None, {}, "Partner not found"),
        (400, "content is required", None, {}, "content is required"),
        # With a code the detail is the shared envelope, message verbatim.
        (
            404,
            "Partner not found",
            "partner.not_found",
            {},
            {"code": "partner.not_found", "message": "Partner not found"},
        ),
        (
            413,
            "Attachment batch too large",
            "partner.attachment_batch_too_large",
            {},
            {"code": "partner.attachment_batch_too_large", "message": "Attachment batch too large"},
        ),
        # Extras ride along inside the envelope, after code and message.
        (
            422,
            "Invalid channels config",
            "partner.channels_invalid",
            {"errors": [{"loc": ["telegram"]}]},
            {
                "code": "partner.channels_invalid",
                "message": "Invalid channels config",
                "errors": [{"loc": ["telegram"]}],
            },
        ),
        (
            409,
            "The active conversation changed in another browser.",
            "partner.stale_session",
            {"active_session_key": "web-current"},
            {
                "code": "partner.stale_session",
                "message": "The active conversation changed in another browser.",
                "active_session_key": "web-current",
            },
        ),
        # The pre-envelope validation shape (extras, no code) keeps working
        # for sites that have not been classified yet.
        (
            422,
            "Invalid channels config",
            None,
            {"errors": [{"loc": ["telegram"]}]},
            {"message": "Invalid channels config", "errors": [{"loc": ["telegram"]}]},
        ),
    ],
)
def test_structured_error_builds_the_expected_detail(
    status_code, message, code, extra, expected_detail
):
    exc = structured_error(status_code, message, code=code, **extra)

    assert isinstance(exc, HTTPException)
    assert exc.status_code == status_code
    assert exc.detail == expected_detail


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ("Partner not found", "Partner not found"),
        ("", ""),
        ({"code": "partner.not_found", "message": "Partner not found"}, "Partner not found"),
        ({"message": "Invalid channels config", "errors": []}, "Invalid channels config"),
        ({"code": "partner.soul_not_found", "message": "Soul not found"}, "Soul not found"),
    ],
)
def test_error_message_reads_either_shape(detail, expected):
    assert error_message(detail) == expected
