"""arXiv preprint retrieval and knowledge-base import.

Search the arXiv public API (or resolve explicit arXiv IDs), then stage each
preprint's abstract and citation metadata (title, authors, year, link) as a
markdown source inside a knowledge base and index it through the standard
document pipeline. Imported preprints become first-class retrievable sources
for later research workflows.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path
import re
from typing import Any

from defusedxml import ElementTree as DefusedElementTree
import httpx

logger = logging.getLogger(__name__)

ARXIV_API_BASE = "https://export.arxiv.org/api/query"
DEFAULT_MAX_PAPERS = 3
MAX_PAPERS_LIMIT = 10
REQUEST_TIMEOUT_S = httpx.Timeout(15.0, connect=5.0)
USER_AGENT = "DeepTutor/1.0 (+https://hkuds.dev/deeptutor)"

SOURCE_SUBDIR = "_arxiv"
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([^/?#\s]+)")
_VERSION_RE = re.compile(r"v\d+$")
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

ClientFactory = Callable[[], AbstractAsyncContextManager[httpx.AsyncClient]]


class ArxivImportError(Exception):
    """A normalized arXiv import failure with a stable error code."""

    def __init__(self, code: str, status_code: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class ArxivApiClient:
    """Query the arXiv public Atom API and return normalized paper metadata."""

    def __init__(self, client_factory: ClientFactory | None = None) -> None:
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT_S,
                follow_redirects=True,
            )
        )

    async def fetch(
        self,
        *,
        query: str = "",
        arxiv_ids: Sequence[str] = (),
        max_results: int = DEFAULT_MAX_PAPERS,
        years_limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch preprint metadata by keyword query or explicit arXiv IDs.

        ``arxiv_ids`` takes precedence when both are supplied. The arXiv API
        asks clients to wait 3 seconds between requests; one call here is a
        single request, so no client-side delay is applied.
        """
        ids = [str(value).strip() for value in arxiv_ids if str(value).strip()]
        search_query = str(query or "").strip()
        if not ids and not search_query:
            raise ValueError("Provide an arXiv search query or explicit arxiv IDs.")
        try:
            limit = min(max(int(max_results), 1), MAX_PAPERS_LIMIT)
        except (TypeError, ValueError) as exc:
            raise ValueError("max_results must be an integer.") from exc

        params: dict[str, str] = {"start": "0", "max_results": str(limit)}
        if ids:
            params["id_list"] = ",".join(ids)
        else:
            params["search_query"] = search_query

        try:
            async with self._client_factory() as client:
                response = await client.get(
                    ARXIV_API_BASE, headers={"User-Agent": USER_AGENT}, params=params
                )
                response.raise_for_status()
                payload = response.text
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                raise ArxivImportError("rate_limited", status) from exc
            raise ArxivImportError("request_failed", status) from exc
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            logger.info("arXiv request failed: %s", exc.__class__.__name__)
            raise ArxivImportError("network_unavailable") from exc

        papers = self._parse_feed(payload)
        if years_limit is not None:
            papers = _within_years(papers, years_limit)
        return papers[:limit]

    def _parse_feed(self, payload: str) -> list[dict[str, Any]]:
        try:
            root = DefusedElementTree.fromstring(payload)
        except (TypeError, ValueError, SyntaxError) as exc:
            raise ArxivImportError("invalid_response") from exc
        papers: list[dict[str, Any]] = []
        for element in root.findall(f"{_ATOM_NS}entry"):
            paper = _normalize_entry(element)
            if paper is not None:
                papers.append(paper)
        return papers


def _normalize_entry(element: Any) -> dict[str, Any] | None:
    """Normalize one Atom entry, skipping entries without a usable arXiv ID."""
    arxiv_id = _extract_arxiv_id(element.findtext(f"{_ATOM_NS}id") or "")
    url = ""
    for link in element.findall(f"{_ATOM_NS}link"):
        if link.get("rel") in (None, "alternate") and link.get("href"):
            url = str(link.get("href"))
            break
    if not arxiv_id:
        return None
    published = str(element.findtext(f"{_ATOM_NS}published") or "").strip()
    year_match = re.match(r"\d{4}", published)
    return {
        "title": " ".join(str(element.findtext(f"{_ATOM_NS}title") or "").split()),
        "authors": [
            " ".join(str(author.findtext(f"{_ATOM_NS}name") or "").split())
            for author in element.findall(f"{_ATOM_NS}author")
        ],
        "year": int(year_match.group(0)) if year_match else "",
        "abstract": " ".join(str(element.findtext(f"{_ATOM_NS}summary") or "").split()),
        "url": url or f"https://arxiv.org/abs/{arxiv_id}",
        "arxiv_id": arxiv_id,
        "published": published,
    }


def _extract_arxiv_id(entry_id: str) -> str:
    """Extract a version-less arXiv ID from an entry URL, or '' if unusable."""
    match = _ARXIV_URL_RE.search(entry_id)
    if not match:
        return ""
    arxiv_id = _VERSION_RE.sub("", match.group(1))
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", arxiv_id):
        return ""
    return arxiv_id


def _within_years(papers: list[dict[str, Any]], years_limit: int | None) -> list[dict[str, Any]]:
    try:
        limit = max(int(years_limit), 0)
    except (TypeError, ValueError):
        return papers
    current_year = datetime.now().year
    return [
        paper
        for paper in papers
        if str(paper.get("year", "")).isdigit() and (current_year - int(paper["year"])) <= limit
    ]


