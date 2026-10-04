"""``arxiv_import`` — arXiv preprint search and knowledge-base import."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from deeptutor.agents._shared.tool_composition import (
    AUTO_MOUNTED_TOOLS,
    ToolMountFlags,
    compose_enabled_tools,
)
from deeptutor.tools import arxiv_import as arxiv_module
from deeptutor.tools.arxiv_import import (
    ArxivApiClient,
    ArxivImportError,
    import_papers,
)
from deeptutor.tools.builtin import (
    BUILTIN_TOOL_NAMES,
    USER_TOGGLEABLE_TOOL_NAMES,
    ArxivImportTool,
)
from deeptutor.tools.builtin_specs import BUILTIN_TOOL_SPEC_BY_NAME


def _atom_feed(entries: list[dict[str, Any]]) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
    ]
    for entry in entries:
        authors = "".join(
            f"<author><name>{entry['authors'][index]}</name></author>"
            for index in range(len(entry["authors"]))
        )
        parts.append(
            "<entry>"
            f"<title>{entry['title']}</title>"
            f"<summary>{entry.get('abstract', '')}</summary>"
            f"<published>{entry['published']}</published>"
            f"{authors}"
            f"<id>{entry['entry_id']}</id>"
            f'<link href="{entry.get("link", "")}" rel="alternate" type="text/html"/>'
            "</entry>"
        )
    parts.append("</feed>")
    return "".join(parts)


_PAPER = {
    "title": "Attention Is All You Need",
    "authors": ["Ashish Vaswani", "Noam Shazeer"],
    "abstract": "The dominant sequence transduction models are based on recurrent networks.",
    "published": "2017-06-12T17:57:34Z",
    "entry_id": "http://arxiv.org/abs/1706.03762v1",
    "link": "https://arxiv.org/abs/1706.03762",
}

_RECENT_PAPER = {
    "title": "Graph Retrieval at Scale",
    "authors": ["Ada Lovelace"],
    "abstract": "Retrieval over knowledge graphs.",
    "published": "2026-01-02T00:00:00Z",
    "entry_id": "http://arxiv.org/abs/2601.00002v2",
    "link": "https://arxiv.org/abs/2601.00002",
}

_IMPORT_PAPER = {
    "title": "Attention Is All You Need",
    "authors": ["Ashish Vaswani", "Noam Shazeer"],
    "year": 2017,
    "abstract": "The dominant sequence transduction models are based on recurrent networks.",
    "url": "https://arxiv.org/abs/1706.03762",
    "arxiv_id": "1706.03762",
    "published": "2017-06-12T17:57:34Z",
}


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", arxiv_module.ARXIV_API_BASE),
                response=httpx.Response(self.status_code),
            )

    @property
    def text(self) -> Any:
        return self.payload


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, *, headers: dict, params: dict) -> FakeResponse:
        self.url = url
        self.headers = headers
        self.params = params
        return self.response


class FailingClient:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def __aenter__(self) -> "FailingClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, *, headers: dict, params: dict) -> FakeResponse:
        raise self.exc


class TestArxivApiClient:
    @pytest.mark.asyncio
    async def test_search_builds_request_and_normalizes_entries(self) -> None:
        client = FakeClient(FakeResponse(_atom_feed([_PAPER])))

        papers = await ArxivApiClient(lambda: client).fetch(query="attention", max_results=3)

        assert client.url == arxiv_module.ARXIV_API_BASE
        assert client.params["search_query"] == "attention"
        assert client.params["max_results"] == "3"
        assert "id_list" not in client.params
        assert "DeepTutor" in client.headers["User-Agent"]
        assert papers == [
            {
                "title": "Attention Is All You Need",
                "authors": ["Ashish Vaswani", "Noam Shazeer"],
                "year": 2017,
                "abstract": (
                    "The dominant sequence transduction models are based on recurrent networks."
                ),
                "url": "https://arxiv.org/abs/1706.03762",
                "arxiv_id": "1706.03762",
                "published": "2017-06-12T17:57:34Z",
            }
        ]

    @pytest.mark.asyncio
    async def test_fetch_by_ids_uses_id_list(self) -> None:
        client = FakeClient(FakeResponse(_atom_feed([_PAPER])))

        await ArxivApiClient(lambda: client).fetch(arxiv_ids=["1706.03762"])

        assert client.params["id_list"] == "1706.03762"
        assert "search_query" not in client.params

    @pytest.mark.asyncio
    async def test_ids_take_precedence_over_query(self) -> None:
        client = FakeClient(FakeResponse(_atom_feed([_PAPER])))

        await ArxivApiClient(lambda: client).fetch(query="attention", arxiv_ids=["1706.03762"])

        assert client.params["id_list"] == "1706.03762"
        assert "search_query" not in client.params

    @pytest.mark.asyncio
    async def test_rate_limit_is_a_typed_error(self) -> None:
        client = FakeClient(FakeResponse("busy", status_code=429))

        with pytest.raises(ArxivImportError, match="rate_limited") as exc_info:
            await ArxivApiClient(lambda: client).fetch(query="attention")

        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_server_error_is_a_typed_error(self) -> None:
        client = FakeClient(FakeResponse("oops", status_code=500))

        with pytest.raises(ArxivImportError, match="request_failed") as exc_info:
            await ArxivApiClient(lambda: client).fetch(query="attention")

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_timeout_maps_to_network_unavailable(self) -> None:
        client = FailingClient(httpx.ConnectTimeout("timed out"))

        with pytest.raises(ArxivImportError, match="network_unavailable"):
            await ArxivApiClient(lambda: client).fetch(query="attention")

    @pytest.mark.asyncio
    async def test_malformed_payload_maps_to_invalid_response(self) -> None:
        client = FakeClient(FakeResponse("<not-atom-feed"))

        with pytest.raises(ArxivImportError, match="invalid_response"):
            await ArxivApiClient(lambda: client).fetch(query="attention")

    @pytest.mark.asyncio
    async def test_query_or_ids_required(self) -> None:
        with pytest.raises(ValueError, match="query or explicit"):
            await ArxivApiClient(lambda: FakeClient(FakeResponse(""))).fetch()

    @pytest.mark.asyncio
    async def test_years_limit_filters_older_preprints(self) -> None:
        client = FakeClient(FakeResponse(_atom_feed([_PAPER, _RECENT_PAPER])))

        papers = await ArxivApiClient(lambda: client).fetch(query="retrieval", years_limit=3)

        assert [paper["arxiv_id"] for paper in papers] == ["2601.00002"]


class TestImportPapers:
    @pytest.fixture
    def kb_dir(self, tmp_path: Any) -> Any:
        kb = tmp_path / "Course"
        (kb / "raw").mkdir(parents=True)
        return kb

    @pytest.fixture
    def stub_indexer(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        recorded: dict[str, Any] = {"calls": [], "return": 0}

        async def fake_add_documents(kb_name: str, files: list[str], base_dir: str) -> int:
            recorded["calls"].append(
                {"kb_name": kb_name, "files": list(files), "base_dir": base_dir}
            )
            return recorded["return"]

        monkeypatch.setattr("deeptutor.knowledge.add_documents.add_documents", fake_add_documents)
        return recorded

    def _client_returning(self, papers: list[dict[str, Any]]) -> ArxivApiClient:
        class FakeSearchClient(ArxivApiClient):
            def __init__(self, results: list[dict[str, Any]]) -> None:
                super().__init__()
                self.results = results

            async def fetch(self, **kwargs: Any) -> list[dict[str, Any]]:
                self.kwargs = kwargs
                return list(self.results)

        return FakeSearchClient(papers)

    @pytest.mark.asyncio
    async def test_stages_markdown_and_indexes_through_add_documents(
        self, kb_dir: Any, stub_indexer: dict[str, Any]
    ) -> None:
        stub_indexer["return"] = 1
        client = self._client_returning([_IMPORT_PAPER])

        result = await import_papers(
            kb_name="Course",
            base_dir=str(kb_dir.parent),
            query="attention",
            client=client,
        )

        source_file = kb_dir / "raw" / "_arxiv" / "1706.03762.md"
        assert source_file.is_file()
        stored = source_file.read_text(encoding="utf-8")
        assert "# Attention Is All You Need" in stored
        assert "Ashish Vaswani, Noam Shazeer" in stored
        assert "2017" in stored
        assert "https://arxiv.org/abs/1706.03762" in stored
        assert "## Abstract" in stored

        assert len(stub_indexer["calls"]) == 1
        call = stub_indexer["calls"][0]
        assert call["kb_name"] == "Course"
        assert call["base_dir"] == str(kb_dir.parent)
        assert call["files"] == [str(source_file)]

        assert result["metadata"]["status"] == "imported"
        assert result["metadata"]["indexed_count"] == 1
        assert result["metadata"]["papers"][0]["source_file"] == "raw/_arxiv/1706.03762.md"
        assert result["sources"][0]["type"] == "paper"
        assert result["sources"][0]["provider"] == "arxiv"
        assert result["sources"][0]["arxiv_id"] == "1706.03762"
        assert result["sources"][0]["authors"] == ["Ashish Vaswani", "Noam Shazeer"]
        assert result["sources"][0]["year"] == 2017
        assert result["sources"][0]["kb_name"] == "Course"
        assert "Imported 1 arXiv preprint(s) into `Course`" in result["content"]

    @pytest.mark.asyncio
    async def test_already_indexed_entries_are_reported(
        self, kb_dir: Any, stub_indexer: dict[str, Any]
    ) -> None:
        stub_indexer["return"] = 0

        result = await import_papers(
            kb_name="Course",
            base_dir=str(kb_dir.parent),
            arxiv_ids=["1706.03762"],
            client=self._client_returning([_IMPORT_PAPER]),
        )

        assert result["metadata"]["status"] == "already_indexed"
        assert "already indexed" in result["content"]

    @pytest.mark.asyncio
    async def test_no_matches_is_not_an_error(
        self, kb_dir: Any, stub_indexer: dict[str, Any]
    ) -> None:
        result = await import_papers(
            kb_name="Course",
            base_dir=str(kb_dir.parent),
            query="nothing",
            client=self._client_returning([]),
        )

        assert result["metadata"]["status"] == "papers_not_found"
        assert result["sources"] == []
        assert stub_indexer["calls"] == []

    @pytest.mark.asyncio
    async def test_duplicate_ids_are_deduplicated(
        self, kb_dir: Any, stub_indexer: dict[str, Any]
    ) -> None:
        stub_indexer["return"] = 1

        result = await import_papers(
            kb_name="Course",
            base_dir=str(kb_dir.parent),
            query="attention",
            client=self._client_returning([_IMPORT_PAPER, _IMPORT_PAPER]),
        )

        assert len(result["metadata"]["papers"]) == 1
        assert len(stub_indexer["calls"][0]["files"]) == 1

    @pytest.mark.asyncio
    async def test_missing_kb_directory_fails(self, tmp_path: Any) -> None:
        with pytest.raises(ArxivImportError, match="kb_not_found"):
            await import_papers(
                kb_name="Ghost",
                base_dir=str(tmp_path),
                query="attention",
                client=self._client_returning([]),
            )

    @pytest.mark.asyncio
    async def test_indexing_failure_is_a_typed_error(
        self, kb_dir: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def failing_add_documents(*args: Any, **kwargs: Any) -> int:
            raise RuntimeError("index unavailable")

        monkeypatch.setattr(
            "deeptutor.knowledge.add_documents.add_documents", failing_add_documents
        )

        with pytest.raises(ArxivImportError, match="import_failed"):
            await import_papers(
                kb_name="Course",
                base_dir=str(kb_dir.parent),
                query="attention",
                client=self._client_returning([_IMPORT_PAPER]),
            )


class _EmptyRegistry:
    @staticmethod
    def get_enabled(_selected: list[str]) -> list[Any]:
        return []


class TestRegistration:
    def test_tool_is_registered(self) -> None:
        definition = ArxivImportTool().get_definition()
        parameters = {parameter.name: parameter for parameter in definition.parameters}

        assert definition.name == "arxiv_import"
        assert definition.name in BUILTIN_TOOL_NAMES
        assert (
            BUILTIN_TOOL_SPEC_BY_NAME["arxiv_import"].class_path
            == "deeptutor.tools.builtin:ArxivImportTool"
        )
        assert parameters["kb_name"].required is True
        assert parameters["query"].required is False
        assert parameters["arxiv_ids"].type == "array"
        assert parameters["max_results"].default == 3
        assert parameters["years_limit"].required is False

    def test_mounting_is_kb_owned_not_a_user_toggle(self) -> None:
        assert "arxiv_import" in AUTO_MOUNTED_TOOLS
        assert "arxiv_import" not in USER_TOGGLEABLE_TOOL_NAMES
        assert "arxiv_import" not in compose_enabled_tools(
            registry=_EmptyRegistry(),
            requested_tools=[],
            optional_whitelist=["arxiv_import"],
            mount_flags=ToolMountFlags(has_kb=False),
        )

    def test_mounts_with_the_same_gate_as_rag(self) -> None:
        tools = compose_enabled_tools(
            registry=_EmptyRegistry(),
            requested_tools=[],
            optional_whitelist=[],
            mount_flags=ToolMountFlags(has_kb=True),
        )
        assert {"rag", "kb_files", "knowledge_frontier", "arxiv_import"} <= set(tools)


class TestExecute:
    def _stub_kb(
        self, monkeypatch: pytest.MonkeyPatch, *, read_only: bool = False
    ) -> SimpleNamespace:
        resource = SimpleNamespace(
            name="Course", base_dir=Path("data/knowledge_bases"), read_only=read_only
        )
        monkeypatch.setattr(
            "deeptutor.multi_user.knowledge_access.resolve_kb",
            lambda kb_name, **kwargs: resource,
            raising=False,
        )
        return resource

    def _stub_import(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        captured: dict[str, Any] = {}

        async def fake_import_papers(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            paper = {
                "title": "Attention Is All You Need",
                "authors": ["Ashish Vaswani"],
                "year": 2017,
                "abstract": "Sequence transduction.",
                "url": "https://arxiv.org/abs/1706.03762",
                "arxiv_id": "1706.03762",
                "source_file": "raw/_arxiv/1706.03762.md",
            }
            return {
                "content": "**Imported 1 arXiv preprint(s) into `Course`**",
                "metadata": {
                    "provider": "arxiv",
                    "kb_name": kwargs["kb_name"],
                    "status": "imported",
                    "staged_count": 1,
                    "indexed_count": 1,
                    "papers": [paper],
                },
                "sources": [
                    {
                        "type": "paper",
                        "provider": "arxiv",
                        "url": paper["url"],
                        "title": paper["title"],
                        "arxiv_id": paper["arxiv_id"],
                        "authors": paper["authors"],
                        "year": paper["year"],
                        "kb_name": kwargs["kb_name"],
                        "source_file": paper["source_file"],
                    }
                ],
            }

        monkeypatch.setattr(arxiv_module, "import_papers", fake_import_papers)
        return captured

    @pytest.mark.asyncio
    async def test_imports_into_resolved_kb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resource = self._stub_kb(monkeypatch)
        captured = self._stub_import(monkeypatch)

        result = await ArxivImportTool().execute(
            kb_name="Course",
            query="attention",
            max_results=2,
        )

        assert result.success
        assert captured["kb_name"] == "Course"
        assert captured["base_dir"] == str(resource.base_dir)
        assert captured["max_results"] == 2
        assert result.sources[0]["provider"] == "arxiv"
        assert result.sources[0]["authors"] == ["Ashish Vaswani"]
        assert result.metadata["kb_name"] == "Course"
        assert "Imported 1 arXiv preprint(s)" in result.content

    @pytest.mark.asyncio
    async def test_requires_kb_name_and_selection(self) -> None:
        missing_kb = await ArxivImportTool().execute(query="attention")
        assert missing_kb.success is False
        assert "kb_name is required" in missing_kb.content

        no_selection = await ArxivImportTool().execute(kb_name="Course")
        assert no_selection.success is False
        assert "query or explicit arxiv_ids" in no_selection.content

    @pytest.mark.asyncio
    async def test_accepts_single_id_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub_kb(monkeypatch)
        captured = self._stub_import(monkeypatch)

        result = await ArxivImportTool().execute(kb_name="Course", arxiv_ids="1706.03762")

        assert result.success
        assert captured["arxiv_ids"] == ["1706.03762"]

    @pytest.mark.asyncio
    async def test_inaccessible_kb_is_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from fastapi import HTTPException

        def deny(kb_name: str, **kwargs: Any) -> None:
            raise HTTPException(status_code=403, detail="forbidden")

        monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_kb", deny, raising=False)

        result = await ArxivImportTool().execute(kb_name="secret", query="attention")

        assert result.success is False
        assert "not accessible" in result.content

    @pytest.mark.asyncio
    async def test_read_only_kb_is_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub_kb(monkeypatch, read_only=True)

        result = await ArxivImportTool().execute(kb_name="shared", query="attention")

        assert result.success is False
        assert "read-only" in result.content

    @pytest.mark.asyncio
    async def test_rate_limit_maps_to_friendly_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_kb(monkeypatch)

        async def rate_limited(**kwargs: Any) -> dict[str, Any]:
            raise ArxivImportError("rate_limited", 429)

        monkeypatch.setattr(arxiv_module, "import_papers", rate_limited)

        result = await ArxivImportTool().execute(kb_name="Course", query="attention")

        assert result.success is False
        assert "rate-limited" in result.content
        assert result.metadata["error"] == "rate_limited"
        assert result.metadata["status_code"] == 429


@pytest.mark.parametrize("language", ["en", "zh"])
def test_arxiv_import_prompt_hints_are_bilingual(language: str) -> None:
    hints = ArxivImportTool().get_prompt_hints(language=language)

    assert "arXiv" in hints.short_description
    assert hints.guideline
    assert hints.input_format
