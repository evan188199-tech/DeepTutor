"""The exposure chain behind a topic's materials: what gets loaded, what is
refused, and whether the manifest tells the tutor the truth about both.

Companion to ``test_topic_materials.py`` — that file covers the happy shapes;
this one pins the loading limits, the rejected references, and the
manifest/index consistency contract.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import re
from types import SimpleNamespace

import pytest

from deeptutor.learning.models import TopicSource, TopicSourceKind
from deeptutor.learning.topic_materials import (
    MAX_OUTLINE_CHARS,
    build_topic_materials,
    render_topic_manifest,
)
from deeptutor.services.workspace.models import WorkspaceError


def _chapter(cid: str, order: int, pages: list[str], summary: str = "", objectives=None):
    return SimpleNamespace(
        id=cid,
        title=f"Chapter {cid}",
        order=order,
        page_ids=pages,
        summary=summary,
        learning_objectives=objectives or [],
    )


def _book_storage(chapters, *, book=None, spine=None):
    return SimpleNamespace(
        load_book=lambda book_id: (
            book if book is not None else SimpleNamespace(title="Agentic RAG", id=book_id)
        ),
        load_spine=lambda book_id: (
            spine if spine is not None else SimpleNamespace(chapters=chapters)
        ),
    )


def _patch_book(
    monkeypatch: pytest.MonkeyPatch, chapters, *, context_text: str = "CONTENT"
) -> None:
    monkeypatch.setattr("deeptutor.book.storage.get_book_storage", lambda: _book_storage(chapters))
    monkeypatch.setattr(
        "deeptutor.book.context.build_book_context",
        lambda refs, **kwargs: SimpleNamespace(
            text=context_text + " " + ",".join(refs[0]["page_ids"]),
            references=[],
            warnings=[],
        ),
    )


def _source(kind, source_id: str, label: str, **kwargs) -> TopicSource:
    return TopicSource(
        id=f"src_{source_id or label}",
        kind=kind,
        source_id=source_id,
        label=label,
        **kwargs,
    )


@pytest.mark.parametrize("missing", ["book", "spine", "chapters"])
def test_a_book_without_generatable_content_is_one_unavailable_row(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    """No spine or no chapters means nothing to read: one honest row, not a
    crash and not an index entry pointing at air."""
    if missing == "book":
        monkeypatch.setattr(
            "deeptutor.book.storage.get_book_storage",
            lambda: _book_storage([], book=None),
        )
    elif missing == "spine":
        monkeypatch.setattr(
            "deeptutor.book.storage.get_book_storage",
            lambda: _book_storage([], spine=None),
        )
    else:
        monkeypatch.setattr(
            "deeptutor.book.storage.get_book_storage",
            lambda: _book_storage([]),
        )

    materials = build_topic_materials([_source(TopicSourceKind.BOOK, "bk_1", "Agentic RAG")])

    assert len(materials.materials) == 1
    row = materials.materials[0]
    assert row.available is False
    assert row.sid == ""
    assert row.full_text == ""
    assert "no generated chapters" in row.note


def test_chapter_outline_falls_back_to_learning_objectives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Grounding must survive a chapter whose summary was never generated: the
    objectives are still enough for the tutor to pick a chapter."""
    chapters = [
        _chapter("ch_a", 0, ["p1"], objectives=["Explain retrieval", "Cite sources"]),
    ]
    _patch_book(monkeypatch, chapters)

    materials = build_topic_materials([_source(TopicSourceKind.BOOK, "bk_1", "Agentic RAG")])
    manifest, _ = render_topic_manifest(materials)

    row = materials.materials[0]
    assert row.outline == "Explain retrieval; Cite sources"
    assert "Explain retrieval" in manifest


