"""LTI 1.3 platform-facing endpoints (upstream issue #567, first slice).

Two routes, both initiated by the LMS rather than the browser session, so
they are mounted without the ``require_learning_surface`` gate:

* ``GET/POST /api/lti/login`` — OIDC third-party initiated login: validate the
  platform registration and redirect back to the platform with a fresh
  ``state``/``nonce`` pair.
* ``POST /api/lti/launch`` — resource link launch: consume the single-use
  ``state``, verify the platform-signed ``id_token`` (RS256 + JWKS), map the
  platform subject onto a least-privilege local account, and set the normal
  ``dt_token`` session cookie.

Every endpoint reports 404 unless LTI is explicitly enabled
  (``lti.json`` ``enabled=true`` + at least one platform registration) and
  built-in auth is the active auth mode — so a default deployment behaves
  exactly as before this router existed.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from deeptutor.services.lti import LtiError, LtiService, get_lti_service
from deeptutor.services.lti.provisioning import provision_lti_user

logger = logging.getLogger(__name__)

router = APIRouter()

_service: LtiService | None = None


def _get_service() -> LtiService:
    global _service
    if _service is None:
        _service = get_lti_service()
    return _service


def _active_service() -> LtiService | None:
    """The service, unless LTI must stay dark for this deployment."""
    from deeptutor.services import auth as auth_service

    if not auth_service.AUTH_ENABLED or auth_service.POCKETBASE_ENABLED:
        return None
    service = _get_service()
    return service if service.enabled else None


def _http_error(exc: LtiError) -> HTTPException:
    logger.warning("LTI request rejected: %s %s", exc.code, exc.detail)
    # ``detail`` stays server-side: the response carries only the stable code.
    return HTTPException(status_code=exc.status_code, detail=exc.code)


@router.get("/login")
@router.post("/login")
async def lti_login(request: Request) -> RedirectResponse:
    service = _active_service()
    if service is None:
        raise HTTPException(status_code=404, detail="Not Found")

    if request.method == "POST":
        form = await request.form()
        params: dict[str, str] = {str(key): str(value) for key, value in form.items()}
    else:
        params = dict(request.query_params)

    redirect_uri = f"{str(request.base_url).rstrip('/')}/api/lti/launch"
    try:
        result = service.begin_login(params, redirect_uri=redirect_uri)
    except LtiError as exc:
        raise _http_error(exc) from exc

    return RedirectResponse(
        result.redirect_url,
        status_code=302,
        headers={"Cache-Control": "no-store"},
    )


@router.post("/launch")
async def lti_launch(request: Request, response: Response) -> dict[str, Any]:
    service = _active_service()
    if service is None:
        raise HTTPException(status_code=404, detail="Not Found")

    form = await request.form()
    try:
        launch = await service.complete_launch(
            {str(key): str(value) for key, value in form.items()}
        )
        username, record = provision_lti_user(
            launch.platform.issuer,
            launch.sub,
            launch.roles,
        )
    except LtiError as exc:
        raise _http_error(exc) from exc

    from deeptutor.api.routers.auth import _COOKIE_MAX_AGE, _cookie_attrs
    from deeptutor.services.auth import create_token

    role = str(record.get("role") or "user")
    token = create_token(username, role, str(record.get("id") or ""))
    response.set_cookie(value=token, max_age=_COOKIE_MAX_AGE, **_cookie_attrs())
    response.headers["Cache-Control"] = "no-store"
    logger.info("LTI launch established session for '%s' (role=%s)", username, role)
    return {
        "ok": True,
        "user_id": str(record.get("id") or ""),
        "username": username,
        "role": role,
        "is_admin": False,
    }
