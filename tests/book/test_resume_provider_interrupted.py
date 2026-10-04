"""Resuming a book whose generation was interrupted by the provider (#655).

When the account behind a book run dies mid-book — quota exhausted,
credentials revoked, provider outage — the chapters compiled before the
outage are READY, the chapter in flight settles PARTIAL with provider-level
block failures, and the chapters after it never started. A resume must spend
only what is genuinely owed:

- READY chapters are never requeued,
- the provider-interrupted chapter is redone, and redoing it retries only
  its failed blocks (the compiler skips blocks already READY),
- content-level failures stay terminal — those blocks already had a fair
  chance and re-running them re-spends the same calls for the same outcome,
- one chapter's failure never pauses or mutates the others' state.
"""

import asyncio
from types import SimpleNamespace

import pytest

from deeptutor.book.compiler import BookCompiler, CompilerOptions
from deeptutor.book.engine import (
    CONSECUTIVE_PAGE_FAILURE_LIMIT,
    BookEngine,
    _BookRuntime,
)
from deeptutor.book.models import (
    Block,
    BlockStatus,
    BlockType,
    Book,
    BookStatus,
    Chapter,
    Page,
    PageStatus,
    Spine,
)


def _block(status: BlockStatus, *, kind: str = "", block_id: str = "") -> Block:
    metadata = {"failure": {"kind": kind, "message": f"{kind} happened"}} if kind else {}
    payload = {"body": "original"} if status == BlockStatus.READY else {}
    return Block(
        id=block_id,
        type=BlockType.TEXT,
        status=status,
        metadata=metadata,
        payload=payload,
    )


def _provider_interrupted_page(page_id: str, order: int) -> Page:
    """A chapter half-generated when the quota ran out mid-book."""
    return Page(
        id=page_id,
        book_id="bk",
        order=order,
        status=PageStatus.PARTIAL,
        blocks=[
            _block(BlockStatus.READY),
            _block(BlockStatus.READY),
            _block(BlockStatus.ERROR, kind="rate_limit"),
            _block(BlockStatus.ERROR, kind="rate_limit"),
        ],
    )


def _engine(pages: list[Page], *, book: Book | None = None):
    engine = BookEngine.__new__(BookEngine)
    engine._global_lock = asyncio.Lock()
    engine._runtimes = {}
    state = {"book": book or Book(id="bk", status=BookStatus.PAUSED)}
    ops: list[str] = []

    class _Storage:
        def load_book(self, book_id):
            return state["book"]

        def load_spine(self, book_id):
            return Spine(book_id=book_id)

        def list_pages(self, book_id):
            return list(pages)

        def save_page(self, page):
            return None

        def save_book(self, saved):
            state["book"] = saved
            ops.append("save_book")

        def append_log(self, book_id, message, op="info"):
            ops.append(op)

    engine.storage = _Storage()
    return engine, state, ops


async def _resume_and_capture(engine: BookEngine) -> list[str]:
    queued: list[str] = []

    async def capture(book_id, pages):
        queued.extend(p.id for p in pages)

    engine._enqueue_pending_pages = capture
    await engine.resume_book(book_id="bk")
    return queued


# ─────────────────────────────────────────────────────────────────────────────
# Resume selection: redo what is owed, keep what is done
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resume_redoes_provider_interrupted_chapter_not_completed_ones() -> None:
    pages = [
        Page(
            id="pg_done",
            book_id="bk",
            order=0,
            status=PageStatus.READY,
            blocks=[_block(BlockStatus.READY)],
        ),
        _provider_interrupted_page("pg_half", order=1),
        Page(id="pg_new", book_id="bk", order=2, status=PageStatus.PENDING),
    ]
    engine, state, _ops = _engine(pages)

    queued = await _resume_and_capture(engine)

    assert queued == ["pg_half", "pg_new"], (
        "resume must requeue the interrupted and untouched chapters in order, "
        "never the completed one"
    )
    assert state["book"].status == BookStatus.COMPILING


@pytest.mark.asyncio
async def test_resume_of_only_interrupted_chapter_does_not_finalize_the_book() -> None:
    pages = [_provider_interrupted_page("pg_half", order=0)]
    engine, state, _ops = _engine(pages)

    queued = await _resume_and_capture(engine)

    assert queued == ["pg_half"]
    assert state["book"].status == BookStatus.COMPILING, (
        "a book whose only chapter is half-done through a provider failure "
        "still owes work — it must not be finalized READY by a resume"
    )


