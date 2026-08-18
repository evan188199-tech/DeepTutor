"""Resolve which connected MarginNote notebook the current turn targets."""

from __future__ import annotations

from deeptutor.core.context import UnifiedContext
from deeptutor.knowledge.kb_types import MARGINNOTE_KB_TYPE

_CACHE_KEY = "_marginnote_notebook"
_UNSET = object()


def notebook_for_turn(context: UnifiedContext) -> dict[str, str] | None:
    """Return binding dict for the selected MarginNote notebook, or ``None``."""
    cached = context.metadata.get(_CACHE_KEY, _UNSET)
    if cached is not _UNSET:
        return cached or None
    resolved = _resolve(context)
    context.metadata[_CACHE_KEY] = resolved or ""
    return resolved


def _resolve(context: UnifiedContext) -> dict[str, str] | None:
    from deeptutor.multi_user.knowledge_access import resolve_kb_metadata

    for ref in context.knowledge_bases or []:
        ref = str(ref).strip()
        if not ref:
            continue
        meta = resolve_kb_metadata(ref)
        if not meta or meta.get("type") != MARGINNOTE_KB_TYPE:
            continue
        path = str(meta.get("notebook_path") or "").strip()
        if not path:
            continue
        return {
            "name": str(meta.get("name") or ref),
            "path": path,
            "adapter": str(meta.get("adapter") or "export"),
            "writeback_path": str(meta.get("writeback_path") or ""),
        }
    return None


def marginnote_notebook_refs(context: UnifiedContext) -> set[str]:
    """Every selected KB ref that resolves to a connected MarginNote notebook."""
    from deeptutor.multi_user.knowledge_access import resolve_kb_metadata

    refs: set[str] = set()
    for ref in context.knowledge_bases or []:
        ref = str(ref).strip()
        if not ref:
            continue
        meta = resolve_kb_metadata(ref)
        if (
            meta
            and meta.get("type") == MARGINNOTE_KB_TYPE
            and str(meta.get("notebook_path") or "").strip()
        ):
            refs.add(ref)
    return refs


__all__ = ["marginnote_notebook_refs", "notebook_for_turn"]
