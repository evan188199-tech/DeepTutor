"""Unit tests for :mod:`deeptutor.tools.paper_search_tool`.

All arXiv I/O is stubbed out — the tool's ``client`` attribute is replaced
with an in-memory stub, so no test ever reaches the network.
"""

from __future__ import annotations

from datetime import datetime, timezone
import time

import arxiv
import pytest

from deeptutor.tools.paper_search_tool import ArxivSearchTool, PaperSearchTool

# ---------------------------------------------------------------------------
# Stubs — mirror the injected-response style of tests/tools/test_web_fetch.py
# ---------------------------------------------------------------------------


class _StubAuthor:
    def __init__(self, name: str) -> None:
        self.name = name


class _StubResult:
    def __init__(
        self,
        *,
        title: str,
        authors: list[str],
        year: int,
        month: int = 1,
        day: int = 15,
        entry_id: str,
        summary: str | None = None,
    ) -> None:
        self.title = title
        self.authors = [_StubAuthor(name) for name in authors]
        self.published = datetime(year, month, day, tzinfo=timezone.utc)
        self.entry_id = entry_id
        self.summary = summary


class _StubClient:
    """Replays scripted pages: each entry is a list of results or an exception."""

    def __init__(self, pages: list) -> None:
        self._pages = list(pages)
        self.calls: list[arxiv.Search] = []

    def results(self, search: arxiv.Search):
        self.calls.append(search)
        outcome = self._pages.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        yield from outcome

    @property
    def call_count(self) -> int:
        return len(self.calls)


def _tool_with(client: _StubClient) -> ArxivSearchTool:
    tool = ArxivSearchTool()
    tool.client = client
    return tool


def _make_paper(
    title: str,
    *,
    authors: list[str],
    year: int,
    entry_id: str,
    summary: str | None = None,
    month: int = 1,
    day: int = 15,
) -> _StubResult:
    return _StubResult(
        title=title,
        authors=authors,
        year=year,
        entry_id=entry_id,
        summary=summary,
        month=month,
        day=day,
    )


# ---------------------------------------------------------------------------
# Query parameter assembly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_query_returns_empty_without_network_call() -> None:
    client = _StubClient([])
    papers = await _tool_with(client).search_papers(query="")
    assert papers == []
    assert client.call_count == 0


@pytest.mark.asyncio
async def test_whitespace_only_query_returns_empty_without_network_call() -> None:
    client = _StubClient([])
    papers = await _tool_with(client).search_papers(query="   \n\t ")
    assert papers == []
    assert client.call_count == 0


@pytest.mark.asyncio
async def test_query_is_stripped_before_search() -> None:
    client = _StubClient([[]])
    await _tool_with(client).search_papers(query="  transformer attention  ")
    assert client.calls[0].query == "transformer attention"


@pytest.mark.asyncio
async def test_sort_by_relevance_uses_relevance_criterion() -> None:
    client = _StubClient([[]])
    await _tool_with(client).search_papers(query="test", sort_by="relevance")
    assert client.calls[0].sort_by is arxiv.SortCriterion.Relevance
    assert client.calls[0].sort_order is arxiv.SortOrder.Descending


@pytest.mark.asyncio
async def test_sort_by_date_uses_submitted_date_criterion() -> None:
    client = _StubClient([[]])
    await _tool_with(client).search_papers(query="test", sort_by="date")
    assert client.calls[0].sort_by is arxiv.SortCriterion.SubmittedDate


@pytest.mark.asyncio
async def test_unknown_sort_by_falls_back_to_relevance() -> None:
    client = _StubClient([[]])
    await _tool_with(client).search_papers(query="test", sort_by="nonsense")
    assert client.calls[0].sort_by is arxiv.SortCriterion.Relevance


@pytest.mark.asyncio
async def test_max_results_is_clamped_to_upper_bound() -> None:
    client = _StubClient([[]])
    await _tool_with(client).search_papers(query="test", max_results=50)
    # fetch size is min(50 * 2, 30) = 30
    assert client.calls[0].max_results == 30


