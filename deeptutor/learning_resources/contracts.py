"""Typed contracts for learning-resource lookup providers (#961 slice 1).

Slice 1 ships the dictionary provider type: a validated manifest (type,
version, languages, offline behavior, permissions), a structured lookup
result that Book/Reader UI can render consistently, and a minimal
in-process provider interface. Glossary and external-bridge provider types,
plus CLI commands, are deliberate follow-up slices.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator


class ProviderType(str, Enum):
    """Learning-resource provider types; slice 1 ships the dictionary type."""

    DICTIONARY = "dictionary"


class ProviderPermission(str, Enum):
    """Capabilities a provider may need beyond pure in-process lookups."""

    NETWORK = "network"
    FILESYSTEM = "filesystem"
    AUTHENTICATION = "authentication"


class InvalidProviderManifest(ValueError):
    """Raised when a provider manifest does not satisfy the contract."""


_NAME_PATTERN = r"^[a-z][a-z0-9._-]*$"
_VERSION_PATTERN = r"^\d+\.\d+\.\d+$"
_LANGUAGE_PATTERN = r"^\*$|^[a-z]{2,3}(-[a-z0-9]{2,8})*$"


class ProviderManifest(BaseModel):
    """Static, typed metadata every learning-resource provider must declare."""

    name: Annotated[str, Field(pattern=_NAME_PATTERN)]
    type: ProviderType
    version: Annotated[str, Field(pattern=_VERSION_PATTERN)]
    languages: list[Annotated[str, Field(pattern=_LANGUAGE_PATTERN)]] = Field(min_length=1)
    offline: bool
    permissions: list[ProviderPermission] = Field(default_factory=list)
    description: str = ""

    @model_validator(mode="after")
    def _online_providers_declare_network(self) -> "ProviderManifest":
        if not self.offline and ProviderPermission.NETWORK not in self.permissions:
            raise ValueError("providers with offline=False must declare the 'network' permission")
        return self


class LookupRequest(BaseModel):
    """Bounded lookup context: providers must not receive arbitrary history."""

    term: str
    source_language: str | None = None
    target_language: str | None = None

    @field_validator("term")
    @classmethod
    def _term_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("term must not be blank")
        return stripped


class Definition(BaseModel):
    """A single sense of the looked-up term."""

    text: str
    part_of_speech: str | None = None


class Phonetic(BaseModel):
    """Pronunciation hint, e.g. an IPA transcription."""

    value: str
    notation: str = "IPA"


class Example(BaseModel):
    """Usage sentence with an optional translation."""

    text: str
    translation: str | None = None


class Translation(BaseModel):
    """A translation of the term into one language."""

    text: str
    language: str


class SourceAttribution(BaseModel):
    """Where a lookup answer came from, so UI can credit the provider."""

    provider: str
    entry: str | None = None
    license: str | None = None


class LookupResult(BaseModel):
    """Structured lookup outcome; ``found=False`` marks a lookup miss."""

    term: str
    language: str
    definitions: list[Definition] = Field(default_factory=list)
    phonetics: list[Phonetic] = Field(default_factory=list)
    examples: list[Example] = Field(default_factory=list)
    translations: list[Translation] = Field(default_factory=list)
    source: SourceAttribution
    found: bool = True


class ProviderError(RuntimeError):
    """Provider-side failure; distinguishable from a lookup miss."""

    def __init__(self, message: str, *, reason: str = "unavailable") -> None:
        super().__init__(message)
        self.reason = reason


class LearningResourceProvider(ABC):
    """In-process interface every learning-resource provider implements."""

    @property
    @abstractmethod
    def manifest(self) -> ProviderManifest:
        """The validated manifest describing this provider."""

    @abstractmethod
    def lookup(self, request: LookupRequest) -> LookupResult:
        """Answer one lookup request; raise ProviderError on failure."""


__all__ = [
    "Definition",
    "Example",
    "InvalidProviderManifest",
    "LearningResourceProvider",
    "LookupRequest",
    "LookupResult",
    "Phonetic",
    "ProviderError",
    "ProviderManifest",
    "ProviderPermission",
    "ProviderType",
    "SourceAttribution",
    "Translation",
]
