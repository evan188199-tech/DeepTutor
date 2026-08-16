"""Realm-database adapter reserved for a future MarginNote 4 live reader."""

from __future__ import annotations

from typing import Any

from deeptutor.capabilities.marginnote.data.base import AdapterError, MarginNoteAdapter, Notebook


class RealmAdapter(MarginNoteAdapter):
    """v2 stub. Reading MN4's Realm schema needs a live app install."""

    def load(self) -> Notebook:
        raise AdapterError(
            "The Realm adapter is not implemented in v1. Export the notebook "
            "as Markdown/OPML and connect it with adapter='export'."
        )

    def search(self, query: str, *, tag: str = "", limit: int = 20) -> list[dict[str, Any]]:
        self.load()
        return []

    def read_item(self, item_id: str) -> dict[str, Any]:
        self.load()
        return {}

    def list_documents(self) -> list[dict[str, Any]]:
        self.load()
        return []

    def read_highlights(
        self,
        document_id: str = "",
        *,
        page_from: int | None = None,
        page_to: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self.load()
        return []

    def mindmap(self, node_id: str = "", *, depth: int = 3) -> dict[str, Any]:
        self.load()
        return {}

    def tags(self, limit: int = 200) -> list[dict[str, Any]]:
        self.load()
        return []

    def create_note(
        self,
        rel_path: str,
        content: str,
        frontmatter: dict[str, Any] | None = None,
    ) -> str:
        self.load()
        return ""

    def append_note(self, ref: str, content: str) -> str:
        self.load()
        return ""

    def create_summary(
        self,
        scope: str,
        analysis: str,
        *,
        frontmatter: dict[str, Any] | None = None,
    ) -> str:
        self.load()
        return ""


__all__ = ["RealmAdapter"]
