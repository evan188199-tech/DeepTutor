"""MarginNote tools — the seam between the chat loop and a connected notebook."""

from __future__ import annotations

import json
from typing import Any

from deeptutor.capabilities.marginnote.data import AdapterError, open_adapter
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult

MARGINNOTE_TOOL_NAMES: tuple[str, ...] = (
    "mn_search",
    "mn_read_note",
    "mn_list_documents",
    "mn_read_highlights",
    "mn_mindmap",
    "mn_tags",
    "mn_create_note",
    "mn_append_note",
    "mn_create_summary",
)


def _adapter_from(kwargs: dict[str, Any]):
    path = str(kwargs.get("_notebook_path") or "").strip()
    if not path:
        return None
    return open_adapter(
        path,
        adapter=str(kwargs.get("_adapter") or "export"),
        writeback_path=str(kwargs.get("_writeback_path") or ""),
    )


def _no_notebook_result() -> ToolResult:
    return ToolResult(
        content="No MarginNote notebook is connected on this turn; MarginNote tools are unavailable.",
        success=False,
    )


def _ok(payload: Any) -> ToolResult:
    return ToolResult(content=json.dumps(payload, ensure_ascii=False), success=True)


def _err(message: str) -> ToolResult:
    return ToolResult(content=message, success=False)


def _as_int(value: Any, *, default: int, lo: int, hi: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, number))


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class _MarginNoteTool(BaseTool):
    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            adapter = _adapter_from(kwargs)
        except AdapterError as exc:
            return _err(str(exc))
        if adapter is None:
            return _no_notebook_result()
        try:
            return await self._run(adapter, kwargs)
        except AdapterError as exc:
            return _err(str(exc))

    async def _run(self, adapter: Any, kwargs: dict[str, Any]) -> ToolResult:  # pragma: no cover
        raise NotImplementedError


class MarginNoteSearchTool(_MarginNoteTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mn_search",
            description=(
                "Search MarginNote highlights, notes and mind-map titles for a "
                "keyword. Optionally filter by tag. Use this first to find "
                "what the learner marked, then mn_read_note the promising ids."
            ),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="Text to search for. May be empty if tag is set.",
                    required=False,
                ),
                ToolParameter(
                    name="tag",
                    type="string",
                    description="Optional tag filter (with or without #).",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Max results (default 20).",
                    required=False,
                ),
            ],
        )

    async def _run(self, adapter: Any, kwargs: dict[str, Any]) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        tag = str(kwargs.get("tag") or "").strip()
        if not query and not tag:
            return _err("mn_search needs a non-empty 'query' or 'tag'.")
        limit = _as_int(kwargs.get("limit"), default=20, lo=1, hi=100)
        hits = adapter.search(query, tag=tag, limit=limit)
        return _ok({"query": query, "tag": tag, "count": len(hits), "results": hits})


class MarginNoteReadNoteTool(_MarginNoteTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mn_read_note",
            description=(
                "Read one highlight, handwritten note or mind-map node by id, "
                "plus neighbouring highlights in the same document."
            ),
            parameters=[
                ToolParameter(
                    name="id",
                    type="string",
                    description="Item id returned by mn_search / mn_read_highlights / mn_mindmap.",
                ),
            ],
        )

    async def _run(self, adapter: Any, kwargs: dict[str, Any]) -> ToolResult:
        item_id = str(kwargs.get("id") or "").strip()
        if not item_id:
            return _err("mn_read_note needs an 'id'.")
        return _ok(adapter.read_item(item_id))


class MarginNoteListDocumentsTool(_MarginNoteTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mn_list_documents",
            description=(
                "List documents in the MarginNote notebook with highlight and "
                "note counts. Use to see what the learner has been reading."
            ),
            parameters=[],
        )

    async def _run(self, adapter: Any, kwargs: dict[str, Any]) -> ToolResult:
        documents = adapter.list_documents()
        return _ok({"count": len(documents), "documents": documents})


