"""Route-layer mapping of service domain errors onto HTTP responses.

Service layers raise :class:`~deeptutor.services.errors.ServiceError`
subclasses; this is the single seam that turns them into the same JSON
envelope fastapi's ``HTTPException`` handler produced when the service layer
still raised it directly (``{"detail": ...}`` with the error's status code).
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from deeptutor.services.errors import ServiceError


async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    """Render a :class:`ServiceError` with its own status code and detail."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
