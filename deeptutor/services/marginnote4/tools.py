"""Read-only chat tools over a connected MarginNote 4 library.

The runtime injects ``_service``, ``_user_id``, and ``_library_id`` after
server-side KB resolution. Tool callers cannot choose another user or library.
"""

from __future__ import annotations

import json
from typing import Any

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult
from deeptutor.services.marginnote4.models import OBJECT_TYPES
from deeptutor.services.marginnote4.service import MarginNote4Service


def _context(kwargs: dict[str, Any]) -> tuple[MarginNote4Service, str, str] | None:
    service = kwargs.get("_service")
    user_id = str(kwargs.get("_user_id") or "")
    library_id = str(kwargs.get("_library_id") or "")
    if not isinstance(service, MarginNote4Service) or not user_id or not library_id:
        return None
    return service, user_id, library_id


def _ok(payload: Any) -> ToolResult:
    return ToolResult(content=json.dumps(payload, ensure_ascii=False), metadata=payload)


def _unavailable() -> ToolResult:
    return ToolResult(
        content="No MarginNote 4 library is connected to this turn.",
        success=False,
    )


def _limit(value: Any, default: int, maximum: int) -> int:
    try:
        return max(1, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


class _MarginNoteReadTool(BaseTool):
    async def execute(self, **kwargs: Any) -> ToolResult:
        context = _context(kwargs)
        if context is None:
            return _unavailable()
        try:
            return await self._run(context, kwargs)
        except Exception as exc:
            return ToolResult(content=str(exc), success=False)

    async def _run(
        self,
        context: tuple[MarginNote4Service, str, str],
        kwargs: dict[str, Any],
    ) -> ToolResult:
        raise NotImplementedError


class MarginNoteSearchTool(_MarginNoteReadTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="marginnote_search",
            description="Search notes, excerpts, cards, and mind-map nodes in the connected MarginNote 4 library.",
            parameters=[
                ToolParameter(name="query", type="string", description="Text to find."),
                ToolParameter(
                    name="object_type",
                    type="string",
                    description="Optional object type filter.",
                    required=False,
                    enum=sorted(OBJECT_TYPES),
                ),
                ToolParameter(
                    name="limit", type="integer", description="Maximum results.", required=False
                ),
            ],
        )

    async def _run(self, context, kwargs):
        service, user_id, library_id = context
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return ToolResult(
                content="marginnote_search requires a non-empty query.", success=False
            )
        return _ok(
            service.search_objects(
                user_id=user_id,
                library_id=library_id,
                query=query,
                object_type=str(kwargs.get("object_type") or ""),
                limit=_limit(kwargs.get("limit"), 20, 100),
            )
        )


class MarginNoteReadTool(_MarginNoteReadTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="marginnote_read",
            description="Read one synced MarginNote 4 object by stable object ID.",
            parameters=[
                ToolParameter(name="object_id", type="string", description="Stable MN4 object ID.")
            ],
        )

    async def _run(self, context, kwargs):
        service, user_id, library_id = context
        obj = service.get_object(
            user_id=user_id,
            library_id=library_id,
            object_id=str(kwargs.get("object_id") or ""),
        )
        if obj is None:
            return ToolResult(content="MarginNote object not found.", success=False)
        return _ok(obj.to_dict())


class MarginNoteListTool(_MarginNoteReadTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="marginnote_list",
            description="List recent objects in the connected MarginNote 4 library.",
            parameters=[
                ToolParameter(
                    name="object_type",
                    type="string",
                    description="Optional object type filter.",
                    required=False,
                    enum=sorted(OBJECT_TYPES),
                ),
                ToolParameter(
                    name="limit", type="integer", description="Maximum results.", required=False
                ),
            ],
        )

    async def _run(self, context, kwargs):
        service, user_id, library_id = context
        return _ok(
            service.search_objects(
                user_id=user_id,
                library_id=library_id,
                query="",
                object_type=str(kwargs.get("object_type") or ""),
                limit=_limit(kwargs.get("limit"), 50, 200),
            )
        )


class MarginNoteDocumentsTool(_MarginNoteReadTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="marginnote_documents",
            description="List source documents represented in the connected MarginNote 4 library.",
            parameters=[],
        )

    async def _run(self, context):
        service, user_id, library_id = context
        documents = service.list_documents(user_id=user_id, library_id=library_id)
        return _ok({"count": len(documents), "documents": documents})


class MarginNoteLinksTool(_MarginNoteReadTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="marginnote_links",
            description="Read objects linked from one MarginNote 4 object.",
            parameters=[
                ToolParameter(name="object_id", type="string", description="Stable MN4 object ID.")
            ],
        )

    async def _run(self, context, kwargs):
        service, user_id, library_id = context
        links = service.linked_objects(
            user_id=user_id,
            library_id=library_id,
            object_id=str(kwargs.get("object_id") or ""),
        )
        return _ok({"count": len(links), "links": links})


class MarginNoteTagsTool(_MarginNoteReadTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="marginnote_tags",
            description="List tags used in the connected MarginNote 4 library.",
            parameters=[
                ToolParameter(
                    name="limit", type="integer", description="Maximum tags.", required=False
                )
            ],
        )

    async def _run(self, context, kwargs):
        service, user_id, library_id = context
        tags = service.collect_tags(
            user_id=user_id,
            library_id=library_id,
            limit=_limit(kwargs.get("limit"), 100, 500),
        )
        return _ok({"count": len(tags), "tags": tags})


class MarginNoteCardsTool(_MarginNoteReadTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="marginnote_cards",
            description="List cards from the connected MarginNote 4 library.",
            parameters=[
                ToolParameter(
                    name="limit", type="integer", description="Maximum cards.", required=False
                )
            ],
        )

    async def _run(self, context, kwargs):
        service, user_id, library_id = context
        cards = service.search_objects(
            user_id=user_id,
            library_id=library_id,
            query="",
            object_type="card",
            limit=_limit(kwargs.get("limit"), 50, 200),
        )
        return _ok({"count": len(cards), "cards": cards})


MARGINNOTE4_TOOL_TYPES = (
    MarginNoteSearchTool,
    MarginNoteReadTool,
    MarginNoteListTool,
    MarginNoteDocumentsTool,
    MarginNoteLinksTool,
    MarginNoteTagsTool,
    MarginNoteCardsTool,
)

__all__ = ["MARGINNOTE4_TOOL_TYPES"]
