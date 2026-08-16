"""MarginNote notebook adapters."""

from __future__ import annotations

from deeptutor.capabilities.marginnote.data.base import AdapterError, MarginNoteAdapter
from deeptutor.capabilities.marginnote.data.export_adapter import ExportAdapter
from deeptutor.capabilities.marginnote.data.realm_adapter import RealmAdapter

SUPPORTED_ADAPTERS = ("export", "realm")


def open_adapter(
    notebook_path: str,
    adapter: str = "export",
    writeback_path: str = "",
) -> MarginNoteAdapter:
    """Build the adapter named by the KB metadata."""
    kind = (adapter or "export").strip().lower() or "export"
    if kind == "realm":
        return RealmAdapter(notebook_path, writeback_path)
    if kind != "export":
        raise AdapterError(f"Unknown MarginNote adapter: {adapter!r}")
    return ExportAdapter(notebook_path, writeback_path)


__all__ = [
    "AdapterError",
    "ExportAdapter",
    "MarginNoteAdapter",
    "RealmAdapter",
    "SUPPORTED_ADAPTERS",
    "open_adapter",
]