class MarginNoteReadHighlightsTool(_MarginNoteTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mn_read_highlights",
            description=(
                "Read highlights (and attached notes) for a document, optionally "
                "restricted to a page range."
            ),
            parameters=[
                ToolParameter(
                    name="document",
                    type="string",
                    description="Document id or name. Empty = every document.",
                    required=False,
                ),
                ToolParameter(
                    name="page_from",
                    type="integer",
                    description="Inclusive first page.",
                    required=False,
                ),
                ToolParameter(
                    name="page_to",
                    type="integer",
                    description="Inclusive last page.",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Max highlights (default 100).",
                    required=False,
                ),
            ],
        )

    async def _run(self, adapter: Any, kwargs: dict[str, Any]) -> ToolResult:
        rows = adapter.read_highlights(
            str(kwargs.get("document") or ""),
            page_from=_optional_int(kwargs.get("page_from")),
            page_to=_optional_int(kwargs.get("page_to")),
            limit=_as_int(kwargs.get("limit"), default=100, lo=1, hi=500),
        )
        return _ok({"count": len(rows), "highlights": rows})


class MarginNoteMindMapTool(_MarginNoteTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mn_mindmap",
            description=(
                "Read the mind-map structure. Omit node_id for the top-level "
                "overview; pass a node id to expand that subtree."
            ),
            parameters=[
                ToolParameter(
                    name="node_id",
                    type="string",
                    description="Mind-map node id. Empty = roots.",
                    required=False,
                ),
                ToolParameter(
                    name="depth",
                    type="integer",
                    description="How many levels to expand (default 3).",
                    required=False,
                ),
            ],
        )

    async def _run(self, adapter: Any, kwargs: dict[str, Any]) -> ToolResult:
        return _ok(
            adapter.mindmap(
                str(kwargs.get("node_id") or ""),
                depth=_as_int(kwargs.get("depth"), default=3, lo=0, hi=8),
            )
        )


class MarginNoteTagsTool(_MarginNoteTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mn_tags",
            description="List tags used on highlights and notes, ranked by count.",
            parameters=[
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Max tags (default 200).",
                    required=False,
                ),
            ],
        )

    async def _run(self, adapter: Any, kwargs: dict[str, Any]) -> ToolResult:
        tags = adapter.tags(limit=_as_int(kwargs.get("limit"), default=200, lo=1, hi=500))
        return _ok({"count": len(tags), "tags": tags})


class MarginNoteCreateNoteTool(_MarginNoteTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mn_create_note",
            description=(
                "Create a new Markdown note in the writeback folder "
                "(deeptutor-notes/ by default) for the learner to import into "
                "MarginNote. Refuses to overwrite an existing file."
            ),
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Writeback-relative path, e.g. 'Fourier/recap.md'.",
                ),
                ToolParameter(name="content", type="string", description="Markdown body."),
                ToolParameter(
                    name="document",
                    type="string",
                    description="Optional source document name.",
                    required=False,
                ),
                ToolParameter(
                    name="source_url",
                    type="string",
                    description="Optional future marginnote4:// deep link.",
                    required=False,
                ),
                ToolParameter(
                    name="mastery_path_id",
                    type="string",
                    description="Optional mastery path to stamp on the note.",
                    required=False,
                ),
                ToolParameter(
                    name="knowledge_point_id",
                    type="string",
                    description="Optional knowledge-point id.",
                    required=False,
                ),
            ],
        )

    async def _run(self, adapter: Any, kwargs: dict[str, Any]) -> ToolResult:
        rel = str(kwargs.get("path") or "").strip()
        if not rel:
            return _err("mn_create_note needs a 'path'.")
        frontmatter = _write_frontmatter(kwargs)
        created = adapter.create_note(rel, str(kwargs.get("content") or ""), frontmatter)
        return _ok({"status": "created", "path": created})


class MarginNoteAppendNoteTool(_MarginNoteTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mn_append_note",
            description=(
                "Append text to an existing writeback note (mastery updates, "
                "new error analysis). Does not edit the original MN4 export."
            ),
            parameters=[
                ToolParameter(
                    name="note",
                    type="string",
                    description="Writeback-relative path or note name.",
                ),
                ToolParameter(name="content", type="string", description="Markdown to append."),
            ],
        )

    async def _run(self, adapter: Any, kwargs: dict[str, Any]) -> ToolResult:
        ref = str(kwargs.get("note") or "").strip()
        if not ref:
            return _err("mn_append_note needs a 'note' path.")
        path = adapter.append_note(ref, str(kwargs.get("content") or ""))
        return _ok({"status": "appended", "path": path})


