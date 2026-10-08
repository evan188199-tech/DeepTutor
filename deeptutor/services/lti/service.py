"""LTI 1.3 launch validation — first slice of upstream issue #567.

Scope of this module (the rest is intentionally deferred, see AGENTS.md next
to this file):

* OIDC third-party initiated login (``begin_login``) — validate the platform
  parameters and redirect back to the platform's authorization endpoint with
  a fresh ``state``/``nonce`` pair.
* Resource link launch validation (``complete_launch``) — consume the
  single-use ``state``, verify the platform-signed ``id_token`` (RS256 against
  the platform JWKS) and enforce the LTI claims required for a minimal
  resource-link launch.

The service is deliberately dependency-free beyond the existing core stack
(``python-jose`` + ``cryptography`` + ``httpx``); it is offline-testable via
the inline ``key_set`` platform option.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import secrets
import threading
import time
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

# LTI 1.3 claim URIs (IMS LTI 1.3 core specification).
MESSAGE_TYPE_CLAIM = "https://purl.imsglobal.org/spec/lti/claim/message_type"
DEPLOYMENT_ID_CLAIM = "https://purl.imsglobal.org/spec/lti/claim/deployment_id"
TARGET_LINK_URI_CLAIM = "https://purl.imsglobal.org/spec/lti/claim/target_link_uri"
ROLES_CLAIM = "https://purl.imsglobal.org/spec/lti/claim/roles"
RESOURCE_LINK_CLAIM = "https://purl.imsglobal.org/spec/lti/claim/resource_link"

RESOURCE_LINK_REQUEST = "LtiResourceLinkRequest"

_STATE_TTL_SECONDS = 600
_MAX_PENDING_STATES = 1024
_JWKS_CACHE_SECONDS = 900
_IAT_FUTURE_TOLERANCE_SECONDS = 300

_DEFAULT_STATE_TTL = _STATE_TTL_SECONDS
_DEFAULT_CLOCK: Callable[[], float] = time.time


@dataclass(frozen=True)
class LtiPlatform:
    """One registered LTI 1.3 platform (tool deployment)."""

    issuer: str
    client_id: str
    deployment_ids: frozenset[str]
    auth_login_url: str
    target_link_uri: str
    key_set_url: str = ""
    key_set: Mapping[str, Any] | None = None


class LtiError(Exception):
    """A rejected login-init/launch request.

    ``code`` is a stable, non-reflecting identifier safe to return to the
    platform; ``detail`` is for server-side logs only.
    """

    def __init__(self, code: str, status_code: int = 400, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class LtiLoginResult:
    redirect_url: str
    state: str


@dataclass(frozen=True)
class LtiLaunchResult:
    platform: LtiPlatform
    claims: dict[str, Any]
    sub: str
    roles: tuple[str, ...]


def _base64url_uint(raw: str) -> int:
    from base64 import urlsafe_b64decode

    padding = "=" * (-len(raw) % 4)
    return int.from_bytes(urlsafe_b64decode(raw + padding), "big")


def _rsa_public_key_from_jwk(jwk: Mapping[str, Any]) -> Any:
    """Build a cryptography RSA public key from an RSA JWK (``n``/``e``)."""
    from cryptography.hazmat.primitives.asymmetric import rsa

    if str(jwk.get("kty") or "") != "RSA":
        raise LtiError("invalid_id_token", detail="non-RSA platform key")
    try:
        modulus = _base64url_uint(str(jwk["n"]))
        exponent = _base64url_uint(str(jwk["e"]))
        return rsa.RSAPublicNumbers(exponent, modulus).public_key()
    except (KeyError, ValueError, TypeError) as exc:
        raise LtiError("invalid_id_token", detail=f"malformed platform key: {exc}") from exc


class LtiService:
    """Validates the platform-facing half of an LTI 1.3 launch.

    Pending login states live in process memory: acceptable for the single
    worker deployment DeepTutor ships by default, and a deliberate
    simplification of this first slice.
    """

    def __init__(
        self,
        platforms: Iterable[LtiPlatform] = (),
        *,
        enabled: bool = True,
        state_ttl_seconds: int = _DEFAULT_STATE_TTL,
        clock: Callable[[], float] = _DEFAULT_CLOCK,
    ) -> None:
        self._platforms = tuple(platforms)
        self._flag_enabled = bool(enabled)
        self._state_ttl = int(state_ttl_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: dict[str, dict[str, Any]] = {}
        self._jwks_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> "LtiService":
        platforms = [
            LtiPlatform(
                issuer=str(entry.get("issuer") or ""),
                client_id=str(entry.get("client_id") or ""),
                deployment_ids=frozenset(str(item) for item in entry.get("deployment_ids") or []),
                auth_login_url=str(entry.get("auth_login_url") or ""),
                target_link_uri=str(entry.get("target_link_uri") or ""),
                key_set_url=str(entry.get("key_set_url") or ""),
                key_set=entry.get("key_set") if entry.get("key_set") is not None else None,
            )
            for entry in settings.get("platforms") or []
            if isinstance(entry, dict)
        ]
        return cls(platforms, enabled=bool(settings.get("enabled")))

    @property
    def enabled(self) -> bool:
        return self._flag_enabled and bool(self._platforms)

    # ------------------------------------------------------------------
    # OIDC third-party initiated login
    # ------------------------------------------------------------------

    def find_platform(self, iss: str, client_id: str | None = None) -> LtiPlatform | None:
        matches = [platform for platform in self._platforms if platform.issuer == iss]
        if client_id:
            matches = [platform for platform in matches if platform.client_id == client_id]
        if len(matches) != 1:
            # No registration, or an ambiguous issuer/client pair the operator
            # must disambiguate by sending client_id.
            return None
        return matches[0]

    def begin_login(self, params: Mapping[str, Any], *, redirect_uri: str) -> LtiLoginResult:
        iss = str(params.get("iss") or "").strip().rstrip("/")
        client_id = str(params.get("client_id") or "").strip() or None
        login_hint = str(params.get("login_hint") or "").strip()
        target_link_uri = str(params.get("target_link_uri") or "").strip()
        message_hint = str(params.get("lti_message_hint") or "").strip()
        deployment_hint = str(params.get("lti_deployment_id") or "").strip()

        if not iss:
            raise LtiError("missing_issuer")
        if not login_hint:
            raise LtiError("missing_login_hint")
        if not target_link_uri:
            raise LtiError("missing_target_link_uri")
        if not redirect_uri.startswith(("http://", "https://")):
            raise LtiError("invalid_redirect_uri", detail="redirect_uri must be absolute http(s)")

        platform = self.find_platform(iss, client_id)
        if platform is None:
            raise LtiError("unregistered_issuer", detail=f"iss={iss!r} client_id={client_id!r}")
        if target_link_uri != platform.target_link_uri:
            raise LtiError("target_link_uri_mismatch")
        if deployment_hint and deployment_hint not in platform.deployment_ids:
            raise LtiError("unregistered_deployment", detail=deployment_hint)

        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        now = self._clock()
        with self._lock:
            self._prune_expired_locked(now)
            self._pending[state] = {
                "nonce": nonce,
                "target_link_uri": target_link_uri,
                "iss": platform.issuer,
                "client_id": platform.client_id,
                "expires_at": now + self._state_ttl,
            }

        query = {
            "scope": "openid",
            "response_type": "id_token",
            "response_mode": "form_post",
            "prompt": "none",
            "client_id": platform.client_id,
            "redirect_uri": redirect_uri,
            "login_hint": login_hint,
            "state": state,
            "nonce": nonce,
        }
        if message_hint:
            query["lti_message_hint"] = message_hint

        split = urlsplit(platform.auth_login_url)
        redirect_url = urlunsplit(
            (split.scheme, split.netloc, split.path, urlencode(query), split.fragment)
        )
        return LtiLoginResult(redirect_url=redirect_url, state=state)

    def _prune_expired_locked(self, now: float) -> None:
        expired = [
            state for state, pending in self._pending.items() if pending["expires_at"] <= now
        ]
        for state in expired:
            self._pending.pop(state, None)
        while len(self._pending) >= _MAX_PENDING_STATES:
            oldest = min(self._pending, key=lambda s: self._pending[s]["expires_at"])
            self._pending.pop(oldest, None)

    # ------------------------------------------------------------------
    # Resource link launch
    # ------------------------------------------------------------------

    async def complete_launch(self, form: Mapping[str, Any]) -> LtiLaunchResult:
        state = str(form.get("state") or "").strip()
        id_token = str(form.get("id_token") or "").strip()
        if not state:
            raise LtiError("missing_state")
        if not id_token:
            raise LtiError("missing_id_token")

        pending = self._consume_state(state)
        platform = self.find_platform(str(pending["iss"]), str(pending["client_id"]))
        if platform is None:
            raise LtiError("unregistered_issuer")

        claims = await self._verify_id_token(id_token, platform)

        nonce = str(claims.get("nonce") or "")
        if not nonce or nonce != str(pending["nonce"]):
            raise LtiError("nonce_mismatch")

        message_type = str(claims.get(MESSAGE_TYPE_CLAIM) or "")
        if message_type != RESOURCE_LINK_REQUEST:
            raise LtiError("unsupported_message", detail=f"message_type={message_type!r}")
        resource_link = claims.get(RESOURCE_LINK_CLAIM)
        if not isinstance(resource_link, dict) or not str(resource_link.get("id") or ""):
            raise LtiError("unsupported_message", detail="missing resource_link id")

        deployment_id = claims.get(DEPLOYMENT_ID_CLAIM)
        if isinstance(deployment_id, str):
            deployments = {deployment_id}
        elif isinstance(deployment_id, list):
            deployments = {str(item) for item in deployment_id}
        else:
            deployments = set()
        if not deployments & platform.deployment_ids:
            raise LtiError("unregistered_deployment", detail=f"claims={sorted(deployments)}")

        claim_target = str(claims.get(TARGET_LINK_URI_CLAIM) or "")
        if claim_target != str(pending["target_link_uri"]):
            raise LtiError("target_link_uri_mismatch", detail=f"claim={claim_target!r}")

        sub = str(claims.get("sub") or "").strip()
        if not sub:
            raise LtiError("invalid_id_token", detail="empty sub")

        raw_roles = claims.get(ROLES_CLAIM)
        roles = tuple(str(role) for role in raw_roles) if isinstance(raw_roles, list) else ()

        return LtiLaunchResult(platform=platform, claims=claims, sub=sub, roles=roles)

    def _consume_state(self, state: str) -> dict[str, Any]:
        with self._lock:
            pending = self._pending.pop(state, None)
        if pending is None or pending["expires_at"] <= self._clock():
            raise LtiError("invalid_state")
        return pending

    async def _verify_id_token(self, id_token: str, platform: LtiPlatform) -> dict[str, Any]:
        from jose import JWTError
        from jose import jwt as jose_jwt

        try:
            header = jose_jwt.get_unverified_header(id_token)
        except JWTError as exc:
            raise LtiError("invalid_id_token", detail=str(exc)) from exc
        if str(header.get("alg") or "") != "RS256":
            raise LtiError("invalid_id_token", detail="unsupported alg")
        kid = str(header.get("kid") or "").strip()
        if not kid:
            raise LtiError("invalid_id_token", detail="missing kid")

        jwk = await self._find_jwk(platform, kid)
        public_key = _rsa_public_key_from_jwk(jwk)
        try:
            claims = dict(
                jose_jwt.decode(
                    id_token,
                    public_key,
                    algorithms=["RS256"],
                    issuer=platform.issuer,
                    audience=platform.client_id,
                    options={
                        "require": ["exp", "iat", "iss", "aud", "sub", "nonce"],
                        # python-jose has no leeway knob; exp/iat drift is
                        # checked manually below with the spec-recommended
                        # tolerance for clock skew.
                        "verify_exp": False,
                    },
                )
            )
        except JWTError as exc:
            raise LtiError("invalid_id_token", detail=str(exc)) from exc

        now = self._clock()
        expires_at = claims.get("exp")
        if not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool):
            raise LtiError("invalid_id_token", detail="invalid exp")
        if expires_at + 60 < now:
            raise LtiError("invalid_id_token", detail="expired")

        issued_at = claims.get("iat")
        if not isinstance(issued_at, (int, float)) or isinstance(issued_at, bool):
            raise LtiError("invalid_id_token", detail="invalid iat")
        if issued_at > now + _IAT_FUTURE_TOLERANCE_SECONDS:
            raise LtiError("invalid_id_token", detail="iat in the future")
        return claims

    async def _find_jwk(self, platform: LtiPlatform, kid: str) -> Mapping[str, Any]:
        jwks = platform.key_set
        if jwks is None:
            jwks = await self._fetch_jwks(platform)
        for jwk in jwks.get("keys") or []:
            if str(jwk.get("kid") or "") == kid:
                return jwk
        raise LtiError("unknown_signing_key", detail=f"kid={kid!r}")

    async def _fetch_jwks(self, platform: LtiPlatform) -> dict[str, Any]:
        now = self._clock()
        cached = self._jwks_cache.get(platform.key_set_url)
        if cached and cached[0] > now:
            return cached[1]
        if not platform.key_set_url:
            raise LtiError("invalid_id_token", detail="platform has no key source")

        import httpx

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(platform.key_set_url)
                response.raise_for_status()
                jwks = response.json()
        except Exception as exc:
            raise LtiError("key_set_unavailable", detail=str(exc)) from exc
        if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
            raise LtiError("key_set_unavailable", detail="malformed JWKS")
        self._jwks_cache[platform.key_set_url] = (now + _JWKS_CACHE_SECONDS, jwks)
        return jwks


_service_instance: LtiService | None = None


def get_lti_service() -> LtiService:
    """Process-wide LTI service built from the runtime ``lti.json`` settings."""
    global _service_instance
    if _service_instance is None:
        from deeptutor.services.config import load_lti_settings

        _service_instance = LtiService.from_settings(load_lti_settings())
    return _service_instance
