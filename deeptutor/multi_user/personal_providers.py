"""Personal API-key LLM providers — bring your own key (#1927).

A personal API-key provider is the API-key counterpart of the per-user Codex
sign-in (#781): an ordinary user in an authenticated deployment adds a
provider profile — OpenRouter, Anthropic, OpenAI, any registry vendor with a
fixed endpoint — that only their account can see or use. The administrator
still owns every shared profile and every grant, and decides whether this
surface exists at all through the ``allow_personal_providers`` deployment
switch (off by default).

The isolation rules, in decreasing order of importance:

* **The key never enters any catalog file.** A profile is written to the
  user's OWN catalog (``data/users/<uid>/settings/model_catalog.json``, the
  same owner-scope file a Codex sign-in uses) with an empty ``api_key``; the
  key itself lives in the owner's ``user-secrets`` directory, which the
  sandbox runner never mounts. On the resolution path
  :func:`~deeptutor.multi_user.personal_models.merge_personal_llm_profiles`
  calls :func:`inject_personal_api_keys` to add the key to the in-memory
  catalog copy it builds — nothing that holds it is ever persisted or
  returned by an API.
* **The endpoint is never user-supplied.** A personal profile binds to a
  registry vendor and uses that vendor's fixed default base URL, so a user
  cannot point the server at an address of their choosing.
* **Profiles are owner-bound** (``owner_bound`` + ``managed_by``), so grants
  keep ignoring them exactly like a Codex profile — one user's key is never
  lent to another account.

Everything a user may reach funnels through
:func:`~deeptutor.multi_user.model_access.redacted_model_access` and the
merge on the resolution path, so hiding a profile in
:func:`~deeptutor.multi_user.personal_models._personal_catalog_profiles`
switching the policy off — removes it from the option list, the selection
gate, and inference at once, without deleting the stored secret.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import stat
from typing import Any

from deeptutor.services.config.model_catalog import ModelCatalogService

from .context import get_current_user
from .paths import get_owner_secrets_dir
from .personal_models import owner_catalog_service

logger = logging.getLogger(__name__)

#: ``managed_by`` stamp that marks a profile as this module's to manage.
MANAGED_BY = "personal_api_key"

#: Personal profile ids all start with this prefix, so an id from any other
#: source (the Codex constants, a hand-written catalog) can never be hijacked
#: by a personal-provider write.
PROFILE_ID_PREFIX = "personal-"

_PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

#: Where below the owner's secrets root the keys live — ``private/<asset>/``
#: is the layout every owner-keyed store uses there.
_SECRETS_ASSET = "private/personal-providers"


class PersonalProviderError(ValueError):
    """A personal-provider write was refused. ``str(exc)`` is public copy."""


def personal_providers_allowed() -> bool:
    """Whether the administrator lets ordinary users add personal providers.

    Reads the deployment-wide system settings (the administrator's settings
    tree), never anything in the caller's own workspace, so the answer is the
    same for every account on the deployment.
    """
    from deeptutor.services.config import load_system_settings

    return bool(load_system_settings().get("allow_personal_providers"))


def allowed_provider_bindings() -> dict[str, dict[str, Any]]:
    """Vendors a personal profile may bind to.

    Registry entries with a fixed vendor endpoint and plain API-key auth.
    Excluded on purpose: OAuth vendors (Codex, Copilot, CodeBuddy — they have
    their own login flows), local endpoints, legacy aliases, and ``custom``
    (an empty default base URL means the address would be user-supplied).
    """
    from deeptutor.services.provider_registry import PROVIDERS

    return {
        spec.name: {
            "label": spec.label,
            "base_url": spec.default_api_base,
            "api_format": spec.default_api_format,
        }
        for spec in PROVIDERS
        if spec.default_api_base and not spec.is_oauth and not spec.is_local and not spec.is_legacy
    }


# ---------------------------------------------------------------------------
# Secret storage (owner-scoped, never inside a workspace or a catalog file)
# ---------------------------------------------------------------------------


def _secret_path(profile_id: str) -> Path:
    return get_owner_secrets_dir() / _SECRETS_ASSET / f"{profile_id}.json"


def stored_api_key(profile_id: str) -> str:
    """The key saved for *profile_id* by the owner of the current scope."""
    path = _secret_path(profile_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    key = payload.get("api_key")
    return key if isinstance(key, str) else ""


def _write_api_key(profile_id: str, api_key: str) -> None:
    path = _secret_path(profile_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Every level below the owner's secrets root stays owner-only, the same
    # posture the codex credential store keeps: the file is created with 0600
    # and re-chmodded on every write so a copy restored with a wider mode
    # does not keep it, and the directories never open up at all.
    for directory in (path.parent.parent, path.parent):
        os.chmod(directory, stat.S_IRWXU)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"api_key": api_key}, handle)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _remove_api_key(profile_id: str) -> None:
    _secret_path(profile_id).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Catalog read/write (the owner's own catalog, never the shared one)
# ---------------------------------------------------------------------------


def _catalog_service() -> ModelCatalogService:
    return owner_catalog_service()


def _personal_profiles(catalog: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    service = _catalog_service()
    if catalog is None:
        if not service.path.exists():
            return []
        catalog = service.load()
    profiles = catalog.get("services", {}).get("llm", {}).get("profiles", []) or []
    return [
        profile
        for profile in profiles
        if isinstance(profile, dict) and profile.get("managed_by") == MANAGED_BY
    ]


def _normalize_models(raw: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise PersonalProviderError("Add at least one model to the provider.")
    models: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise PersonalProviderError("Each model must be an object.")
        model_id = str(entry.get("model") or "").strip()
        if not model_id:
            raise PersonalProviderError("Each model needs the model id the vendor expects.")
        item_id = str(entry.get("id") or "").strip() or model_id
        if item_id in seen_ids:
            raise PersonalProviderError(f"Duplicate model id: {item_id}")
        seen_ids.add(item_id)
        models.append(
            {
                "id": item_id,
                "name": str(entry.get("name") or "").strip() or model_id,
                "model": model_id,
            }
        )
    return models


def _next_profile_id(binding: str, existing: set[str]) -> str:
    base = f"{PROFILE_ID_PREFIX}{binding}"
    candidate = base
    suffix = 1
    while candidate in existing:
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


def _audit(action: str, profile_id: str) -> None:
    """Record a personal-provider write without ever logging the key."""
    from .audit import log_usage

    log_usage("personal_provider", profile_id, action, extra={"binding_managed_by": MANAGED_BY})


def save_personal_provider(
    *,
    profile_id: str | None = None,
    name: str = "",
    binding: str,
    api_key: str | None = None,
    models: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create or update the caller's own API-key provider profile.

    The profile is written owner-scoped with an empty ``api_key``; the key,
    when supplied, goes to the owner's secret store. An update that omits it
    keeps the stored one. Returns the public (redacted) view of the profile.
    """
    user = get_current_user()
    if user.is_admin:
        raise PersonalProviderError(
            "Administrators configure providers in the shared model catalog."
        )
    if not personal_providers_allowed():
        raise PersonalProviderError("Personal API-key providers are disabled by the administrator.")
    bindings = allowed_provider_bindings()
    binding = str(binding or "").strip().lower().replace("-", "_")
    if binding not in bindings:
        raise PersonalProviderError(
            "Choose a provider from the supported list; custom endpoints are not allowed."
        )
    name = str(name or "").strip() or bindings[binding]["label"]
    normalized_models = _normalize_models(models)

    service = _catalog_service()
    current = service.load()
    current_profiles = current.get("services", {}).get("llm", {}).get("profiles", []) or []
    existing_ids = {
        str(profile.get("id") or "") for profile in current_profiles if isinstance(profile, dict)
    }
    if profile_id:
        resolved_id = str(profile_id).strip()
        if not resolved_id.startswith(PROFILE_ID_PREFIX) or not _PROFILE_ID_RE.match(
            resolved_id[len(PROFILE_ID_PREFIX) :]
        ):
            raise PersonalProviderError(
                "Profile ids must start with 'personal-' and use lowercase letters, "
                "digits, and dashes."
            )
        for profile in current_profiles:
            if (
                isinstance(profile, dict)
                and str(profile.get("id") or "") == resolved_id
                and profile.get("managed_by") != MANAGED_BY
            ):
                raise PersonalProviderError(
                    "That id belongs to another provider and cannot be replaced."
                )
    else:
        resolved_id = _next_profile_id(binding, existing_ids)
    new_key = str(api_key).strip() if api_key is not None else ""
    if not new_key and not stored_api_key(resolved_id):
        # Refused before any write: a profile without a usable key would show
        # up as an option that fails every turn.
        raise PersonalProviderError("An API key is required.")

    def mutate(catalog: dict[str, Any]) -> None:
        services = catalog.setdefault("services", {})
        llm = services.setdefault("llm", {})
        profiles = llm.setdefault("profiles", [])
        profiles[:] = [
            profile
            for profile in profiles
            if not (
                isinstance(profile, dict)
                and str(profile.get("id") or "") == resolved_id
                and profile.get("managed_by") == MANAGED_BY
            )
        ]
        profiles.append(
            {
                "id": resolved_id,
                "name": name,
                "binding": binding,
                "base_url": bindings[binding]["base_url"],
                # Never a secret here: the key lives in the owner's secret
                # store and is injected at resolution time.
                "api_key": "",
                "api_version": "",
                "extra_headers": {},
                "managed_by": MANAGED_BY,
                "owner_bound": True,
                "models": normalized_models,
            }
        )

    service.update(mutate)
    if new_key:
        _write_api_key(resolved_id, new_key)
    _audit("save", resolved_id)
    return public_provider_profile(_profile_by_id(service.load(), resolved_id))


