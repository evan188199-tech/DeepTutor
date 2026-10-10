"""Canonical HTTP error factories shared by the API routers.

Every 404 "resource missing" detail raised under ``deeptutor/api/routers`` must
come from :func:`not_found` (or the i18n ``t()`` keys), so clients can match one
stable template instead of a dozen ad-hoc wordings.
"""

from __future__ import annotations

from fastapi import HTTPException, status


def not_found(resource: str, identifier: object | None = None) -> HTTPException:
    """Build the canonical 404 for a missing resource.

    ``resource`` is the noun phrase shown to clients (``"Session"``,
    ``"Knowledge base"``); ``identifier`` optionally names the exact instance
    that was looked up. The rendered detail is exactly one of:

    - ``"<resource> not found"``
    - ``"<resource> '<identifier>' not found"``
    """
    if identifier is None:
        detail = f"{resource} not found"
    else:
        detail = f"{resource} '{identifier}' not found"
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
