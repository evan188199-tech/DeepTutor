"""Probe a MarginNote export folder without registering a knowledge base."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deeptutor.capabilities.marginnote4.data import AdapterError, open_adapter
from deeptutor.capabilities.marginnote4.data.diagnostics import (
    PUBLIC_ADAPTERS,
    WRITE_MODE_IMPORT_QUEUE,
    WRITE_MODE_NONE,
    AdapterCapabilities,
    AdapterDiagnostics,
    display_name_for,
)
from deeptutor.capabilities.marginnote4.official import probe_official_write_interface


def normalize_adapter_name(adapter: str | None) -> str:
    return (adapter or "export").strip().lower() or "export"


def _blocked(
    kind: str, folder: Path, error: str, recover: list[str], status: str = "disconnected"
) -> AdapterDiagnostics:
    return AdapterDiagnostics(
        compatible=False,
        adapter=kind,
        export_format=kind if kind != "export" else "markdown-opml",
        file_count=0,
        document_count=0,
        highlight_count=0,
        note_count=0,
        mindmap_count=0,
        writeback_available=False,
        cursor="",
        content_hash="",
        capabilities=AdapterCapabilities(
            adapter=kind,
            can_read=False,
            can_watch=False,
            official_write=False,
            write_verified=False,
            write_mode=WRITE_MODE_NONE,
            write_block_reason=error,
        ),
        recover_actions=recover,
        status_hint=status,
        notebook_name=display_name_for(str(folder)),
        error=error,
    )


def probe_marginnote(
    notebook_path: str,
    *,
    adapter: str = "export",
    writeback_path: str = "",
) -> dict[str, Any]:
    """Inspect notebook_path and return a browser-safe diagnostic payload."""
    kind = normalize_adapter_name(adapter)
    official = probe_official_write_interface()
    folder = Path(notebook_path).expanduser()

    if kind not in PUBLIC_ADAPTERS:
        diagnostics = _blocked(
            kind,
            folder,
            "adapter='realm' is not available. Use a Markdown/OPML export folder.",
            ["use_export_adapter"],
        )
    elif not folder.exists():
        diagnostics = _blocked(
            kind, folder, f"Folder does not exist: {folder.name}", ["choose_existing_export"]
        )
    elif not folder.is_dir():
        diagnostics = _blocked(kind, folder, "Not a directory.", ["choose_existing_export"])
    else:
        try:
            adapter_obj = open_adapter(str(folder), adapter=kind, writeback_path=writeback_path)
            diagnostics = adapter_obj.diagnose()
        except (AdapterError, OSError) as exc:
            diagnostics = _blocked(kind, folder, str(exc), ["fix_permissions"], status="degraded")

    if official.write_api_verified:
        diagnostics.capabilities.official_write = True
        diagnostics.capabilities.write_verified = True
        diagnostics.capabilities.write_mode = "official"
        diagnostics.capabilities.write_block_reason = ""
    else:
        diagnostics.capabilities.official_write = False
        diagnostics.capabilities.write_verified = False
        if diagnostics.capabilities.write_mode != WRITE_MODE_NONE:
            diagnostics.capabilities.write_mode = WRITE_MODE_IMPORT_QUEUE
        diagnostics.capabilities.write_block_reason = official.block_reason

    payload = diagnostics.to_public_dict()
    payload["official_write"] = official.to_dict()
    return payload


__all__ = ["normalize_adapter_name", "probe_marginnote"]
