"""Core data models for the MarginNote 4 local bridge."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

NOTE = "note"
EXCERPT = "excerpt"
CARD = "card"
MINDMAP_NODE = "mindmap_node"
DOCUMENT = "document"
COMMENT = "comment"
ALL_TYPES = frozenset({NOTE, EXCERPT, CARD, MINDMAP_NODE, DOCUMENT, COMMENT})

WRITEBACK_STATUSES = (
    "pending_confirmation",
    "approved",
    "leased",
    "applied",
    "failed",
    "conflicted",
    "awaiting_import",
    "imported",
    "rejected",
)
DELIVERY_MODES = ("import_queue", "automation")


@dataclass(slots=True)
class MarginNoteObject:
    object_id: str
    object_type: str
    title: str = ""
    content: str = ""
    excerpt: str | None = None
    document_id: str | None = None
    document_title: str | None = None
    page: int | None = None
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    color: str | None = None
    created_at: str = ""
    updated_at: str = ""
    synced_at: str = ""
    object_hash: str = ""
    device_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SyncBatch:
    device_id: str
    sync_id: str = ""
    sequence: int = 0
    final: bool = True
    base_cursor: str = ""
    snapshot_hash: str = ""
    objects: list[MarginNoteObject] = field(default_factory=list)
    deleted_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SyncResult:
    stored: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0
    new_cursor: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PairedDevice:
    device_id: str
    user_id: str = "local-admin"
    kb_id: str = ""
    kb_name: str = ""
    device_name: str = ""
    device_kind: str = "macos"
    paired_at: str = ""
    last_seen: str = ""
    active: bool = True
    automation_verified: bool = False


@dataclass(slots=True)
class PairingCode:
    code: str
    user_id: str
    kb_id: str
    kb_name: str
    expires_at: str


@dataclass(slots=True)
class WritebackPayload:
    title: str
    markdown: str
    tags: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    target_notebook: str = ""

    def canonical(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "markdown": self.markdown,
            "tags": sorted({str(item) for item in self.tags}),
            "source_refs": [str(item) for item in self.source_refs],
            "target_notebook": self.target_notebook,
        }


@dataclass(slots=True)
class WritebackReceipt:
    payload_hash: str
    delivery_mode: str
    provider: str
    result: str
    external_id: str = ""
    written_at: str = ""


__all__ = [
    "ALL_TYPES",
    "CARD",
    "COMMENT",
    "DELIVERY_MODES",
    "DOCUMENT",
    "EXCERPT",
    "LearningEvent",
    "MINDMAP_NODE",
    "NOTE",
    "MarginNoteObject",
    "PairedDevice",
    "PairingCode",
    "SyncBatch",
    "SyncResult",
    "WRITEBACK_STATUSES",
    "WritebackPayload",
    "WritebackReceipt",
]


@dataclass(slots=True)
class LearningEvent:
    event_id: str
    object_id: str
    event_type: str = "review"
    outcome: str = ""
    timestamp: str = ""
    device_id: str = ""
