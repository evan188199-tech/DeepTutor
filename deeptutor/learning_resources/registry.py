"""Registry for learning-resource providers: lifecycle control plus lookup.

The registry owns three slice-1 responsibilities from #961: validated
registration, explicit enable/disable lifecycle with an error state, and a
lookup path that only queries enabled providers whose declared languages
cover the request. Provider failures degrade to an error state and never
propagate to the caller, so reading and learning flows stay unaffected.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from deeptutor.learning_resources.contracts import (
    InvalidProviderManifest,
    LearningResourceProvider,
    LookupRequest,
    LookupResult,
    ProviderError,
    ProviderManifest,
)
from deeptutor.learning_resources.lifecycle import (
    ProviderState,
    ProviderStateStore,
    transition,
)

logger = logging.getLogger(__name__)


class ProviderStatus(BaseModel):
    """Queryable view of one registered provider."""

    manifest: ProviderManifest
    state: ProviderState
    last_error: str | None = None


class LearningResourceRegistry:
    """In-process registry of learning-resource providers."""

    def __init__(self, state_store: ProviderStateStore | None = None) -> None:
        self._state_store = state_store
        self._providers: dict[str, LearningResourceProvider] = {}
        self._states: dict[str, ProviderState] = {}
        self._last_errors: dict[str, str | None] = {}

    # -- registration ----------------------------------------------------

    def register(self, provider: LearningResourceProvider) -> None:
        """Register a provider; it starts (or resumes) lifecycle state."""
        if not isinstance(provider, LearningResourceProvider):
            raise TypeError(
                f"expected a LearningResourceProvider instance, got {type(provider).__name__}"
            )
        try:
            manifest = ProviderManifest.model_validate(provider.manifest)
        except Exception as exc:
            raise InvalidProviderManifest(str(exc)) from exc
        name = manifest.name
        if name in self._providers:
            raise ValueError(f"provider {name!r} is already registered")

        self._providers[name] = provider
        persisted = self._state_store.load(name) if self._state_store else None
        if persisted is None:
            self._states[name] = ProviderState.INSTALLED
            self._last_errors[name] = None
        else:
            self._states[name] = persisted.state
            self._last_errors[name] = persisted.last_error

    # -- lifecycle control -------------------------------------------------

    def enable(self, name: str) -> None:
        self._move(name, ProviderState.ENABLED)

    def disable(self, name: str) -> None:
        self._move(name, ProviderState.DISABLED)

    def mark_error(self, name: str, reason: str) -> None:
        """Record a provider failure; only running providers can fail."""
        current = self._require(name)
        if current is ProviderState.ERROR:
            self._last_errors[name] = reason
            self._persist(name)
            return
        self._move(name, ProviderState.ERROR)
        self._last_errors[name] = reason
        self._persist(name)

    # -- queries -----------------------------------------------------------

    def status(self) -> list[ProviderStatus]:
        return [
            ProviderStatus(
                manifest=provider.manifest,
                state=self._states[name],
                last_error=self._last_errors.get(name),
            )
            for name, provider in self._providers.items()
        ]

    def get_status(self, name: str) -> ProviderStatus | None:
        provider = self._providers.get(name)
        if provider is None:
            return None
        return ProviderStatus(
            manifest=provider.manifest,
            state=self._states[name],
            last_error=self._last_errors.get(name),
        )

    def lookup(
        self,
        request: LookupRequest | str,
        *,
        provider: str | None = None,
    ) -> list[LookupResult]:
        """Query enabled providers; never raises on provider-side failures."""
        if isinstance(request, str):
            request = LookupRequest(term=request)
        results: list[LookupResult] = []
        for name, candidate in self._providers.items():
            if provider is not None and name != provider:
                continue
            if self._states[name] is not ProviderState.ENABLED:
                continue
            if not self._supports(candidate.manifest, request):
                continue
            try:
                results.append(candidate.lookup(request))
            except ProviderError as exc:
                logger.warning("Learning-resource provider %s failed: %s", name, exc)
                self.mark_error(name, str(exc))
            except Exception:
                logger.warning(
                    "Learning-resource provider %s raised unexpectedly", name, exc_info=True
                )
                self.mark_error(name, "unexpected provider failure")
        return results

    # -- internals -----------------------------------------------------------

    def _supports(self, manifest: ProviderManifest, request: LookupRequest) -> bool:
        if "*" in manifest.languages:
            return True
        for language in (request.source_language, request.target_language):
            if language is not None and language not in manifest.languages:
                return False
        return True

    def _move(self, name: str, target: ProviderState) -> None:
        current = self._require(name)
        self._states[name] = transition(current, target, provider=name)
        if target is not ProviderState.ERROR:
            self._last_errors[name] = None
        self._persist(name)

    def _persist(self, name: str) -> None:
        if self._state_store is not None:
            self._state_store.save(name, self._states[name], last_error=self._last_errors.get(name))

    def _require(self, name: str) -> ProviderState:
        try:
            return self._states[name]
        except KeyError:
            raise KeyError(f"unknown learning-resource provider {name!r}") from None


__all__ = ["LearningResourceRegistry", "ProviderStatus"]