@pytest.mark.asyncio
async def test_max_results_floor_is_one() -> None:
    client = _StubClient([[]])
    papers = await _tool_with(client).search_papers(query="test", max_results=0)
    assert client.calls[0].max_results == 2  # min(1 * 2, 30)
    assert papers == []


@pytest.mark.asyncio
async def test_small_max_results_fetches_double_but_returns_requested_count() -> None:
    recent = datetime.now().year
    client = _StubClient(
        [
            [
                _make_paper(
                    f"Paper {i}",
                    authors=["A Author"],
                    year=recent,
                    entry_id=f"http://arxiv.org/abs/2401.0000{i}",
                )
                for i in range(6)
            ]
        ]
    )
    papers = await _tool_with(client).search_papers(query="test", max_results=3)
    assert client.calls[0].max_results == 6  # 3 * 2
    assert len(papers) == 3


# ---------------------------------------------------------------------------
# Response parsing — normal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normal_response_parses_full_paper_contract() -> None:
    client = _StubClient(
        [
            [
                _make_paper(
                    "Attention Is All You Need",
                    authors=["Ashish Vaswani", "Noam Shazeer"],
                    year=2017,
                    month=6,
                    day=12,
                    entry_id="http://arxiv.org/abs/1706.03762v7",
                    summary="We propose a new simple network architecture, the Transformer.\n"
                    "Based   solely on attention mechanisms.",
                )
            ]
        ]
    )
    papers = await _tool_with(client).search_papers(query="transformer", years_limit=None)

    assert len(papers) == 1
    paper = papers[0]
    assert paper["title"] == "Attention Is All You Need"
    assert paper["authors"] == ["Ashish Vaswani", "Noam Shazeer"]
    assert paper["year"] == 2017
    assert paper["abstract"] == (
        "We propose a new simple network architecture, the Transformer. "
        "Based solely on attention mechanisms."
    )
    assert paper["url"] == "http://arxiv.org/abs/1706.03762v7"
    assert paper["arxiv_id"] == "1706.03762"
    assert paper["published"] == "2017-06-12T00:00:00+00:00"


@pytest.mark.asyncio
async def test_arxiv_id_is_stripped_of_version_suffix() -> None:
    client = _StubClient(
        [
            [
                _make_paper(
                    "P", authors=["A B"], year=2024, entry_id="http://arxiv.org/abs/2312.00752v2"
                )
            ]
        ]
    )
    papers = await _tool_with(client).search_papers("p", years_limit=None)
    assert papers[0]["arxiv_id"] == "2312.00752"


@pytest.mark.asyncio
async def test_arxiv_id_without_version_is_kept_as_is() -> None:
    client = _StubClient(
        [[_make_paper("P", authors=["A B"], year=2024, entry_id="http://arxiv.org/abs/2312.00752")]]
    )
    papers = await _tool_with(client).search_papers("p", years_limit=None)
    assert papers[0]["arxiv_id"] == "2312.00752"


@pytest.mark.asyncio
async def test_none_summary_is_normalized_to_empty_string() -> None:
    client = _StubClient(
        [
            [
                _make_paper(
                    "P",
                    authors=["A B"],
                    year=2024,
                    entry_id="http://arxiv.org/abs/2401.00001",
                    summary=None,
                )
            ]
        ]
    )
    papers = await _tool_with(client).search_papers("p", years_limit=None)
    assert papers[0]["abstract"] == ""


# ---------------------------------------------------------------------------
# Response truncation — max_results cap and year filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_results_are_truncated_at_max_results_in_feed_order() -> None:
    recent = datetime.now().year
    client = _StubClient(
        [
            [
                _make_paper(
                    f"Paper {i}",
                    authors=["A Author"],
                    year=recent,
                    entry_id=f"http://arxiv.org/abs/2401.0000{i}",
                )
                for i in range(5)
            ]
        ]
    )
    papers = await _tool_with(client).search_papers("test", max_results=2, years_limit=None)
    assert [p["title"] for p in papers] == ["Paper 0", "Paper 1"]


