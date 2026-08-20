"""Data contracts for the MarginNote 4 bridge.

The wire shape is intentionally boring and JSON-first. The add-on owns MN4
native conversion; this service only accepts already-normalized objects with
stable identifiers and monotonic revisions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

MARGINNOTE4_PROTOCOL_VERSION = 1

NOTE = "note"
EXCERPT = "excerpt"
CARD = "card"
MINDMAP_NODE = "mindmap_node"
DOCUMENT = "document"
COMMENT = "comment"

OBJECT_TYPES = frozenset({NOTE, EXCERPT, CARD, MINDMAP_NODE, DOCUMENT, COMMENT})


@dataclass(slots=True)
class MarginNoteObject:
    """One normalized MarginNote 4 object."""

    object_id: str
    object_type: str
    revision: int
    title: str = ""
    content: str = ""
    excerpt: str | None = None
    document_id: str | None = None
    document_title: str | None = None
    page: int | None = None
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    color: str | None = None
    source_locator: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    deleted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PairingSession:
    session_id: str
    user_id: str
    library_id: str
    library_name: str
    status: str
    device_id: str | None
    device_name: str
    device_kind: str
    created_at: str
    updated_at: str
    expires_at: str


@dataclass(slots=True)
class DeviceRecord:
    device_id: str
    user_id: str
    library_id: str
    library_name: str
    device_name: str
    device_kind: str
    status: str
    paired_at: str
    last_seen: str
    revoked_at: str | None = None


@dataclass(slots=True)
class AuthenticatedDevice:
    device_id: str
    user_id: str
    library_id: str
    library_name: str


@dataclass(slots=True)
class PushResult:
    operation_id: str
    cursor: str
    accepted: int
    updated: int
    deleted: int
    ignored_stale: int
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    replayed: bool = False


@dataclass(slots=True)
class PullResult:
    cursor: str
    has_more: bool
    changes: list[dict[str, Any]]


__all__ = [
    "MARGINNOTE4_PROTOCOL_VERSION",
    "AuthenticatedDevice",
    "CARD",
    "COMMENT",
    "DOCUMENT",
    "DeviceRecord",
    "EXCERPT",
    "MINDMAP_NODE",
    "MarginNoteObject",
    "NOTE",
    "OBJECT_TYPES",
    "PairingSession",
    "PullResult",
    "PushResult",
]
