"""Provider lifecycle: installed → enabled/disabled with an explicit error state.

Installation never implies enablement (#961): a freshly registered provider
is ``installed`` and only answers lookups once explicitly ``enabled``.
Disabling preserves provider data — this module only tracks state and never
deletes anything under the provider-specific storage directory.
"""

from __future__ import annotations

from enum import Enum
import json
import logging
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)


class ProviderState(str, Enum):
    """Lifecycle states a learning-resource provider moves through."""

    INSTALLED = "installed"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"


_ALLOWED_TRANSITIONS: dict[ProviderState, frozenset[ProviderState]] = {
    ProviderState.INSTALLED: frozenset({ProviderState.ENABLED, ProviderState.DISABLED}),
    ProviderState.ENABLED: frozenset({ProviderState.DISABLED, ProviderState.ERROR}),
    ProviderState.DISABLED: frozenset({ProviderState.ENABLED}),
    ProviderState.ERROR: frozenset({ProviderState.ENABLED, ProviderState.DISABLED}),
}


class InvalidProviderStateTransition(ValueError):
    """Raised when a lifecycle move is not allowed from the current state."""

    def __init__(
        self,
        provider: str,
        current: ProviderState,
        target: ProviderState,
    ) -> None:
        super().__init__(
            f"provider {provider!r} cannot move from {current.value} to {target.value}"
        )
        self.provider = provider
        self.current = current
        self.target = target


def transition(
    current: ProviderState,
    target: ProviderState,
    *,
    provider: str = "<unregistered>",
) -> ProviderState:
    """Validate a lifecycle move and return the new state."""
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidProviderStateTransition(provider, current, target)
    return target


class PersistedProviderState(NamedTuple):
    """A provider's persisted lifecycle record."""

    state: ProviderState
    last_error: str | None


class ProviderStateStore:
    """Persists lifecycle state under provider-specific workspace directories.

    Each provider's record lives in ``<base_dir>/<provider>/state.json`` so
    provider data stays isolated and disabling a provider never touches its
    files. Persistence is best-effort: unreadable state files are logged and
    ignored rather than propagated to callers.
    """

    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)

    def _state_file(self, provider: str) -> Path:
        return self._base_dir / provider / "state.json"

    def save(
        self,
        provider: str,
        state: ProviderState,
        *,
        last_error: str | None = None,
    ) -> None:
        path = self._state_file(provider)
        payload = {"state": state.value, "last_error": last_error}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            logger.warning("Could not persist state for provider %r", provider, exc_info=True)

    def load(self, provider: str) -> PersistedProviderState | None:
        try:
            payload = json.loads(self._state_file(provider).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            logger.warning("Ignoring unreadable state file for provider %r", provider)
            return None
        try:
            return PersistedProviderState(
                ProviderState(payload["state"]), payload.get("last_error")
            )
        except (KeyError, ValueError):
            logger.warning("Ignoring malformed state payload for provider %r", provider)
            return None


__all__ = [
    "InvalidProviderStateTransition",
    "PersistedProviderState",
    "ProviderState",
    "ProviderStateStore",
    "transition",
]
