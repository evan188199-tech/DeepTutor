"""Primitive contracts for bounded research evidence: parsing, budgets, degradation."""

from __future__ import annotations

import hashlib

import fitz
import httpx
import pytest

import deeptutor.services.research.primitives as primitives
from deeptutor.services.research.primitives import (
    ResearchClient,
    ResearchError,
    arxiv_id,
    audit_checks,
    choose_files,
    literature,
    parse_feed,
    read_pdf,
    repository,
    source_path,
)

_ATOM_NS = 'xmlns="http://www.w3.org/2005/Atom"'


def _entry(identifier: str, title: str = "A paper") -> str:
    return (
        f"<entry><id>https://arxiv.org/abs/{identifier}</id>"
        f"<title>  {title}  </title>"
        f"<summary>  multi word   abstract </summary>"
        f"<author><name>Ada Lovelace</name></author>"
        f"<published>2024-01-01</published><updated>2024-01-02</updated></entry>"
    )


def _feed(*entries: str) -> bytes:
    return f'<feed {_ATOM_NS}>{"".join(entries)}</feed>'.encode()


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(primitives, "ARXIV_INTERVAL", 0)
    monkeypatch.setattr(primitives, "_NEXT_API", 0)

    async def allowed(*args, **kwargs):
        return True, ""

    monkeypatch.setattr(primitives, "validate_mcp_url_async", allowed)


def _client(handler, **kwargs) -> ResearchClient:
    return ResearchClient(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        **kwargs,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1706.03762", "1706.03762"),
        ("  2401.00001v2  ", "2401.00001v2"),
        ("arXiv: 1706.03762", "1706.03762"),
        ("hep-th/9901001", "hep-th/9901001"),
        ("1706.03762.pdf", "1706.03762"),
        ("https://arxiv.org/abs/1706.03762v3", "1706.03762v3"),
        ("https://www.alphaxiv.org/pdf/1706.03762v2", "1706.03762v2"),
    ],
)
def test_arxiv_id_accepts_canonical_forms(value, expected):
    assert arxiv_id(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-paper",
        "1706.037",
        "1706.037622",
        "1706.03762v0",
        "https://arxiv.org/abs/1706.03762?token=x",
        "https://user:pw@arxiv.org/abs/1706.03762",
        "ftp://arxiv.org/abs/1706.03762",
        "https://arxiv.org.evil.test/abs/1706.03762",
        "https://arxiv.org/list/1706.03762",
    ],
)
def test_arxiv_id_rejects_noncanonical_input(value):
    with pytest.raises(ResearchError):
        arxiv_id(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://github.com/owner/repo", ("owner", "repo")),
        ("https://github.com/owner/repo.git", ("owner", "repo")),
        ("https://github.com/Owner-1/repo.name", ("Owner-1", "repo.name")),
    ],
)
def test_repository_parses_owner_and_name(value, expected):
    assert repository(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "http://github.com/owner/repo",
        "https://gitlab.com/owner/repo",
        "https://github.com/owner",
        "https://github.com/owner/repo/tree/main",
        "https://github.com/owner/repo?tab=readme",
        "https://github.com/owner/repo#readme",
        "https://user:pw@github.com/owner/repo",
        "https://github.com/" + "o" * 40 + "/repo",
        "https://github.com/owner/..",
    ],
)
def test_repository_rejects_non_github_or_malformed_urls(value):
    with pytest.raises(ResearchError):
        repository(value)


def test_source_path_normalizes_relative_paths():
    assert source_path("src/model.py") == "src/model.py"
    assert source_path("./nested/x.py") == "nested/x.py"
    assert source_path("a" * 300) == "a" * 300


@pytest.mark.parametrize(
    "value",
    ["", "/abs/x.py", "../up.py", "a/b/../c.py", "win\\path.py", "a" * 301],
)
def test_source_path_rejects_unbounded_paths(value):
    with pytest.raises(ResearchError):
        source_path(value)


