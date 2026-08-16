"""Realm-database adapter reserved for a future MarginNote 4 live reader."""

from __future__ import annotations

from typing import Any

from deeptutor.capabilities.marginnote.data.base import AdapterError, MarginNoteAdapter, Notebook
from deeptutor.capabilities.marginnote.data.diagnostics import (
    WRITE_MODE_NONE,
    AdapterCapabilities,
    AdapterDiagnostics,
    display_name_for,
)

_REALM_BLOCKED = (
    "The Realm adapter is not implemented and is blocked from public use. "
    "Export the notebook as Markdown/OPML and connect it with adapter='export'."
)


class RealmAdapter(MarginNoteAdapter):
    """v2 stub. Reading MN4's Realm schema needs a live app install."""

    adapter_name = "realm"

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            adapter="realm",
            can_read=False,
            can_watch=False,
            official_write=False,
            write_verified=False,
            write_mode=WRITE_MODE_NONE,
            write_block_reason=_REALM_BLOCKED,
        )

    def diagnose(self) -> AdapterDiagnostics:
        return AdapterDiagnostics(
            compatible=False,
            adapter="realm",
            export_format="realm",
            file_count=0,
            document_count=0,
            highlight_count=0,
            note_count=0,
            mindmap_count=0,
            writeback_available=False,
            cursor="",
            content_hash="",
            capabilities=self.capabilities(),
            recover_actions=["use_export_adapter"],
            status_hint="disconnected",
            notebook_name=display_name_for(self.notebook_path),
            error=_REALM_BLOCKED,
        )

    def load(self) -> Notebook:
        raise AdapterError(_REALM_BLOCKED)

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
