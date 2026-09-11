"""Public contracts for LinguaWave's media domain.

The models in this module intentionally contain stable identities and metadata
only.  Playback URLs are short lived capabilities and are returned separately
by :class:`PlaybackDescriptor`; they must never be saved in a playlist or
synced to another device.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class MediaType(str, Enum):
    MUSIC = "music"
    PODCAST = "podcast"
    EPISODE = "episode"
    LOCAL = "local"


class PlaylistKind(str, Enum):
    MANUAL = "manual"
    SMART = "smart"
    SYSTEM = "system"
    EXTERNAL_IMPORT = "external_import"


class HomeSectionKind(str, Enum):
    QUICK_START = "quick_start"
    CONTINUE_PLAYING = "continue_playing"
    PLAYLISTS = "playlists"
    SUBSCRIPTION_UPDATES = "subscription_updates"
    RECOMMENDATIONS = "recommendations"
    CONTINUE_LEARNING = "continue_learning"
    OFFLINE = "offline"


class ImportCandidateStatus(str, Enum):
    MATCHED = "matched"
    NEEDS_CONFIRMATION = "needs_confirmation"
    DUPLICATE = "duplicate"
    UNRECOGNIZED = "unrecognized"
    UNSUPPORTED = "unsupported"


class ImportJobStatus(str, Enum):
    PREVIEWED = "previewed"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class MediaItem(BaseModel):
    item_id: str
    canonical_id: str
    media_type: MediaType
    title: str
    creator: str = ""
    collection_title: str = ""
    artwork_url: str = ""
    language: str = ""
    duration_seconds: float = Field(default=0, ge=0)
    published_at: str = ""
    source_url: str = ""
    is_favorite: bool = False
    is_downloaded: bool = False
    playback_position_seconds: float = Field(default=0, ge=0)
    learning_progress: float = Field(default=0, ge=0, le=1)
    added_at: str = ""


class PlaybackDescriptor(BaseModel):
    kind: Literal["audio", "video", "local", "unavailable"] = "unavailable"
    provider: str = ""
    stream_url: str = ""
    expires_at: str = ""
    start_seconds: float = Field(default=0, ge=0)
    supports_video: bool = False
    reason: str = ""


class SmartPlaylistRule(BaseModel):
    media_types: list[MediaType] = Field(default_factory=list)
    playback_state: Literal["any", "unplayed", "in_progress", "played"] = "any"
    downloaded: bool | None = None
    favorite: bool | None = None
    learning_state: Literal["any", "not_started", "in_progress", "complete"] = "any"
    language: str = Field(default="", max_length=32)
    subscribed_only: bool = False
    min_duration_seconds: float | None = Field(default=None, ge=0)
    max_duration_seconds: float | None = Field(default=None, ge=0)
    added_after: str = ""
    published_after: str = ""

    @field_validator("max_duration_seconds")
    @classmethod
    def duration_range_is_possible(cls, value: float | None, info) -> float | None:
        minimum = info.data.get("min_duration_seconds")
        if value is not None and minimum is not None and value < minimum:
            raise ValueError("max_duration_seconds must be at least min_duration_seconds")
        return value


class PlaylistItem(BaseModel):
    item_id: str
    media: MediaItem
    position: int = Field(ge=0)
    added_at: str
    added_from: str = ""
    note: str = ""


class Playlist(BaseModel):
    playlist_id: str
    name: str
    description: str = ""
    kind: PlaylistKind
    pinned: bool = False
    cover_url: str = ""
    rule: SmartPlaylistRule | None = None
    item_count: int = Field(default=0, ge=0)
    created_at: str
    updated_at: str


class PlaylistDetail(Playlist):
    items: list[PlaylistItem] = Field(default_factory=list)


class PlaylistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1_000)
    kind: Literal["manual", "smart"] = "manual"
    pinned: bool = False
    rule: SmartPlaylistRule | None = None

    @field_validator("rule")
    @classmethod
    def smart_playlists_need_a_rule(
        cls, value: SmartPlaylistRule | None, info
    ) -> SmartPlaylistRule | None:
        if info.data.get("kind") == "smart" and value is None:
            return SmartPlaylistRule()
        return value


class PlaylistUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1_000)
    pinned: bool | None = None
    rule: SmartPlaylistRule | None = None


class PlaylistItemsCreate(BaseModel):
    canonical_ids: list[str] = Field(min_length=1, max_length=100)
    added_from: str = Field(default="manual", max_length=64)
    note: str = Field(default="", max_length=500)

    @field_validator("canonical_ids")
    @classmethod
    def canonical_ids_are_unique(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if not normalized:
            raise ValueError("at least one canonical media id is required")
        if len(normalized) != len(set(normalized)):
            raise ValueError("canonical media ids must be unique")
        return normalized


class PlaylistOrder(BaseModel):
    item_ids: list[str] = Field(min_length=1, max_length=500)


class HomeCard(BaseModel):
    card_id: str
    title: str
    subtitle: str = ""
    artwork_url: str = ""
    action: str = "open"
    media: MediaItem | None = None
    playlist: Playlist | None = None
    progress: float | None = Field(default=None, ge=0, le=1)
    reason: str = ""


class HomeSection(BaseModel):
    section_id: str
    kind: HomeSectionKind
    title: str
    display: Literal["hero", "grid", "shelf", "list"]
    cards: list[HomeCard] = Field(default_factory=list)
    cursor: str | None = None


class RecommendationReason(BaseModel):
    code: str
    text: str


class DiscoveryShelf(BaseModel):
    shelf_id: str
    title: str
    category: Literal["recommended", "music", "podcast", "topic"]
    cards: list[HomeCard] = Field(default_factory=list)
    cursor: str | None = None


class ImportCandidate(BaseModel):
    candidate_id: str
    status: ImportCandidateStatus
    source: str
    canonical_id: str = ""
    media_type: MediaType | None = None
    title: str = ""
    creator: str = ""
    detail: str = ""


class ImportPreview(BaseModel):
    preview_token: str
    expires_at: str
    candidates: list[ImportCandidate]
    target_playlist_id: str | None = None
    suggested_playlist_name: str = ""
    item_count: int = Field(ge=0)


class ImportPreviewRequest(BaseModel):
    source: str = Field(default="", max_length=200_000)
    sources: list[str] = Field(default_factory=list, max_length=500)
    target_playlist_id: str | None = None
    playlist_name: str = Field(default="", max_length=120)
    format_hint: str = Field(default="", max_length=32)

    @field_validator("sources")
    @classmethod
    def strip_sources(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value.strip()]

    def raw_inputs(self) -> list[str]:
        values = list(self.sources)
        if self.source.strip():
            values.append(self.source.strip())
        if not values:
            raise ValueError("source or sources is required")
        return values


class ImportApplyRequest(BaseModel):
    preview_token: str = Field(min_length=16, max_length=256)
    selected_candidate_ids: list[str] | None = Field(default=None, max_length=500)
    target_playlist_id: str | None = None
    playlist_name: str = Field(default="", max_length=120)


class ImportJob(BaseModel):
    job_id: str
    status: ImportJobStatus
    preview_token: str
    playlist_id: str | None = None
    imported_item_count: int = Field(default=0, ge=0)
    failed_item_count: int = Field(default=0, ge=0)
    created_at: str
    updated_at: str
    error: str = ""


class SubscriptionRequest(BaseModel):
    title: str = Field(default="", max_length=300)
    source_url: str = Field(default="", max_length=2_048)
    language: str = Field(default="", max_length=32)


class PlaybackProgress(BaseModel):
    position_seconds: float = Field(ge=0)
    duration_seconds: float = Field(default=0, ge=0)
    completed: bool = False


class SourceMappingRequest(BaseModel):
    provider: Literal["invidious", "yattee", "local"]
    source_id: str = Field(min_length=1, max_length=512)
    source_url: str = Field(default="", max_length=2_048)
    confirmed: bool = True


class TimedTextDocument(BaseModel):
    item_id: str
    status: Literal["ready", "unavailable", "queued"]
    language: str = ""
    source: str = ""
    cues: list[dict[str, Any]] = Field(default_factory=list)


class LearningArtifact(BaseModel):
    artifact_id: str
    item_id: str
    segment_id: str
    status: Literal["queued", "ready"]
    completed: bool = False
    note: str = ""


class SyncMutation(BaseModel):
    mutation_id: str = Field(min_length=1, max_length=128)
    entity_type: str = Field(min_length=1, max_length=64)
    entity_id: str = Field(min_length=1, max_length=128)
    operation: Literal["upsert", "delete"]
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: str = ""


class SyncEnvelope(BaseModel):
    cursor: str = ""
    mutations: list[SyncMutation] = Field(default_factory=list, max_length=500)


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scopes: list[str] = Field(min_length=1, max_length=5)


class PublicAccessToken(BaseModel):
    token_id: str
    name: str
    prefix: str
    scopes: list[str]
    created_at: str
    last_used_at: str = ""