@pytest.mark.asyncio
async def test_papers_older_than_years_limit_are_filtered_out() -> None:
    recent = datetime.now().year
    client = _StubClient(
        [
            [
                _make_paper(
                    "Old",
                    authors=["A B"],
                    year=recent - 10,
                    entry_id="http://arxiv.org/abs/2001.00001",
                ),
                _make_paper(
                    "Fresh",
                    authors=["A B"],
                    year=recent - 1,
                    entry_id="http://arxiv.org/abs/2501.00001",
                ),
            ]
        ]
    )
    papers = await _tool_with(client).search_papers("test", years_limit=3)
    assert [p["title"] for p in papers] == ["Fresh"]


@pytest.mark.asyncio
async def test_years_limit_boundary_year_is_kept() -> None:
    # current_year - year == years_limit is within the limit (only strictly
    # older papers are dropped).
    boundary_year = datetime.now().year - 3
    client = _StubClient(
        [
            [
                _make_paper(
                    "Boundary",
                    authors=["A B"],
                    year=boundary_year,
                    entry_id="http://arxiv.org/abs/2301.00001",
                )
            ]
        ]
    )
    papers = await _tool_with(client).search_papers("test", years_limit=3)
    assert [p["title"] for p in papers] == ["Boundary"]


@pytest.mark.asyncio
async def test_years_limit_none_keeps_old_papers() -> None:
    client = _StubClient(
        [
            [
                _make_paper(
                    "Ancient",
                    authors=["A B"],
                    year=1995,
                    entry_id="http://arxiv.org/abs/9501.00001",
                )
            ]
        ]
    )
    papers = await _tool_with(client).search_papers("test", years_limit=None)
    assert [p["title"] for p in papers] == ["Ancient"]


@pytest.mark.asyncio
async def test_all_results_filtered_by_year_returns_empty_list() -> None:
    client = _StubClient(
        [
            [
                _make_paper(
                    "Old", authors=["A B"], year=1995, entry_id="http://arxiv.org/abs/9501.00001"
                )
            ]
        ]
    )
    papers = await _tool_with(client).search_papers("test", years_limit=3)
    assert papers == []


# ---------------------------------------------------------------------------
# Empty results and error paths — every failure must return [], never raise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_result_page_returns_empty_list() -> None:
    client = _StubClient([[]])
    papers = await _tool_with(client).search_papers("test")
    assert papers == []
    assert client.call_count == 1


@pytest.mark.asyncio
async def test_timeout_returns_empty_list(monkeypatch) -> None:
    from deeptutor.tools import paper_search_tool as module

    monkeypatch.setattr(module, "_REQUEST_TIMEOUT_S", 0.05)

    class _SlowClient(_StubClient):
        def results(self, search):
            self.calls.append(search)
            time.sleep(1.0)
            yield from []

    client = _SlowClient([])
    papers = await _tool_with(client).search_papers("test")
    assert papers == []


@pytest.mark.asyncio
async def test_http_error_500_returns_empty_list_without_retry() -> None:
    client = _StubClient(
        [arxiv.HTTPError(url="http://export.arxiv.org/api/query", retry=0, status=500)]
    )
    papers = await _tool_with(client).search_papers("test")
    assert papers == []
    assert client.call_count == 1


@pytest.mark.asyncio
async def test_http_error_429_retries_once_and_succeeds(monkeypatch) -> None:
    from deeptutor.tools import paper_search_tool as module

    monkeypatch.setattr(module, "_RETRY_DELAY_S", 0)
    client = _StubClient(
        [
            arxiv.HTTPError(url="http://export.arxiv.org/api/query", retry=0, status=429),
            [
                _make_paper(
                    "Recovered",
                    authors=["A B"],
                    year=2024,
                    entry_id="http://arxiv.org/abs/2401.00001",
                )
            ],
        ]
    )
    papers = await _tool_with(client).search_papers("test", years_limit=None)
    assert [p["title"] for p in papers] == ["Recovered"]
    assert client.call_count == 2


