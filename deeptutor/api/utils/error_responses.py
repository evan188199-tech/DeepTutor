"""The raise-side helper for the structured error envelope.

A router that refuses a request with ``HTTPException(detail="free text")``
leaves the frontend matching whole strings. The shared envelope — already
spoken by ``book.py`` and ``space_mcp.py`` — wraps that same text in
``{"code", "message"}`` so clients get a stable machine-readable key while
the message stays byte-identical.

``structured_error`` builds both shapes:

* **without a code** the detail stays the historical plain string, so a call
  site that has not been classified yet puts exactly its old body on the
  wire (``extra`` fields, when present, still ride along in a dict — the
  shape unclassified validation refusals already used);
* **with a code** the detail becomes the envelope, message verbatim, plus
  any extra fields the refusal already carried (validation ``errors``, the
  ``active_session_key`` of a busy partner turn).

``error_message`` reads either shape back out, for the in-process consumers
that surface a refusal's text (WebSocket frames, logs) instead of letting a
dict render as its repr.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def structured_error(
    status_code: int,
    message: str,
    *,
    code: str | None = None,
    **extra: Any,
) -> HTTPException:
    """Build an ``HTTPException`` whose detail is machine-readable when asked to be.

    The optional ``code`` is the whole contract: omitted, the detail is the
    plain ``message`` string (an unclassified site changes nothing on the
    wire); given, the detail is ``{"code", "message"}`` and every ``extra``
    keyword joins it, so refusals that always carried structured context
    (validation ``errors``, a busy turn's ``active_session_key``) keep it.
    """
    if code is None and not extra:
        return HTTPException(status_code=status_code, detail=message)
    detail: dict[str, Any] = {}
    if code is not None:
        detail["code"] = code
    detail["message"] = message
    detail.update(extra)
    return HTTPException(status_code=status_code, detail=detail)


def error_message(detail: Any) -> str:
    """The human-readable text of an ``HTTPException`` detail, either shape."""
    if isinstance(detail, dict):
        return str(detail.get("message", ""))
    return str(detail)


__all__ = ["error_message", "structured_error"]
