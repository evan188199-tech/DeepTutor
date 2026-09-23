"""Transport-neutral LinguaWave request principal types."""

from __future__ import annotations

from dataclasses import dataclass

from .access import MediaPrincipal


@dataclass(frozen=True)
class MediaRequestPrincipal:
    principal: MediaPrincipal | None
    scopes: frozenset[str]

    @property
    def is_session(self) -> bool:
        return self.principal is None


SESSION_SCOPES = frozenset(
    {"media:read", "playlist:read", "playlist:write", "subscription:write", "import:write"}
)


__all__ = ["MediaRequestPrincipal", "SESSION_SCOPES"]
