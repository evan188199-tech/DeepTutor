"""Shared MarginNote models and the adapter contract.

Adapters hide the on-disk format (Markdown/OPML export today, Realm later)
behind one notebook of highlights, notes and mind-map nodes. Tools never
parse files themselves.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any


class AdapterError(Exception):
    """A notebook operation could not be completed."""


@dataclass(slots=True)
class Highlight:
    id: str
    document_id: str
    document_name: str
    text: str
    page: int | None = None
    color: str = ""
    note_id: str = ""
    tags: list[str] = field(default_factory=list)
    section: str = ""
    source_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Note:
    id: str
    document_id: str
    document_name: str
    text: str
    highlight_id: str = ""
    tags: list[str] = field(default_factory=list)
    page: int | None = None
    section: str = ""
    source_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MindMapNode:
    id: str
    title: str
    parent_id: str = ""
    children: list[str] = field(default_factory=list)
    note: str = ""
    highlight_id: str = ""
    document_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DocumentInfo:
    id: str
    name: str
    source_path: str = ""
    highlight_count: int = 0
    note_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Notebook:
    name: str
    root: str
    documents: list[DocumentInfo] = field(default_factory=list)
    highlights: list[Highlight] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    mindmap: list[MindMapNode] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "root": self.root,
            "documents": [item.to_dict() for item in self.documents],
            "highlight_count": len(self.highlights),
            "note_count": len(self.notes),
            "mindmap_nodes": len(self.mindmap),
        }


class MarginNoteAdapter(ABC):
    """Read/write surface every notebook format implements."""

    def __init__(self, notebook_path: str, writeback_path: str = "") -> None:
        self.notebook_path = notebook_path
        self.writeback_path = writeback_path

    @abstractmethod
    def load(self) -> Notebook:
        """Return the current notebook snapshot, refreshing if files changed."""

    @abstractmethod
    def search(self, query: str, *, tag: str = "", limit: int = 20) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def read_item(self, item_id: str) -> dict[str, Any]:
        ...

    @abstractmethod
    def list_documents(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def read_highlights(
        self,
        document_id: str = "",
        *,
        page_from: int | None = None,
        page_to: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def mindmap(self, node_id: str = "", *, depth: int = 3) -> dict[str, Any]:
        ...

    @abstractmethod
    def tags(self, limit: int = 200) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def create_note(
        self,
        rel_path: str,
        content: str,
        frontmatter: dict[str, Any] | None = None,
    ) -> str:
        ...

    @abstractmethod
    def append_note(self, ref: str, content: str) -> str:
        ...

    @abstractmethod
    def create_summary(
        self,
        scope: str,
        analysis: str,
        *,
        frontmatter: dict[str, Any] | None = None,
    ) -> str:
        ...


__all__ = [
    "AdapterError",
    "DocumentInfo",
    "Highlight",
    "MarginNoteAdapter",
    "MindMapNode",
    "Note",
    "Notebook",
]
