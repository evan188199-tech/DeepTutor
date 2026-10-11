"""Boundary tests for the PageIndex tool exposure surface.

Covers the source-row normalizer's malformed-payload branches and the SDK tool
wrapper's success/failure classification, all against fake SDK transports.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from deeptutor.services.rag.pipelines.pageindex.storage import OSS_PROVIDER
from deeptutor.services.rag.pipelines.pageindex.tools import (
    PageIndexSDKTool,
    pageindex_sources_from_text,
)


class _SDKTool:
    name = "get_page_content"
    description = "Read pages"
    params_json_schema = {"type": "object", "properties": {}}

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[str] = []

    async def on_invoke_tool(self, _context: Any, args_json: str) -> str:
        self.calls.append(args_json)
        return self._response


def _page_response(content: list[dict[str, Any]]) -> str:
    return json.dumps({"success": True, "doc_name": "manual.pdf", "content": content})


# --------------------------------------------------- source normalization --
@pytest.mark.parametrize("text", [None, "", "not-json", "[1, 2]", "42"])
def test_non_page_payloads_yield_no_sources(text: Any) -> None:
    assert pageindex_sources_from_text(text, provider=OSS_PROVIDER) == []


@pytest.mark.parametrize(
    "payload",
    [
        {"success": False, "doc_name": "m.pdf", "content": [{"page": 1}]},
        {"errorCode": "E1", "doc_name": "m.pdf", "content": [{"page": 1}]},
        {"success": True},
        {"success": True, "doc_name": " "},
        {"success": True, "doc_name": "m.pdf"},
        {"success": True, "doc_name": "m.pdf", "content": "not-a-list"},
    ],
)
def test_error_and_malformed_payloads_yield_no_sources(payload: dict[str, Any]) -> None:
    assert pageindex_sources_from_text(json.dumps(payload), provider=OSS_PROVIDER) == []


def test_blank_pages_and_duplicate_blocks_are_deduped() -> None:
    text = json.dumps(
        {
            "success": True,
            "doc_name": "manual.pdf",
            "content": [
                {"page": None},
                {"page": ""},
                {"page": 3, "block_id": "b1"},
                {"page": "3", "block_id": "b1"},
                {"page": 4},
                {"page": 4, "block_id": "x"},
                "not-a-dict",
            ],
        }
    )

    rows = pageindex_sources_from_text(
        text, provider="pageindex", kb_name="kb", doc_ids={"manual.pdf": "c-1"}
    )

    assert [(row["page"], row.get("block_id")) for row in rows] == [
        (3, "b1"),
        (4, None),
        (4, "x"),
    ]
    assert all(row["type"] == "pageindex" for row in rows)
    assert all(row["provider"] == "pageindex" for row in rows)
    assert all(row["document_name"] == row["source"] == "manual.pdf" for row in rows)
    assert all(row["kb_name"] == "kb" for row in rows)
    assert all(row["doc_id"] == "c-1" for row in rows)


def test_optional_fields_are_omitted_when_absent() -> None:
    rows = pageindex_sources_from_text(
        _page_response([{"page": 2}]), provider=OSS_PROVIDER
    )

    assert rows == [
        {
            "type": "pageindex",
            "provider": OSS_PROVIDER,
            "document_name": "manual.pdf",
            "source": "manual.pdf",
            "page": 2,
        }
    ]


# ------------------------------------------------------- SDK tool wrapper --
def test_failed_sdk_payload_marks_tool_failure() -> None:
    sdk = _SDKTool(json.dumps({"success": False, "error": "not found"}))
    tool = PageIndexSDKTool(sdk, provider=OSS_PROVIDER, kb_name="kb", doc_ids={})

    result = asyncio.run(tool.execute(doc_name="m.pdf"))

    assert result.success is False
    assert result.sources == []
    assert json.loads(result.content)["error"] == "not found"


def test_error_code_payload_marks_tool_failure() -> None:
    sdk = _SDKTool(json.dumps({"errorCode": "boom", "doc_name": "m.pdf"}))
    tool = PageIndexSDKTool(sdk, provider=OSS_PROVIDER, kb_name="kb", doc_ids={})

    assert asyncio.run(tool.execute(doc_name="m.pdf")).success is False


def test_non_json_sdk_text_counts_as_success_without_sources() -> None:
    sdk = _SDKTool("plain prose")
    tool = PageIndexSDKTool(sdk, provider=OSS_PROVIDER, kb_name="kb", doc_ids={})

    result = asyncio.run(tool.execute(doc_name="m.pdf"))

    assert result.success is True
    assert result.sources == []
    assert result.content == "plain prose"


def test_event_sink_is_not_forwarded_to_the_sdk() -> None:
    sdk = _SDKTool(_page_response([{"page": 3}]))
    tool = PageIndexSDKTool(sdk, provider=OSS_PROVIDER, kb_name="kb", doc_ids={})

    result = asyncio.run(tool.execute(doc_name="m.pdf", event_sink=object()))

    assert sdk.calls == [json.dumps({"doc_name": "m.pdf"}, ensure_ascii=False)]
    assert result.success is True
    assert result.metadata["pageindex_provider"] == OSS_PROVIDER
    assert result.metadata["kb_name"] == "kb"
