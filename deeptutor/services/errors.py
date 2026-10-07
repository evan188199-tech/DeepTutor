"""Domain errors raised by service and access layers.

Service modules must stay independent of the web framework: they raise these
plain exceptions and the API layer (``deeptutor.api``) maps them onto HTTP
status codes in one place (``deeptutor.api.error_mapping``). Keeping fastapi
out of this module is what lets CLI-side code import these services without
pulling the server stack.
"""

from __future__ import annotations


class ServiceError(Exception):
    """Base class for domain errors the API layer maps onto HTTP responses.

    ``status_code`` is the HTTP status the API layer renders; ``detail`` keeps
    the human-readable message (matching the shape ``HTTPException`` used to
    carry before service layers dropped the fastapi dependency).
    """

    status_code: int = 500

    @property
    def detail(self) -> str:
        return str(self)


class AccessDeniedError(ServiceError):
    """The current user may not access this resource (HTTP 403)."""

    status_code = 403


class ResourceNotFoundError(ServiceError):
    """The referenced resource does not exist or is not visible (HTTP 404)."""

    status_code = 404