@pytest.mark.asyncio
async def test_http_error_429_retry_failure_returns_empty_list(monkeypatch) -> None:
    from deeptutor.tools import paper_search_tool as module

    monkeypatch.setattr(module, "_RETRY_DELAY_S", 0)
    client = _StubClient(
        [
            arxiv.HTTPError(url="http://export.arxiv.org/api/query", retry=0, status=429),
            arxiv.HTTPError(url="http://export.arxiv.org/api/query", retry=1, status=429),
        ]
    )
    papers = await _tool_with(client).search_papers("test")
    assert papers == []
    assert client.call_count == 2


@pytest.mark.asyncio
async def test_unexpected_error_during_fetch_returns_empty_list() -> None:
    client = _StubClient([ValueError("malformed feed payload")])
    papers = await _tool_with(client).search_papers("test")
    assert papers == []


# ---------------------------------------------------------------------------
# Output structure contract
# ---------------------------------------------------------------------------


_DOCUMENTED_KEYS = {"title", "authors", "year", "abstract", "url", "arxiv_id", "published"}


@pytest.mark.asyncio
async def test_every_paper_has_exactly_the_documented_keys_with_types() -> None:
    recent = datetime.now().year
    client = _StubClient(
        [
            [
                _make_paper(
                    "Contract",
                    authors=["First Author", "Second Author"],
                    year=recent,
                    month=3,
                    day=2,
                    entry_id="http://arxiv.org/abs/2503.00001v1",
                    summary="  A   spaced   out summary.  ",
                )
            ]
        ]
    )
    papers = await _tool_with(client).search_papers("contract", years_limit=None)

    assert len(papers) == 1
    paper = papers[0]
    assert set(paper.keys()) == _DOCUMENTED_KEYS
    assert isinstance(paper["title"], str)
    assert isinstance(paper["authors"], list) and all(isinstance(a, str) for a in paper["authors"])
    assert isinstance(paper["year"], int)
    assert isinstance(paper["abstract"], str)
    assert isinstance(paper["url"], str)
    assert isinstance(paper["arxiv_id"], str)
    assert isinstance(paper["published"], str)


# ---------------------------------------------------------------------------
# Citation / URL helpers
# ---------------------------------------------------------------------------


def test_format_paper_citation_single_author() -> None:
    tool = ArxivSearchTool()
    citation = tool.format_paper_citation({"authors": ["Ada Lovelace"], "year": 2024})
    assert citation == "(Lovelace, 2024)"


def test_format_paper_citation_uses_surname_of_multiword_name() -> None:
    tool = ArxivSearchTool()
    citation = tool.format_paper_citation({"authors": ["Grace Brewster Hopper"], "year": 2024})
    assert citation == "(Hopper, 2024)"


def test_format_paper_citation_multiple_authors_uses_et_al() -> None:
    tool = ArxivSearchTool()
    citation = tool.format_paper_citation(
        {"authors": ["Ada Lovelace", "Grace Hopper"], "year": 2024}
    )
    assert citation == "(Lovelace et al., 2024)"


def test_format_paper_citation_without_authors_is_unknown() -> None:
    tool = ArxivSearchTool()
    citation = tool.format_paper_citation({"authors": [], "year": 2024})
    assert citation == "(Unknown, 2024)"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://arxiv.org/abs/2312.00752v2", "2312.00752"),
        ("https://arxiv.org/abs/2312.00752", "2312.00752"),
        ("https://arxiv.org/pdf/2312.00752", "2312.00752"),
        ("http://export.arxiv.org/abs/1706.03762v7", "1706.03762"),
        ("https://example.com/paper/2312.00752", None),
        ("not a url", None),
    ],
)
def test_extract_arxiv_id_from_url(url: str, expected: str | None) -> None:
    assert ArxivSearchTool().extract_arxiv_id_from_url(url) == expected


def test_backward_compatible_alias_points_to_same_class() -> None:
    assert PaperSearchTool is ArxivSearchTool