def test_parse_feed_extracts_entries_with_normalized_fields():
    rows = parse_feed(_feed(_entry("2401.00001v1"), _entry("hep-th/9901001")))
    assert [row["arxiv_id"] for row in rows] == ["2401.00001v1", "hep-th/9901001"]
    assert rows[0]["title"] == "A paper"
    assert rows[0]["abstract"] == "multi word abstract"
    assert rows[0]["authors"] == ["Ada Lovelace"]
    assert rows[0]["published"] == "2024-01-01"
    assert rows[0]["updated"] == "2024-01-02"
    assert rows[0]["url"] == "https://arxiv.org/abs/2401.00001v1"
    assert rows[0]["pdf_url"] == "https://arxiv.org/pdf/2401.00001v1"
    assert rows[0]["evidence_level"] == "primary_abstract"


def test_parse_feed_rejects_non_atom_and_damaged_xml():
    with pytest.raises(ResearchError, match="Atom"):
        parse_feed(b'<rss version="2.0"><channel/></rss>')
    with pytest.raises(ResearchError, match="Atom"):
        parse_feed(f"<feed {_ATOM_NS}><entry>".encode())
    with pytest.raises(ResearchError):
        parse_feed(_feed(_entry("banana")))


def test_parse_feed_caps_results_at_eight_entries():
    rows = parse_feed(_feed(*(_entry(f"2401.{index:05d}") for index in range(1, 11))))
    assert [row["arxiv_id"] for row in rows] == [f"2401.{index:05d}" for index in range(1, 9)]


@pytest.mark.asyncio
async def test_fetch_rejects_non_primary_hosts_and_embedded_credentials(offline):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=b"data")

    client = _client(handler)
    with pytest.raises(ResearchError, match="primary-source hosts"):
        await client.fetch("https://example.com/data", limit=100)
    with pytest.raises(ResearchError, match="primary-source hosts"):
        await client.fetch("https://user:pw@arxiv.org/pdf/1706.03762", limit=100)
    assert calls == []


@pytest.mark.asyncio
async def test_fetch_enforces_byte_budget(offline):
    def handler(request):
        return httpx.Response(200, content=b"x" * 1001)

    client = _client(handler)
    with pytest.raises(ResearchError, match="byte budget"):
        await client.fetch("https://arxiv.org/pdf/1706.03762", limit=1000)
    assert await client.fetch("https://arxiv.org/pdf/1706.03762", limit=1001) == b"x" * 1001


@pytest.mark.asyncio
async def test_fetch_reports_http_status_as_failure(offline):
    client = _client(lambda request: httpx.Response(404))
    with pytest.raises(ResearchError, match="HTTP 404"):
        await client.fetch("https://arxiv.org/pdf/missing", limit=100)


@pytest.mark.asyncio
async def test_fetch_follows_same_scope_redirects_and_stops_at_budget(offline):
    calls = []

    def redirect_handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "/pdf/again"})

    client = _client(redirect_handler)
    with pytest.raises(ResearchError, match="redirect budget"):
        await client.fetch("https://arxiv.org/pdf/1706.03762", limit=100)
    assert len(calls) == 4

    hops = []

    def one_hop_handler(request):
        hops.append(str(request.url))
        if len(hops) == 1:
            return httpx.Response(302, headers={"location": "/abs/1706.03762v3"})
        return httpx.Response(200, content=b"final")

    client = _client(one_hop_handler)
    assert await client.fetch("https://arxiv.org/pdf/1706.03762", limit=100) == b"final"
    assert len(hops) == 2


@pytest.mark.asyncio
async def test_search_validates_query_and_limit_bounds(offline):
    client = _client(lambda request: httpx.Response(200, content=_feed()))
    for query, limit in [("", 6), (" ", 6), ("x" * 1001, 6), ("attention", 0), ("attention", 9)]:
        with pytest.raises(ResearchError, match="nonempty query"):
            await client.search(query, limit=limit)


@pytest.mark.asyncio
async def test_search_quotes_query_and_parses_feed(offline):
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, content=_feed(_entry("2401.00001")))

    client = _client(handler)
    rows = await client.search("attention is all", limit=8)
    assert "search_query=" in requested[0]
    assert "attention%20is%20all" in requested[0]
    assert "max_results=8" in requested[0]
    assert "sortBy=relevance" in requested[0]
    assert [row["arxiv_id"] for row in rows] == ["2401.00001"]


