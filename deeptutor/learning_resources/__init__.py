"""Learning-resource providers: typed lookup contracts and lifecycle (#961)."""

from deeptutor.learning_resources.builtin import BuiltinDictionaryProvider
from deeptutor.learning_resources.contracts import (
    Definition,
    Example,
    InvalidProviderManifest,
    LearningResourceProvider,
    LookupRequest,
    LookupResult,
    Phonetic,
    ProviderError,
    ProviderManifest,
    ProviderPermission,
    ProviderType,
    SourceAttribution,
    Translation,
)
from deeptutor.learning_resources.lifecycle import (
    InvalidProviderStateTransition,
    ProviderState,
    ProviderStateStore,
)
from deeptutor.learning_resources.registry import LearningResourceRegistry, ProviderStatus

__all__ = [
    "BuiltinDictionaryProvider",
    "Definition",
    "Example",
    "InvalidProviderManifest",
    "InvalidProviderStateTransition",
    "LearningResourceProvider",
    "LearningResourceRegistry",
    "LookupRequest",
    "LookupResult",
    "Phonetic",
    "ProviderError",
    "ProviderManifest",
    "ProviderPermission",
    "ProviderState",
    "ProviderStateStore",
    "ProviderStatus",
    "ProviderType",
    "SourceAttribution",
    "Translation",
]