def test_overlong_outline_is_clipped_to_the_manifest_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A chapter summary longer than the row hint would bury a 40-chapter
    book's manifest."""
    long_summary = "细节" * 300
    chapters = [_chapter("ch_a", 0, ["p1"], summary=long_summary)]
    _patch_book(monkeypatch, chapters)

    materials = build_topic_materials([_source(TopicSourceKind.BOOK, "bk_1", "书")])

    row = materials.materials[0]
    assert len(row.outline) == MAX_OUTLINE_CHARS + 1
    assert row.outline.endswith("…")
    assert row.outline[:-1] in long_summary
    assert row.outline not in long_summary


def test_books_beyond_the_chapter_cap_name_the_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 42-chapter book lists its first 40 chapters and one summary row for
    the rest — the manifest stays readable and says what it left out."""
    chapters = [_chapter(f"ch_{i:02d}", i, [f"p{i}"]) for i in range(42)]
    _patch_book(monkeypatch, chapters)

    materials = build_topic_materials([_source(TopicSourceKind.BOOK, "bk_1", "大部头")])
    manifest, index = render_topic_manifest(materials)

    assert len(index) == 40
    overflow = materials.materials[-1]
    assert overflow.available is False
    assert overflow.sid == ""
    assert "+2 more chapters" in overflow.name
    assert "not listed this turn" in overflow.note
    assert overflow.name in manifest


def test_chapters_beyond_the_turn_budget_are_named_not_served(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once the material budget is spent the remaining chapters stay visible as
    named rows instead of being read or silently dropped."""
    chapters = [
        _chapter("ch_a", 0, ["p1"]),
        _chapter("ch_b", 1, ["p2"]),
    ]
    monkeypatch.setattr("deeptutor.book.storage.get_book_storage", lambda: _book_storage(chapters))
    monkeypatch.setattr(
        "deeptutor.book.context.build_book_context",
        lambda refs, **kwargs: SimpleNamespace(text="X" * 30, references=[], warnings=[]),
    )
    monkeypatch.setattr("deeptutor.learning.topic_materials.MAX_TOTAL_CHARS", 10)

    materials = build_topic_materials([_source(TopicSourceKind.BOOK, "bk_1", "书")])
    manifest, index = render_topic_manifest(materials)

    assert sorted(index) == ["bk-bk_1-ch_a"]
    second = materials.materials[1]
    assert second.available is False
    assert second.sid == ""
    assert "beyond this turn's material budget" in second.note
    assert "beyond this turn's material budget" in manifest


def test_an_empty_source_reference_is_never_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A selected row with no source id is refuse-able at the manifest step:
    the loader must not go hunting with an empty id."""

    def _explode():
        raise AssertionError("storage must not be consulted for an empty reference")

    monkeypatch.setattr("deeptutor.book.storage.get_book_storage", _explode)

    materials = build_topic_materials([_source(TopicSourceKind.BOOK, "", "空引用")])

    row = materials.materials[0]
    assert row.available is False
    assert row.sid == ""
    assert "marked unavailable" in row.note


def test_an_unrecognized_kind_is_declared_unreadable() -> None:
    """A kind the loader does not know is announced as unreadable rather than
    being ignored — the tutor must see that the material exists but cannot be
    served."""
    stranger = SimpleNamespace(
        id="src_x",
        kind="hologram",
        source_id="holo_1",
        label="全息讲义",
        position=0,
        available=True,
        metadata={},
    )

    materials = build_topic_materials([stranger])

    row = materials.materials[0]
    assert row.available is False
    assert row.sid == ""
    assert row.kind == "hologram"
    assert "cannot be read during tutoring" in row.note


def test_workspace_origin_namespaces_read_source_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same book selected in two workspaces must never collide on a
    ``read_source`` id, and a legacy source without an origin keeps its bare
    id."""
    chapters = [_chapter("ch_a", 0, ["p1"])]
    monkeypatch.setattr("deeptutor.book.storage.get_book_storage", lambda: _book_storage(chapters))
    monkeypatch.setattr(
        "deeptutor.book.context.build_book_context",
        lambda refs, **kwargs: SimpleNamespace(text="CONTENT", references=[], warnings=[]),
    )
    monkeypatch.setattr(
        "deeptutor.services.workspace.context.workspace_context",
        lambda origin: contextlib.nullcontext(),
    )

    def _prefixed(origin: str) -> str:
        return hashlib.sha256(origin.encode()).hexdigest()[:12]

    materials = build_topic_materials(
        [
            _source(
                TopicSourceKind.BOOK,
                "bk_1",
                "工作区A的书",
                position=0,
                metadata={"content_workspace_id": "ws-a"},
            ),
            _source(
                TopicSourceKind.BOOK,
                "bk_1",
                "工作区B的书",
                position=1,
                metadata={"content_workspace_id": "ws-b"},
            ),
            _source(TopicSourceKind.BOOK, "bk_1", "旧书", position=2),
        ]
    )
    _, index = render_topic_manifest(materials)

    assert f"ws-{_prefixed('ws-a')}-bk-bk_1-ch_a" in index
    assert f"ws-{_prefixed('ws-b')}-bk-bk_1-ch_a" in index
    assert "bk-bk_1-ch_a" in index
    assert len(index) == 3


