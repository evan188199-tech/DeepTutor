"""The structured error envelope, as the REST contract records it.

Routers that refuse a request with ``HTTPException(detail={"code": ...,
"message": ...})`` speak a shared shape: FastAPI wraps ``detail`` verbatim, so
the wire body is ``{"detail": {"code": ..., "message": ..., ...}}``. Until the
models below existed, none of that was documented — FastAPI does not render
schemas for manually raised ``HTTPException``s, so every such refusal showed up
in the generated contract as an undocumented status, and frontend code parsed
``detail.code`` by hand (see ``web/lib/mcp-api.ts``).

Declaring these models in a route's ``responses=`` changes no behaviour: status
codes and payloads stay exactly as the handlers raise them. The models only
make the OpenAPI render — and the TypeScript generated from it — carry the
shape, so clients can stop hand-writing it.

Emitters occasionally add fields beyond ``code`` and ``message`` (an install
log, the notebook a damaged file belonged to). The base envelope allows
extras so it never lies by omission; the emitters whose extras are part of the
contract subclass it (and get their own component) so those fields are typed
rather than merely tolerated.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_STATUS_DESCRIPTIONS = {
    400: "Refused: the request or the state it targets is invalid.",
    401: "Refused: the caller's credentials are missing or expired.",
    403: "Refused: the caller may not perform this action.",
    404: "Refused: the addressed object does not exist.",
    408: "Refused: an upstream call timed out.",
    409: "Refused: the request conflicts with the current state.",
    429: "Refused: an upstream rate limit was hit.",
}


class StructuredErrorEnvelope(BaseModel):
    """The ``detail`` payload of a structured refusal (``{"code", "message"}``)."""

    model_config = ConfigDict(extra="allow")

    code: str = Field(examples=["mcp.not_oauth"])
    message: str = Field(examples=["This server does not use OAuth."])


class StructuredErrorResponse(BaseModel):
    """A refusal the UI can explain: the envelope, wrapped as FastAPI emits it."""

    detail: StructuredErrorEnvelope


class CliInstallErrorEnvelope(StructuredErrorEnvelope):
    """A failed CLI-app install, carrying the output that explains it."""

    log: str = Field(default="", description="Install output; the actionable part of the refusal.")


class CliInstallErrorResponse(BaseModel):
    detail: CliInstallErrorEnvelope


class NotebookUnreadableErrorEnvelope(StructuredErrorEnvelope):
    """A notebook too damaged to read, naming the file that failed."""

    notebook_id: str = Field(default="", description="The notebook whose stored file is damaged.")


class NotebookUnreadableErrorResponse(BaseModel):
    detail: NotebookUnreadableErrorEnvelope


def envelope_responses(
    *statuses: int,
    model: type[BaseModel] = StructuredErrorResponse,
) -> dict[int, dict[str, Any]]:
    """Build ``responses=`` entries documenting the envelope for ``statuses``.

    Purely declarative: FastAPI merges these with its automatic entries (the
    request-validation ``422`` keeps its own schema), and nothing about the
    runtime response changes.
    """

    return {
        status: {
            "model": model,
            "description": _STATUS_DESCRIPTIONS.get(
                status, "Refused with a structured error envelope."
            ),
        }
        for status in statuses
    }


def envelope_ref_response(
    status: int,
    model: type[BaseModel],
) -> dict[int, dict[str, Any]]:
    """Like ``envelope_responses``, for one status, as a hand-written ``$ref``.

    For a route whose ``response_class`` is not JSON (the notebook export's
    ``PlainTextResponse``), FastAPI files any ``{"model": ...}`` entry under
    the route's own media type, which would document a JSON refusal body as
    ``text/plain``. Pointing at the component by name sidesteps that; the
    component itself is registered by the sibling routes of the same router
    that declare the model directly.
    """

    return {
        status: {
            "description": _STATUS_DESCRIPTIONS.get(
                status, "Refused with a structured error envelope."
            ),
            "content": {
                "application/json": {"schema": {"$ref": f"#/components/schemas/{model.__name__}"}}
            },
        }
    }


__all__ = [
    "CliInstallErrorEnvelope",
    "CliInstallErrorResponse",
    "NotebookUnreadableErrorEnvelope",
    "NotebookUnreadableErrorResponse",
    "StructuredErrorEnvelope",
    "StructuredErrorResponse",
    "envelope_ref_response",
    "envelope_responses",
]
