"""Shared structured error envelope for REST 4xx responses.

Routers that raise ``HTTPException(detail={"code": ..., "message": ...})``
reference these models (or subclasses that pin ``code`` and add fields) in
their ``responses={...}`` declarations so the generated frontend contract
records the real error body: ``{"detail": {"code": ..., "message": ...}}``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Structured payload FastAPI nests under ``detail`` in 4xx bodies."""

    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Human-readable explanation of the failure.")


class ErrorResponse(BaseModel):
    """Envelope of REST 4xx bodies raised as ``HTTPException(detail=ErrorDetail)``."""

    detail: ErrorDetail
