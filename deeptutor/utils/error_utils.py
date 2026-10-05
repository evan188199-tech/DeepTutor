#!/usr/bin/env python
"""
Error Utilities - Error formatting and handling utilities
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Length caps for user-facing text taken from a well-formed provider error envelope.
_MAX_ENVELOPE_MESSAGE_LENGTH = 300
_MAX_ENVELOPE_CODE_LENGTH = 100

# Neutral copy returned when an exception message has no whitelisted representation.
_FALLBACK_MESSAGE = (
    "This request could not be completed because of an unexpected error. Please try again later."
)


def _find_json_block(message: str) -> Optional[str]:
    """Extract potential JSON block from message by matching braces."""
    start_idx = message.find("{")
    if start_idx == -1:
        return None

    brace_count = 0
    in_string = False
    escape_next = False

    for char_idx in range(start_idx, len(message)):
        char = message[char_idx]

        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if not in_string:
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    return message[start_idx : char_idx + 1]

    return None


def _clean_envelope_value(value: object, limit: int) -> str:
    """Collapse whitespace and cap the length of a whitelisted envelope value."""
    text = " ".join(str(value).split())
    if len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def _format_error_envelope(message: str) -> Optional[str]:
    """Build a whitelisted, truncated summary from a standard provider error envelope.

    Args:
        message: The raw exception text, which may embed a JSON error envelope.

    Returns:
        The formatted summary, or None when the text is not a standard envelope.
    """
    potential_json = _find_json_block(message)
    if not potential_json:
        return None
    try:
        error_data = json.loads(potential_json)
    except (json.JSONDecodeError, AttributeError):
        return None

    if not (isinstance(error_data, dict) and isinstance(error_data.get("error"), dict)):
        return None

    error_info = error_data["error"]
    parts = []
    if "message" in error_info:
        parts.append(
            f"Message: {_clean_envelope_value(error_info['message'], _MAX_ENVELOPE_MESSAGE_LENGTH)}"
        )
    if "type" in error_info:
        parts.append(
            f"Type: {_clean_envelope_value(error_info['type'], _MAX_ENVELOPE_CODE_LENGTH)}"
        )
    if "code" in error_info:
        parts.append(
            f"Code: {_clean_envelope_value(error_info['code'], _MAX_ENVELOPE_CODE_LENGTH)}"
        )
    return " | ".join(parts) if parts else None


def format_exception_message(exc: Exception) -> str:
    """
    Format exception message for better readability

    Only standard provider error envelopes are reorganized into a whitelisted,
    length-capped summary. Any other text is replaced with neutral copy; the
    original text is kept in the server log only.

    Args:
        exc: The exception to format

    Returns:
        Formatted error message
    """
    message = str(exc)

    formatted = _format_error_envelope(message)
    if formatted is not None:
        return formatted

    logger.warning(
        "format_exception_message replaced non-envelope exception text with fallback (%s): %s",
        type(exc).__name__,
        message,
    )
    return _FALLBACK_MESSAGE