def test_an_origin_that_fails_validation_never_reaches_the_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source pinned to a workspace this account may not read is refused
    where the scope is validated: the material degrades to an unavailable row,
    the id never enters the index, and the turn itself survives."""

    @contextlib.contextmanager
    def _deny(_origin):
        raise WorkspaceError("workspace is not available to this account")
        yield

    monkeypatch.setattr("deeptutor.services.workspace.context.workspace_context", _deny)

    materials = build_topic_materials(
        [
            _source(
                TopicSourceKind.BOOK,
                "bk_private",
                "别人的书",
                metadata={"content_workspace_id": "ws-other"},
            )
        ]
    )
    manifest, index = render_topic_manifest(materials)

    assert index == {}
    assert materials.warnings == ["book:bk_private"]
    row = materials.materials[0]
    assert row.available is False
    assert row.sid == ""
    assert "could not be loaded" in row.note
    assert "could not be loaded" in manifest


def test_manifest_ids_and_index_stay_in_sync_for_mixed_materials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every id the manifest announces is exactly what ``read_source`` can
    serve: no readable row without an id, no index key the manifest hides."""
    chapters = [_chapter("ch_a", 0, ["p1"])]
    _patch_book(monkeypatch, chapters)

    materials = build_topic_materials(
        [
            _source(TopicSourceKind.BOOK, "bk_1", "Agentic RAG", position=0),
            _source(TopicSourceKind.KNOWLEDGE_BASE, "mechanics-kb", "力学库", position=1),
            _source(TopicSourceKind.BOOK, "bk_gone", "缺失的书", position=2, available=False),
        ]
    )
    manifest, index = render_topic_manifest(materials)

    announced = set(re.findall(r"- id=(\S+)", manifest))
    assert announced == set(index)
    by_sid = {m.sid: m for m in materials.materials if m.readable}
    for sid, text in index.items():
        assert by_sid[sid].full_text == text
    kb_row = next(m for m in materials.materials if m.kind == "knowledge_base")
    assert kb_row.sid == ""
    assert "mechanics-kb" in manifest