@pytest.mark.asyncio
async def test_paper_rejects_identifier_before_any_request(offline):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=_feed(_entry("2401.00001")))

    client = _client(handler)
    with pytest.raises(ResearchError):
        await client.paper("not-a-paper")
    assert calls == []


@pytest.mark.asyncio
async def test_paper_rejects_foreign_or_stale_versions(offline):
    def handler(request):
        return httpx.Response(200, content=_feed(_entry("2401.00001v1")))

    client = _client(handler)
    with pytest.raises(ResearchError, match="not returned"):
        await client.paper("1706.03762")
    with pytest.raises(ResearchError, match="version"):
        await client.paper("2401.00001v2")


@pytest.mark.asyncio
async def test_paper_accepts_versioned_and_unversioned_matches(offline):
    def handler(request):
        return httpx.Response(200, content=_feed(_entry("2401.00001v3")))

    client = _client(handler)
    assert (await client.paper("2401.00001"))["arxiv_id"] == "2401.00001v3"
    assert (await client.paper("2401.00001v3"))["arxiv_id"] == "2401.00001v3"


@pytest.mark.asyncio
async def test_paper_rejects_ambiguous_multi_entry_responses(offline):
    feed = _feed(_entry("2401.00001v1"), _entry("2401.00002v1"))
    client = _client(lambda request: httpx.Response(200, content=feed))
    with pytest.raises(ResearchError, match="not returned"):
        await client.paper("2401.00001")


@pytest.mark.asyncio
async def test_code_reads_selected_files_and_degrades_for_missing_or_binary(offline):
    tree = [
        {"type": "blob", "mode": "100644", "path": "model.py"},
        {"type": "blob", "mode": "100644", "path": "big.py"},
        {"type": "blob", "mode": "100644", "path": "binary.py"},
        {"type": "blob", "mode": "120000", "path": "link.py"},
        {"type": "tree", "mode": "040000", "path": "src"},
    ]
    payloads = {
        "model.py": b"dropout = 0.2\n",
        "big.py": b"a" * 30000,
        "binary.py": b"\xff\xfe\xfa",
    }

    def handler(request):
        if "/commits/" in request.url.path:
            return httpx.Response(200, json={"sha": "a" * 40})
        if "/git/trees/" in request.url.path:
            return httpx.Response(200, json={"tree": tree, "truncated": True})
        for name, payload in payloads.items():
            if request.url.path.endswith("/contents/" + name):
                return httpx.Response(200, content=payload)
        return httpx.Response(404)

    client = _client(handler)
    result = await client.code(
        "https://github.com/owner/repo",
        files=["model.py", "big.py", "binary.py", "missing.py", "link.py"],
    )
    statuses = {row["path"]: row["status"] for row in result["files"]}
    assert statuses == {
        "model.py": "read",
        "big.py": "read",
        "binary.py": "unverified",
        "missing.py": "unavailable",
        "link.py": "unavailable",
    }
    model_row = result["files"][0]
    assert model_row["truncated"] is False
    assert model_row["sha256"] == hashlib.sha256(payloads["model.py"]).hexdigest()
    assert model_row["url"] == "https://github.com/owner/repo/blob/" + "a" * 40 + "/model.py"
    big_row = result["files"][1]
    assert big_row["truncated"] is True
    assert len(big_row["text"]) == 24000
    assert result["commit"] == "a" * 40
    assert result["requested_ref"] == "HEAD"
    assert result["tree_truncated"] is True
    assert result["execution"] == "not_run"


@pytest.mark.asyncio
async def test_code_rejects_invalid_ref_before_any_request(offline):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"sha": "a" * 40})

    client = _client(handler)
    with pytest.raises(ResearchError, match="revision"):
        await client.code("https://github.com/owner/repo", ref="HEAD; extra")
    assert calls == []