def _profile_by_id(catalog: dict[str, Any], profile_id: str) -> dict[str, Any] | None:
    for profile in catalog.get("services", {}).get("llm", {}).get("profiles", []) or []:
        if isinstance(profile, dict) and str(profile.get("id") or "") == profile_id:
            return profile
    return None


def delete_personal_provider(profile_id: str) -> None:
    """Remove the caller's own provider profile and its stored key.

    Allowed even when the policy is off: it only ever deletes the caller's
    own data, and a user whose deployment withdrew the feature should still
    be able to take their key back out.
    """
    user = get_current_user()
    if user.is_admin:
        raise PersonalProviderError(
            "Administrators configure providers in the shared model catalog."
        )
    profile_id = str(profile_id or "").strip()
    service = _catalog_service()

    removed = False

    def mutate(catalog: dict[str, Any]) -> None:
        nonlocal removed
        profiles = catalog.get("services", {}).get("llm", {}).get("profiles", [])
        kept = []
        for profile in profiles:
            if (
                isinstance(profile, dict)
                and str(profile.get("id") or "") == profile_id
                and profile.get("managed_by") == MANAGED_BY
            ):
                removed = True
                continue
            kept.append(profile)
        catalog["services"]["llm"]["profiles"] = kept

    service.update(mutate)
    _remove_api_key(profile_id)
    if not removed:
        raise PersonalProviderError("No such personal provider.")
    _audit("delete", profile_id)