def test_an_unreadable_chat_transcript_is_named_not_served(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A conversation that no longer loads degrades to an unavailable row with
    an empty id — never a half-empty index entry."""

    async def _gone(store, session_id, **kwargs):
        return None

    monkeypatch.setattr("deeptutor.services.session.source_inventory._load_history_session", _gone)
    monkeypatch.setattr(
        "deeptutor.learning.topic_materials._session_store", lambda: SimpleNamespace()
    )

    materials = build_topic_materials([_source(TopicSourceKind.CHAT, "sess_gone", "旧对话")])

    row = materials.materials[0]
    assert row.available is False
    assert row.readable is False
    assert row.sid == ""
    assert "could not be read" in row.note


def test_a_missing_question_bank_entry_is_named_not_served(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _gone(store, entry_id):
        return None

    monkeypatch.setattr("deeptutor.services.session.source_inventory._load_question_entry", _gone)
    monkeypatch.setattr(
        "deeptutor.learning.topic_materials._session_store", lambda: SimpleNamespace()
    )

    materials = build_topic_materials(
        [_source(TopicSourceKind.QUESTION_BANK, "404", "已删除的错题")]
    )

    row = materials.materials[0]
    assert row.available is False
    assert row.sid == ""
    assert "no longer exists" in row.note


def test_a_blank_cowriter_draft_is_named_not_served(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "deeptutor.co_writer.storage.get_co_writer_storage",
        lambda: SimpleNamespace(
            load_document=lambda doc_id: SimpleNamespace(title="空草稿", content="   ")
        ),
    )

    materials = build_topic_materials([_source(TopicSourceKind.COWRITER, "doc_blank", "空稿")])

    row = materials.materials[0]
    assert row.available is False
    assert row.sid == ""
    assert "this draft is empty" in row.note


def test_an_empty_notebook_is_rejected_upfront(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "deeptutor.services.notebook.get_notebook_manager",
        lambda: SimpleNamespace(get_records_by_references=lambda refs: []),
    )

    materials = build_topic_materials([_source(TopicSourceKind.NOTEBOOK, "nb_empty", "空笔记本")])

    row = materials.materials[0]
    assert row.available is False
    assert row.sid == ""
    assert "empty or unreadable" in row.note


def test_notebook_records_without_readable_content_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "deeptutor.services.notebook.get_notebook_manager",
        lambda: SimpleNamespace(
            get_records_by_references=lambda refs: [
                {"id": "r1", "title": "只有标题", "output": "   "},
                {"id": "r2", "title": "", "summary": ""},
            ]
        ),
    )

    materials = build_topic_materials([_source(TopicSourceKind.NOTEBOOK, "nb_blank", "空白笔记")])

    row = materials.materials[0]
    assert row.available is False
    assert row.sid == ""
    assert "no readable content" in row.note


def test_a_chapter_that_renders_to_nothing_is_named_not_served(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chapters = [_chapter("ch_a", 0, ["p1"], summary="写了目录没写正文")]
    monkeypatch.setattr("deeptutor.book.storage.get_book_storage", lambda: _book_storage(chapters))
    monkeypatch.setattr(
        "deeptutor.book.context.build_book_context",
        lambda refs, **kwargs: SimpleNamespace(text="  \n ", references=[], warnings=[]),
    )

    materials = build_topic_materials([_source(TopicSourceKind.BOOK, "bk_1", "书")])
    manifest, index = render_topic_manifest(materials)

    assert index == {}
    row = materials.materials[0]
    assert row.available is False
    assert "no readable content" in row.note
    assert "no readable content" in manifest


def test_materials_are_listed_in_the_topic_position_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The manifest walks the learner's own ordering, not the storage's."""
    monkeypatch.setattr(
        "deeptutor.services.notebook.get_notebook_manager",
        lambda: SimpleNamespace(
            get_records_by_references=lambda refs: [{"id": "r1", "title": "笔记", "output": "内容"}]
        ),
    )

    materials = build_topic_materials(
        [
            _source(TopicSourceKind.NOTEBOOK, "nb_a", "A", position=2),
            _source(TopicSourceKind.NOTEBOOK, "nb_b", "B", position=0),
            _source(TopicSourceKind.NOTEBOOK, "nb_c", "C", position=1),
        ]
    )

    assert [m.name for m in materials.materials] == [
        "B (1 records)",
        "C (1 records)",
        "A (1 records)",
    ]


def test_a_loader_called_on_a_running_loop_skips_instead_of_deadlocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loader is storage-bound and synchronous; if a future caller runs it
    on a loop, the turn must degrade — not wedge."""
    monkeypatch.setattr(
        "deeptutor.learning.topic_materials._session_store", lambda: SimpleNamespace()
    )

    async def _inside():
        return build_topic_materials([_source(TopicSourceKind.CHAT, "sess_1", "旧对话")])

    materials = asyncio.run(_inside())

    row = materials.materials[0]
    assert row.available is False
    assert row.sid == ""