class MarginNoteCreateSummaryTool(_MarginNoteTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mn_create_summary",
            description=(
                "Write a learning summary card for a document or chapter into "
                "the writeback folder. Pulls the attached mastery path when "
                "one is active and stamps it in frontmatter."
            ),
            parameters=[
                ToolParameter(
                    name="scope",
                    type="string",
                    description="Document or chapter name this summary covers.",
                ),
                ToolParameter(
                    name="analysis",
                    type="string",
                    description="Tutor-authored recap, gaps and next steps.",
                ),
                ToolParameter(
                    name="mastery_path_id",
                    type="string",
                    description="Optional mastery path id (injected when active).",
                    required=False,
                ),
                ToolParameter(
                    name="knowledge_point_id",
                    type="string",
                    description="Optional knowledge-point id.",
                    required=False,
                ),
                ToolParameter(
                    name="source_url",
                    type="string",
                    description="Optional future marginnote4:// deep link.",
                    required=False,
                ),
            ],
        )

    async def _run(self, adapter: Any, kwargs: dict[str, Any]) -> ToolResult:
        scope = str(kwargs.get("scope") or "").strip()
        if not scope:
            return _err("mn_create_summary needs a 'scope'.")
        analysis = str(kwargs.get("analysis") or "").strip()
        frontmatter = _write_frontmatter(kwargs)
        frontmatter["document"] = scope
        mastery = _mastery_payload(kwargs)
        if mastery:
            frontmatter["mastery"] = mastery["counts"]
            if analysis:
                analysis = f"{analysis.rstrip()}\n\n## Mastery\n\n{_format_mastery(mastery)}"
            else:
                analysis = f"## Mastery\n\n{_format_mastery(mastery)}"
        path = adapter.create_summary(scope, analysis, frontmatter=frontmatter)
        return _ok({"status": "written", "path": path, "mastery": mastery or None})


def _write_frontmatter(kwargs: dict[str, Any]) -> dict[str, Any]:
    meta: dict[str, Any] = {"source": "marginnote", "created_by": "deeptutor"}
    document = str(kwargs.get("document") or "").strip()
    if document:
        meta["document"] = document
    source_url = str(kwargs.get("source_url") or "").strip()
    meta["source_url"] = source_url
    path_id = str(kwargs.get("mastery_path_id") or kwargs.get("_mastery_path_id") or "").strip()
    if path_id:
        meta["mastery_path_id"] = path_id
    kp_id = str(kwargs.get("knowledge_point_id") or "").strip()
    if kp_id:
        meta["knowledge_point_id"] = kp_id
    return meta


def _mastery_payload(kwargs: dict[str, Any]) -> dict[str, Any] | None:
    path_id = str(kwargs.get("mastery_path_id") or kwargs.get("_mastery_path_id") or "").strip()
    if not path_id:
        return None
    try:
        from deeptutor.learning.policy import map_summary
        from deeptutor.learning.storage import LearningStore

        progress = LearningStore().load(path_id)
    except Exception:
        return None
    if progress is None:
        return None
    summary = map_summary(progress)
    errors = [
        {
            "id": record.id,
            "knowledge_point_id": record.knowledge_point_id,
            "error_type": getattr(record.error_type, "value", record.error_type),
            "status": record.status,
        }
        for record in progress.error_records
        if record.status in {"active", "retrying", "review"}
    ]
    return {
        "path_id": path_id,
        "counts": summary.get("counts", {}),
        "complete": summary.get("complete", False),
        "open_errors": errors[:20],
    }


def _format_mastery(payload: dict[str, Any]) -> str:
    counts = payload.get("counts") or {}
    lines = [
        f"- Path: `{payload.get('path_id', '')}`",
        f"- Mastered: {counts.get('mastered', 0)}/{counts.get('total', 0)}",
        f"- Complete: {bool(payload.get('complete'))}",
    ]
    errors = payload.get("open_errors") or []
    if errors:
        lines.append("- Open errors:")
        for item in errors[:8]:
            lines.append(
                f"  - {item.get('knowledge_point_id')} ({item.get('error_type')}, {item.get('status')})"
            )
    return "\n".join(lines)


MARGINNOTE_TOOL_TYPES: tuple[type[BaseTool], ...] = (
    MarginNoteSearchTool,
    MarginNoteReadNoteTool,
    MarginNoteListDocumentsTool,
    MarginNoteReadHighlightsTool,
    MarginNoteMindMapTool,
    MarginNoteTagsTool,
    MarginNoteCreateNoteTool,
    MarginNoteAppendNoteTool,
    MarginNoteCreateSummaryTool,
)


__all__ = ["MARGINNOTE_TOOL_NAMES", "MARGINNOTE_TOOL_TYPES"]