@pytest.mark.asyncio
async def test_code_rejects_non_immutable_commit_identity(offline):
    def handler(request):
        if "/commits/" in request.url.path:
            return httpx.Response(200, json={"sha": "short-sha"})
        return httpx.Response(404)

    client = _client(handler)
    with pytest.raises(ResearchError, match="immutable commit"):
        await client.code("https://github.com/owner/repo", files=["model.py"])


@pytest.mark.asyncio
async def test_code_caps_explicit_selection_at_eight_files(offline):
    def handler(request):
        if "/commits/" in request.url.path:
            return httpx.Response(200, json={"sha": "a" * 40})
        if "/git/trees/" in request.url.path:
            return httpx.Response(200, json={"tree": []})
        return httpx.Response(404)

    client = _client(handler)
    with pytest.raises(ResearchError, match="at most eight"):
        await client.code(
            "https://github.com/owner/repo", files=[f"file{index}.py" for index in range(9)]
        )


def test_choose_files_ranks_readme_then_config_then_other_sources():
    paths = [
        "docs/notes.txt",
        "README.md",
        "src/main.py",
        "model.py",
        "train_config.yaml",
        "data.bin",
        "eval/metrics.json",
        "a.py",
        "b.py",
    ]
    assert choose_files(paths) == [
        "README.md",
        "model.py",
        "eval/metrics.json",
        "train_config.yaml",
        "a.py",
        "b.py",
    ]


def _audit_sources():
    paper = {
        "pages": [
            {"page": 1, "text": "fast convergence: rate 0.1. limit is Infinity"}
        ]
    }
    code = {
        "files": [
            {
                "path": "m.py",
                "status": "read",
                "text": "rate = 0.2  # implementation",
                "url": "https://github.com/owner/repo/blob/" + "a" * 40 + "/m.py",
            }
        ]
    }
    return paper, code


def test_audit_checks_rejects_more_than_twelve_checks():
    paper, code = _audit_sources()
    with pytest.raises(ResearchError, match="twelve"):
        audit_checks(paper, code, [{}] * 13)


def test_audit_checks_degrades_when_quotes_or_values_do_not_resolve():
    paper, code = _audit_sources()
    missing_file = audit_checks(
        paper,
        code,
        [{"claim": "c", "paper_quote": "0.1", "file": "nope.py", "code_quote": "0.2"}],
    )[0]
    assert missing_file["status"] == "unverified"

    missing_quotes = audit_checks(
        paper,
        code,
        [{"claim": "c", "paper_quote": "absent", "file": "m.py", "code_quote": "also absent"}],
    )[0]
    assert missing_quotes["status"] == "unverified"

    non_numeric = audit_checks(
        paper,
        code,
        [
            {
                "paper_quote": "fast convergence: rate 0.1",
                "file": "m.py",
                "code_quote": "rate = 0.2",
                "expected": "fast",
                "implemented": "0.2",
            }
        ],
    )[0]
    assert non_numeric["status"] == "requires_semantic_review"

    infinite = audit_checks(
        paper,
        code,
        [
            {
                "paper_quote": "limit is Infinity",
                "file": "m.py",
                "code_quote": "rate = 0.2",
                "expected": "Infinity",
                "implemented": "0.2",
            }
        ],
    )[0]
    assert infinite["status"] == "requires_semantic_review"


@pytest.mark.asyncio
async def test_literature_rejects_more_than_three_followups(offline):
    client = _client(lambda request: httpx.Response(200, content=_feed()))
    with pytest.raises(ResearchError, match="three"):
        await literature(client, "topic", ["a", "b", "c", "d"])


def test_read_pdf_rejects_empty_document_and_out_of_range_pages():
    zero_pages = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [] /Count 0 >>
endobj
trailer
<< /Size 3 /Root 1 0 R >>
%%EOF
"""
    with pytest.raises(ResearchError, match="no source pages"):
        read_pdf(zero_pages, [1], False)

    document = fitz.open()
    for number in range(3):
        document.new_page().insert_text((40, 40), f"Page {number + 1}")
    raw = document.tobytes()
    document.close()
    with pytest.raises(ResearchError, match="one-based"):
        read_pdf(raw, [99], False)