def public_provider_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """API-safe view of a personal provider: everything but the key."""
    profile_id = str(profile.get("id") or "")
    return {
        "id": profile_id,
        "name": profile.get("name") or profile_id,
        "binding": profile.get("binding") or "",
        "base_url": profile.get("base_url") or "",
        "has_api_key": bool(stored_api_key(profile_id)),
        "models": [
            {
                "id": str(model.get("id") or ""),
                "name": model.get("name") or model.get("model") or "",
                "model": model.get("model") or "",
            }
            for model in profile.get("models", []) or []
            if isinstance(model, dict)
        ],
    }


def list_personal_providers() -> list[dict[str, Any]]:
    """The caller's own personal providers, redacted.

    Empty for an administrator (their providers live in the shared catalog)
    and in scopes without a signed-in user. Visible even when the policy is
    off, so a user can still find and delete what they saved.
    """
    from .context import get_current_user_or_none

    user = get_current_user_or_none()
    if user is None or user.is_admin:
        return []
    return [public_provider_profile(profile) for profile in _personal_profiles()]


def inject_personal_api_keys(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copies of *profiles* with each personal provider's key attached.

    Called on the resolution path, where the merged in-memory catalog is what
    the LLM layer reads credentials from. The stored catalog profile keeps an
    empty ``api_key``; only the copy handed to resolution ever carries the
    key, and nothing persists or serializes that copy.
    """
    injected: list[dict[str, Any]] = []
    for profile in profiles:
        if isinstance(profile, dict) and profile.get("managed_by") == MANAGED_BY:
            profile = {**profile, "api_key": stored_api_key(str(profile.get("id") or ""))}
        injected.append(profile)
    return injected


__all__ = [
    "MANAGED_BY",
    "PersonalProviderError",
    "allowed_provider_bindings",
    "delete_personal_provider",
    "inject_personal_api_keys",
    "list_personal_providers",
    "personal_providers_allowed",
    "public_provider_profile",
    "save_personal_provider",
    "stored_api_key",
]
