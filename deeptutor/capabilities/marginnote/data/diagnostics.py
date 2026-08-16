"""Shared diagnostic models for MarginNote adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

WRITE_MODE_NONE = "none"
WRITE_MODE_IMPORT_QUEUE = "import_queue"
WRITE_MODE_OFFICIAL = "official"

SYNC_STATUSES = (
    "disconnected",
    "probing",
    "syncing",
    "ready",
    "degraded",
    "conflict",
    "requires_user_action",
)

PUBLIC_ADAPTERS = frozenset({"export"})
KNOWN_ADAPTERS = frozenset({"export", "realm"})


@dataclass(slots=True)
class ParseWarning:
    path: str
    code: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AdapterCapabilities:
    adapter: str
    can_read: bool = False
    can_watch: bool = False
    official_write: bool = False
    write_verified: bool = False
    write_mode: str = WRITE_MODE_IMPORT_QUEUE
    write_block_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AdapterDiagnostics:
    compatible: bool
    adapter: str
    export_format: str
    file_count: int
    document_count: int
    highlight_count: int
    note_count: int
    mindmap_count: int
    writeback_available: bool
    cursor: str
    content_hash: str
    capabilities: AdapterCapabilities
    warnings: list[ParseWarning] = field(default_factory=list)
    recover_actions: list[str] = field(default_factory=list)
    status_hint: str = "ready"
    notebook_name: str = ""
    error: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "ok": self.compatible and not self.error,
            "compatible": self.compatible,
            "adapter": self.adapter,
            "export_format": self.export_format,
            "notebook_name": self.notebook_name,
            "file_count": self.file_count,
            "counts": {
                "documents": self.document_count,
                "highlights": self.highlight_count,
                "notes": self.note_count,
                "mindmap_nodes": self.mindmap_count,
            },
            "writeback_available": self.writeback_available,
            "cursor": self.cursor,
            "content_hash": self.content_hash,
            "capabilities": self.capabilities.to_dict(),
            "warnings": [item.to_dict() for item in self.warnings],
            "recover_actions": list(self.recover_actions),
            "status_hint": self.status_hint,
            "error": self.error or None,
        }


def display_name_for(path: str) -> str:
    name = Path(path).expanduser().name
    return name or "notebook"


__all__ = [
    "AdapterCapabilities",
    "AdapterDiagnostics",
    "KNOWN_ADAPTERS",
    "PUBLIC_ADAPTERS",
    "ParseWarning",
    "SYNC_STATUSES",
    "WRITE_MODE_IMPORT_QUEUE",
    "WRITE_MODE_NONE",
    "WRITE_MODE_OFFICIAL",
    "display_name_for",
]
