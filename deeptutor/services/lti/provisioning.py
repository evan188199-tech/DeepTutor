"""Map LTI platform identities onto least-privilege local accounts."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Iterable

from .service import LtiError

logger = logging.getLogger(__name__)

#: Membership role URIs (LIS vocabulary) that map to a local ``teacher``.
#: Everything else — Learner, Mentor, or an unknown vocabulary — stays at the
#: least-privileged ``student``.
_TEACHER_ROLE_SUFFIXES = frozenset({"instructor", "teachingassistant", "faculty"})


def local_username_for(issuer: str, sub: str) -> str:
    """Deterministic, collision-free local username for a platform subject.

    Opaque by design: the mapping key is ``issuer|sub`` hashed with SHA-256,
    so the local username neither embeds platform PII nor collides with
    locally chosen accounts.
    """
    digest = hashlib.sha256(f"{str(issuer).rstrip('/')}|{sub}".encode()).hexdigest()[:32]
    return f"lti-{digest}"


def map_local_role(lti_roles: Iterable[str]) -> str:
    """Map LIS membership roles onto the local role model (never ``admin``)."""
    for role in lti_roles:
        suffix = str(role).rsplit("#", 1)[-1].strip().lower()
        if suffix in _TEACHER_ROLE_SUFFIXES:
            return "teacher"
    return "student"


def provision_lti_user(
    issuer: str, sub: str, lti_roles: Iterable[str]
) -> tuple[str, dict[str, Any]]:
    """Return the local account for a verified platform subject, creating it
    on first launch (JIT provisioning).

    Guarantees (see services/lti/AGENTS.md):

    * never creates — or returns a session for — an ``admin`` account;
    * the role is fixed at first provisioning and never drifts on re-launch;
    * provisioned accounts have an unusable password hash, so they cannot
      password-login through ``/api/auth/login``.
    """
    from deeptutor.multi_user import identity

    role = map_local_role(lti_roles)
    preset = "standard" if role == "teacher" else "learner"
    username = local_username_for(issuer, sub)

    record = identity.provision_external_user(username, role=role, preset=preset)

    if bool(record.get("disabled")):
        raise LtiError("account_disabled", status_code=403)
    if str(record.get("role") or "") == "admin":
        # An operator manually elevated this account; an LTI launch must never
        # be a session-issuing path into an admin account.
        raise LtiError("account_not_launchable", status_code=403)
    return username, record