@pytest.mark.asyncio
async def test_resume_leaves_content_failed_chapters_terminal() -> None:
    pages = [
        Page(
            id="pg_content",
            book_id="bk",
            order=0,
            status=PageStatus.PARTIAL,
            blocks=[
                _block(BlockStatus.READY),
                _block(BlockStatus.ERROR, kind="json_parse"),
                _block(BlockStatus.ERROR, kind="empty_response"),
            ],
        ),
        Page(id="pg_new", book_id="bk", order=1, status=PageStatus.PENDING),
    ]
    engine, _state, _ops = _engine(pages)

    queued = await _resume_and_capture(engine)

    assert queued == ["pg_new"], (
        "content-level failures already had a fair chance; only untouched "
        "chapters are owed a compile"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Breaker: half-chapters through an outage count as provider trouble
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_breaker_counts_provider_interrupted_chapters() -> None:
    pages: list[Page] = []
    engine, state, ops = _engine(pages)
    runtime = _BookRuntime()
    runtime.consecutive_page_failures = CONSECUTIVE_PAGE_FAILURE_LIMIT - 1
    engine._runtimes["bk"] = runtime

    tripped = await engine._record_page_outcome(
        runtime, "bk", _provider_interrupted_page("pg_half", order=0)
    )

    assert tripped is True
    assert state["book"].status == BookStatus.PAUSED
    assert state["book"].metadata.get("pause_reason", "").startswith("rate_limit:")
    assert "paused" in ops


@pytest.mark.asyncio
async def test_content_failure_in_one_chapter_keeps_the_rest_going() -> None:
    engine, state, _ops = _engine([])
    runtime = _BookRuntime()
    engine._runtimes["bk"] = runtime

    content_failed = Page(
        id="pg_content",
        book_id="bk",
        status=PageStatus.ERROR,
        blocks=[
            _block(BlockStatus.ERROR, kind="json_parse"),
            _block(BlockStatus.ERROR, kind="json_parse"),
        ],
    )
    tripped = await engine._record_page_outcome(runtime, "bk", content_failed)

    assert tripped is False
    assert runtime.consecutive_page_failures == 0
    assert state["book"].status == BookStatus.PAUSED, "the book itself is untouched"


@pytest.mark.asyncio
async def test_partially_recovered_chapter_still_resets_the_breaker() -> None:
    """A PARTIAL page whose failures were content-level proves the provider lives."""
    engine, _state, _ops = _engine([])
    runtime = _BookRuntime()
    runtime.consecutive_page_failures = CONSECUTIVE_PAGE_FAILURE_LIMIT - 1
    engine._runtimes["bk"] = runtime

    recovered_mostly = Page(
        id="pg_mixed",
        book_id="bk",
        status=PageStatus.PARTIAL,
        blocks=[
            _block(BlockStatus.READY),
            _block(BlockStatus.ERROR, kind="rate_limit"),
            _block(BlockStatus.ERROR, kind="json_parse"),
            _block(BlockStatus.ERROR, kind="empty_response"),
        ],
    )
    tripped = await engine._record_page_outcome(runtime, "bk", recovered_mostly)

    assert tripped is False
    assert runtime.consecutive_page_failures == 0


# ─────────────────────────────────────────────────────────────────────────────
# Redo granularity: an interrupted chapter retries only its failed blocks
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recompiled_interrupted_chapter_spends_only_failed_blocks() -> None:
    ready_a = _block(BlockStatus.READY, block_id="blk_a")
    ready_b = _block(BlockStatus.READY, block_id="blk_b")
    failed_c = _block(BlockStatus.ERROR, kind="rate_limit", block_id="blk_c")
    failed_d = _block(BlockStatus.ERROR, kind="rate_limit", block_id="blk_d")
    page = Page(
        id="pg_half",
        book_id="bk",
        order=0,
        status=PageStatus.PARTIAL,
        blocks=[ready_a, ready_b, failed_c, failed_d],
    )
    chapter = Chapter(id="ch_1", title="Chapter 1", order=0)

    regenerated: list[str] = []
    saved_statuses: list[PageStatus] = []

    class _Generator:
        async def generate(self, ctx):
            regenerated.append(ctx.block.id)
            ctx.block.status = BlockStatus.READY
            ctx.block.payload["body"] = "regenerated"

    class _Storage:
        def save_page(self, saved):
            saved_statuses.append(saved.status)

        def append_log(self, book_id, message, op="info"):
            return None

        def load_exploration(self, book_id):
            raise FileNotFoundError(book_id)

    class _Stream:
        async def book_event(self, event, payload=None, stage=None):
            return None

    compiler = BookCompiler.__new__(BookCompiler)
    compiler.storage = _Storage()
    compiler.options = CompilerOptions(
        persist_after_each_block=True, block_retry_attempts=0, block_concurrency=1
    )
    compiler.registry = SimpleNamespace(get=lambda _type: _Generator())
    compiler.architect = None

    result = await compiler.compile_page(
        book_id="bk",
        chapter=chapter,
        page=page,
        stream=_Stream(),
    )

    assert regenerated == ["blk_c", "blk_d"], "only the failed blocks are re-spent"
    assert ready_a.payload["body"] == "original"
    assert ready_b.payload["body"] == "original"
    assert result.status == PageStatus.READY
    # Persisted per block, so an interruption mid-retry still keeps progress.
    assert saved_statuses[0] == PageStatus.GENERATING
    assert PageStatus.GENERATING in saved_statuses[1:]
    assert saved_statuses[-1] == PageStatus.READY