def _deduplicate(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for paper in papers:
        key = str(paper.get("arxiv_id", "")).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(paper)
    return unique


def _source_filename(paper: dict[str, Any]) -> str:
    arxiv_id = str(paper.get("arxiv_id", "")).strip()
    stem = _SAFE_FILENAME_RE.sub("_", arxiv_id) if arxiv_id else ""
    if not stem:
        digest = hashlib.sha256(str(paper.get("title", "")).encode("utf-8")).hexdigest()[:12]
        stem = f"paper-{digest}"
    return f"{stem}.md"


def _render_source_markdown(paper: dict[str, Any]) -> str:
    """Render one preprint as a self-describing, citation-verifiable source file."""
    authors = ", ".join(str(author) for author in (paper.get("authors") or []))
    imported_at = datetime.now(timezone.utc).date().isoformat()
    lines = [
        f"# {paper.get('title') or 'Untitled'}",
        "",
        f"- Authors: {authors or 'Unknown'}",
        f"- Year: {paper.get('year', '')}",
        f"- arXiv ID: {paper.get('arxiv_id', '')}",
        f"- Source: {paper.get('url', '')}",
        f"- Imported from the arXiv public API on {imported_at}",
        "",
        "## Abstract",
        "",
        str(paper.get("abstract", "") or "(no abstract available)"),
        "",
    ]
    return "\n".join(lines)


async def import_papers(
    *,
    kb_name: str,
    base_dir: str,
    query: str = "",
    arxiv_ids: Sequence[str] = (),
    max_results: int = DEFAULT_MAX_PAPERS,
    years_limit: int | None = None,
    client: ArxivApiClient | None = None,
) -> dict[str, Any]:
    """Fetch arXiv metadata and import each preprint into a knowledge base.

    The caller performs the multi-user KB access check and supplies the
    resolved ``kb_name`` and ``base_dir`` (mirroring ``discover_frontier``).
    Each preprint is staged under ``<kb>/raw/_arxiv/`` as markdown carrying
    its abstract and citation metadata, then indexed through the standard
    ``add_documents`` pipeline so it becomes retrievable and citable.
    """
    from deeptutor.knowledge.add_documents import add_documents

    kb_name = str(kb_name or "").strip()
    if not kb_name:
        raise ValueError("arXiv import requires an explicit kb_name.")
    kb_dir = Path(base_dir) / kb_name
    if not kb_dir.is_dir():
        raise ArxivImportError("kb_not_found")

    papers = await (client or ArxivApiClient()).fetch(
        query=query,
        arxiv_ids=arxiv_ids,
        max_results=max_results,
        years_limit=years_limit,
    )
    papers = _deduplicate(papers)[:MAX_PAPERS_LIMIT]
    if not papers:
        return {
            "content": "No arXiv preprints matched this request; nothing was imported.",
            "metadata": {
                "provider": "arxiv",
                "kb_name": kb_name,
                "status": "papers_not_found",
                "papers": [],
            },
            "sources": [],
        }

    source_dir = kb_dir / "raw" / SOURCE_SUBDIR
    source_dir.mkdir(parents=True, exist_ok=True)
    staged: list[dict[str, Any]] = []
    for paper in papers:
        relative_path = f"raw/{SOURCE_SUBDIR}/{_source_filename(paper)}"
        (kb_dir / relative_path).write_text(_render_source_markdown(paper), encoding="utf-8")
        staged.append({**paper, "source_file": relative_path})

    try:
        indexed_count = await add_documents(
            kb_name,
            [str(kb_dir / item["source_file"]) for item in staged],
            base_dir=base_dir,
        )
    except Exception as exc:
        logger.warning("arXiv import into '%s' failed during indexing: %s", kb_name, exc)
        raise ArxivImportError("import_failed") from exc

    skipped = len(staged) - max(int(indexed_count), 0)
    content = _render_import_report(kb_name=kb_name, papers=staged, skipped=skipped)
    return {
        "content": content,
        "metadata": {
            "provider": "arxiv",
            "kb_name": kb_name,
            "status": "imported" if indexed_count else "already_indexed",
            "staged_count": len(staged),
            "indexed_count": int(indexed_count),
            "papers": staged,
        },
        "sources": [
            {
                "type": "paper",
                "provider": "arxiv",
                "url": paper.get("url", ""),
                "title": paper.get("title", ""),
                "arxiv_id": paper.get("arxiv_id", ""),
                "authors": paper.get("authors", []),
                "year": paper.get("year", ""),
                "kb_name": kb_name,
                "source_file": paper.get("source_file", ""),
            }
            for paper in staged
        ],
    }


def _render_import_report(*, kb_name: str, papers: list[dict[str, Any]], skipped: int) -> str:
    lines = [f"**Imported {len(papers) - skipped} arXiv preprint(s) into `{kb_name}`**", ""]
    for index, paper in enumerate(papers, start=1):
        authors = ", ".join(str(author) for author in (paper.get("authors") or [])[:4])
        lines.extend(
            [
                f"{index}. **{paper.get('title', 'Untitled')}** ({paper.get('year', 'unknown')})",
                f"   Authors: {authors or 'Unknown'}",
                f"   arXiv: {paper.get('arxiv_id', 'unknown')} | URL: {paper.get('url', '')}",
                f"   Stored as: {paper.get('source_file', '')}",
                "",
            ]
        )
    if skipped:
        lines.append(
            f"{skipped} preprint(s) were already indexed with identical content and were not "
            "duplicated."
        )
    lines.append(
        "Each preprint is stored with its abstract and citation metadata "
        "(authors, year, link) and is now searchable through the knowledge base."
    )
    return "\n".join(lines)


__all__ = [
    "ARXIV_API_BASE",
    "ArxivApiClient",
    "ArxivImportError",
    "ClientFactory",
    "import_papers",
]
