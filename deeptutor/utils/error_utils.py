#!/usr/bin/env python
"""
Error Utilities - Error formatting and handling utilities
"""

import json
import re
from typing import Optional

# Labelled credential assignments, e.g. ``token=...`` or ``"api_key": ...``.
_CREDENTIAL_PAIR_RE = re.compile(
    r"(?i)\b(bearer|token|api[-_]?key|apikey|secret|password|passwd|credential)s?\b"
    r"(\s*[=:]\s*)"
    r"(\S+)"
)
# Long opaque runs that look like encoded key material rather than prose.
_OPAQUE_RUN_RE = re.compile(r"\b[A-Za-z0-9+/_\-]{24,}\b")
_WHITESPACE_RE = re.compile(r"\s+")


def exc_type_name(exc: BaseException) -> str:
    """
    Return only the exception class name.

    Exception messages can carry provider response bodies, request echoes, or
    endpoint details, so logging surfaces use the type name as the safe
    default; structured fields carry the operational context instead.
    """
    return type(exc).__name__


def redacted_error_summary(exc: BaseException, limit: int = 120) -> str:
    """
    Return a short, redacted summary of ``str(exc)`` for limited-detail logs.

    Credential-shaped pairs and long opaque runs are masked and the result is
    whitespace-collapsed and truncated to ``limit`` characters. Prefer
    :func:`exc_type_name` wherever the type name alone is enough context.
    """
    text = _WHITESPACE_RE.sub(" ", str(exc)).strip()
    if not text:
        return exc_type_name(exc)
    text = _CREDENTIAL_PAIR_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}***", text)
    text = _OPAQUE_RUN_RE.sub("***", text)
    if len(text) > limit:
        text = text[: limit - 3].rstrip() + "..."
    return text


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


def format_exception_message(exc: Exception) -> str:
    """
    Format exception message for better readability

    Args:
        exc: The exception to format

    Returns:
        Formatted error message
    """
    message = str(exc)

    # Try to parse JSON error messages (common in API errors)
    potential_json = _find_json_block(message)
    if potential_json:
        try:
            error_data = json.loads(potential_json)

            # Standard extraction logic
            if isinstance(error_data, dict) and "error" in error_data:
                error_info = error_data["error"]
                if isinstance(error_info, dict):
                    parts = []
                    if "message" in error_info:
                        parts.append(f"Message: {error_info['message']}")
                    if "type" in error_info:
                        parts.append(f"Type: {error_info['type']}")
                    if "code" in error_info:
                        parts.append(f"Code: {error_info['code']}")
                    if parts:
                        return " | ".join(parts)
        except (json.JSONDecodeError, AttributeError):
            pass

    # Return original message if parsing fails
    return message
