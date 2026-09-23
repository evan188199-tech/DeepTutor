"""HTTP authentication bridge for LinguaWave media routes."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import Cookie, Header, HTTPException, status

from deeptutor.api.routers.auth import _extract_token, _install_current_user, require_auth
from deeptutor.media.access import MediaAccessStore
from deeptutor.media.auth import SESSION_SCOPES, MediaRequestPrincipal
from deeptutor.multi_user.paths import local_admin_user


async def require_media_auth(
    authorization: str | None = Header(default=None, alias="Authorization"),
    dt_token: str | None = Cookie(default=None, alias="dt_token"),
) -> MediaRequestPrincipal:
    """Accept a browser JWT or an exchanged LinguaWave mobile credential."""
    token = _extract_token(authorization, dt_token)
    if token and token.startswith("lw_mobile_"):
        principal = MediaAccessStore().verify(token, allowed_kinds={"mobile"})
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired LinguaWave mobile token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if principal.owner_id == local_admin_user().id:
            _install_current_user(None)
            return MediaRequestPrincipal(principal=principal, scopes=principal.scopes)
        try:
            from deeptutor.multi_user.identity import get_user_by_id

            record = get_user_by_id(principal.owner_id)
            if record is None:
                raise LookupError("owner is missing")
            username, values = record
            _install_current_user(
                SimpleNamespace(
                    username=username,
                    role=str(values.get("role") or "user"),
                    user_id=principal.owner_id,
                )
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is unavailable"
            ) from exc
        return MediaRequestPrincipal(principal=principal, scopes=principal.scopes)
    await require_auth(authorization=authorization, dt_token=dt_token)
    return MediaRequestPrincipal(principal=None, scopes=SESSION_SCOPES)


def require_scope(principal: MediaRequestPrincipal, scope: str) -> None:
    if scope not in principal.scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Media credential lacks required scope: {scope}",
        )


__all__ = ["require_media_auth", "require_scope"]
