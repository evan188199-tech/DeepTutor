"""The ``question_bank`` tool: the agent's only writable handle on the bank.

Regression cover for the reported failure — "file my wrong answers into
my new mistakes set" ended up in a notebook because no tool could reach
the question bank. These tests pin the shape that makes the ask a single
call: list gives ids, organize files them under a *name* and creates the
category when it is new.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.tools.question_bank import run_question_bank


@pytest.fixture
def store(tmp_path: Path) -> SQLiteSessionStore:
    return SQLiteSessionStore(db_path=tmp_path / "bank.db")


async def _seed(store: SQLiteSessionStore) -> str:
    session = await store.create_session(title="Drill")
    session_id = session["id"]
    await store.upsert_notebook_entries(
        session_id,
        [
            {
                "turn_id": "t1",
                "question_id": "q1",
                "question": "Derivative of sin(x)?",
                "correct_answer": "cos(x)",
                "user_answer": "-cos(x)",
                "is_correct": False,
            },
            {
                "turn_id": "t1",
                "question_id": "q2",
                "question": "Integral of 1/x?",
                "correct_answer": "ln|x| + C",
                "user_answer": "ln|x| + C",
                "is_correct": True,
            },
        ],
    )
    return session_id


@pytest.mark.asyncio
async def test_overview_on_empty_bank_is_explicit(store: SQLiteSessionStore) -> None:
    outcome = await run_question_bank(action="overview", store=store)
    assert outcome.ok
    assert "empty" in outcome.text


@pytest.mark.asyncio
async def test_list_wrong_exposes_ids_for_filing(store: SQLiteSessionStore) -> None:
    await _seed(store)
    outcome = await run_question_bank(action="list", filter_mode="wrong", store=store)
    assert outcome.ok
    assert outcome.summary["count"] == 1
    assert len(outcome.summary["entry_ids"]) == 1
    # The rendered id is what the model copies into ``organize``.
    assert f"[{outcome.summary['entry_ids'][0]}]" in outcome.text


@pytest.mark.asyncio
async def test_organize_creates_the_category_it_is_given(store: SQLiteSessionStore) -> None:
    await _seed(store)
    listing = await run_question_bank(action="list", filter_mode="wrong", store=store)
    ids = listing.summary["entry_ids"]

    outcome = await run_question_bank(
        action="organize", entry_ids=ids, category="微积分错题", store=store
    )
    assert outcome.ok
    assert outcome.summary["created_category"] is True
    assert outcome.summary["changed"] == len(ids)

    categories = await store.list_categories()
    assert [(c["name"], c["entry_count"]) for c in categories] == [("微积分错题", len(ids))]


@pytest.mark.asyncio
async def test_organize_is_idempotent_and_never_duplicates_a_category(
    store: SQLiteSessionStore,
) -> None:
    await _seed(store)
    ids = (await run_question_bank(action="list", store=store)).summary["entry_ids"]
    await run_question_bank(action="organize", entry_ids=ids, category="Mistakes", store=store)

    repeat = await run_question_bank(
        action="organize", entry_ids=ids, category="mistakes", store=store
    )
    assert repeat.ok
    assert repeat.summary["created_category"] is False
    assert repeat.summary["changed"] == 0
    assert len(await store.list_categories()) == 1


@pytest.mark.asyncio
async def test_uncategorized_is_the_triage_inbox(store: SQLiteSessionStore) -> None:
    await _seed(store)
    ids = (await run_question_bank(action="list", filter_mode="wrong", store=store)).summary[
        "entry_ids"
    ]
    await run_question_bank(action="organize", entry_ids=ids, category="Filed", store=store)

    inbox = await run_question_bank(action="list", filter_mode="uncategorized", store=store)
    assert inbox.summary["count"] == 1
    assert inbox.summary["entry_ids"] != ids


@pytest.mark.asyncio
async def test_bad_ids_do_not_sink_the_good_ones(store: SQLiteSessionStore) -> None:
    await _seed(store)
    ids = (await run_question_bank(action="list", store=store)).summary["entry_ids"]

    outcome = await run_question_bank(
        action="organize",
        entry_ids=[ids[0], "not-an-id", 987654],
        category="Partial",
        store=store,
    )
    assert outcome.ok
    assert outcome.summary["changed"] == 1
    assert "not-an-id" in outcome.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs, fragment",
    [
        ({"action": "nope"}, "Unknown action"),
        ({"action": "list", "filter_mode": "weird"}, "Unknown filter"),
        ({"action": "organize", "entry_ids": [1], "category": ""}, "`category` is required"),
        ({"action": "organize", "entry_ids": [], "category": "X"}, "`entry_ids`"),
        ({"action": "unfile", "entry_ids": [1], "category": "ghost"}, "No category named"),
        ({"action": "list", "category": "ghost"}, "No category named"),
    ],
)
async def test_errors_are_actionable_sentences(
    store: SQLiteSessionStore, kwargs: dict, fragment: str
) -> None:
    await _seed(store)
    outcome = await run_question_bank(store=store, **kwargs)
    assert not outcome.ok
    assert fragment in outcome.error


@pytest.mark.asyncio
async def test_bookmark_round_trip(store: SQLiteSessionStore) -> None:
    await _seed(store)
    ids = (await run_question_bank(action="list", store=store)).summary["entry_ids"]

    starred = await run_question_bank(action="bookmark", entry_ids=ids, store=store)
    assert starred.ok
    assert (await store.question_bank_stats())["bookmarked"] == len(ids)

    cleared = await run_question_bank(
        action="bookmark", entry_ids=ids, bookmarked=False, store=store
    )
    assert cleared.ok
    assert (await store.question_bank_stats())["bookmarked"] == 0


@pytest.mark.asyncio
async def test_mount_gate_follows_the_data(store: SQLiteSessionStore) -> None:
    assert store.has_question_bank_entries() is False
    await _seed(store)
    assert store.has_question_bank_entries() is True


# ── record (#1244): partner conversations file wrong questions ────────────


class _FakePartnerContext:
    """Duck-typed stand-in for PartnerTurnContext (only the fields the tool
    reads via getattr: partner_id / actor_id / partner_name / shared_memory)."""

    def __init__(self, shared_memory: Any, partner_id: str = "p1") -> None:
        self.partner_id = partner_id
        self.actor_id = "user-42"
        self.partner_name = "Study Buddy"
        self.shared_memory = shared_memory


@pytest.mark.asyncio
async def test_record_files_a_partner_mistake_without_a_placeholder_session(
    store: SQLiteSessionStore,
) -> None:
    outcome = await run_question_bank(
        action="record",
        question="  What is 7 × 8? ",
        user_answer="54",
        correct_answer="56",
        explanation="7×8 = 56, not 54 — the 7× row is easy to off-by-one.",
        category="Multiplication drills",
        store=store,
    )

    assert outcome.ok, outcome.error
    assert outcome.summary["session_id"] == ""
    assert outcome.summary["origin_type"] == "external_import"
    origin_ref = outcome.summary["origin_ref"]
    assert outcome.summary["source"] == "partner_chat"
    stats = await store.question_bank_stats()
    assert stats["total"] == 1
    entry = await store.find_notebook_entry_by_origin(
        "external_import", origin_ref, outcome.summary["question_id"]
    )
    assert entry is not None
    assert entry["session_id"] == ""
    assert entry["source"] == "partner_chat"
    assert entry["question"] == "What is 7 × 8?"
    assert await store.list_sessions() == []
    # The optional category was created and the entry filed into it.
    assert "Filed under 'Multiplication drills'" in outcome.text


@pytest.mark.asyncio
async def test_record_same_question_twice_updates_instead_of_duplicating(
    store: SQLiteSessionStore,
) -> None:
    first = await run_question_bank(action="record", question="What is 7 × 8?", store=store)
    again = await run_question_bank(
        action="record",
        question="WHAT  is 7 × 8?",  # different case/spacing, same question
        correct_answer="56",
        store=store,
    )

    assert first.ok and again.ok
    assert again.summary["question_id"] == first.summary["question_id"]
    assert (await store.question_bank_stats())["total"] == 1


@pytest.mark.asyncio
async def test_record_requires_the_question(store: SQLiteSessionStore) -> None:
    outcome = await run_question_bank(action="record", question="   ", store=store)
    assert not outcome.ok
    assert "`question` is required" in outcome.error


@pytest.mark.asyncio
async def test_record_routes_to_the_bank_the_family_browses(
    store: SQLiteSessionStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.path_service import PathService
    from deeptutor.services.session.sqlite_store import (
        get_sqlite_session_store_for,
    )

    learner_paths = PathService(workspace_root=tmp_path / "learner-scope")
    fake_context = _FakePartnerContext(shared_memory=learner_paths)
    monkeypatch.setattr(
        "deeptutor.services.partners.interaction.get_partner_turn_context",
        lambda: fake_context,
    )

    # No explicit store: inside a partner turn the tool must resolve the
    # learner-facing bank (the shared scope), not the partner's own.
    outcome = await run_question_bank(action="record", question="Define entropy.")

    assert outcome.ok, outcome.error
    partner_bank = get_sqlite_session_store_for(learner_paths)
    assert (await partner_bank.question_bank_stats())["total"] == 1
    # …and nothing leaked into the current (partner-scope) store.
    assert (await store.question_bank_stats())["total"] == 0


@pytest.mark.asyncio
async def test_partner_turns_mount_the_bank_even_when_it_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.agents._shared.tool_composition import partner_can_record_questions
    from deeptutor.services.path_service import PathService

    assert partner_can_record_questions() is False

    fake_context = _FakePartnerContext(
        shared_memory=PathService(workspace_root=Path(tmp_path) / "scope")
    )
    monkeypatch.setattr(
        "deeptutor.services.partners.interaction.get_partner_turn_context",
        lambda: fake_context,
    )
    assert partner_can_record_questions() is True


@pytest.mark.asyncio
async def test_ensure_notebook_session_is_idempotent(store: SQLiteSessionStore) -> None:
    assert await store.ensure_notebook_session("partner-notebook:p1:admin", "T (Partner)") is True
    assert await store.ensure_notebook_session("partner-notebook:p1:admin", "T (Partner)") is False


# ── query + sorting: overview stats, listing order, limit clamps ──────────


@pytest.mark.asyncio
async def test_overview_with_entries_renders_stats_and_name_sorted_categories(
    store: SQLiteSessionStore,
) -> None:
    session_id = await _seed(store)
    ids = (await run_question_bank(action="list", store=store)).summary["entry_ids"]
    # Create out of alphabetical order to pin the store's name-sorted listing.
    await run_question_bank(action="organize", entry_ids=ids[:1], category="Zoology", store=store)
    await run_question_bank(action="organize", entry_ids=ids[1:], category="Algebra", store=store)

    outcome = await run_question_bank(action="overview", store=store)
    assert outcome.ok
    assert "2 questions" in outcome.text
    assert "1 answered wrong" in outcome.text
    assert "0 bookmarked" in outcome.text
    names = [c["name"] for c in outcome.summary["categories"]]
    assert names == sorted(names) == ["Algebra", "Zoology"]
    assert "Algebra (1)" in outcome.text and "Zoology (1)" in outcome.text
    assert session_id  # seeded through a real session; overview never needs it


@pytest.mark.asyncio
async def test_list_orders_most_recent_first_and_hints_at_the_rest(
    store: SQLiteSessionStore,
) -> None:
    session = await store.create_session(title="Drill")
    questions = [f"Question number {i}?" for i in range(3)]
    await store.upsert_notebook_entries(
        session["id"],
        [
            {
                "turn_id": f"t{i}",
                "question_id": f"q{i}",
                "question": q,
                "correct_answer": "a",
                "user_answer": "b",
                "is_correct": False,
            }
            for i, q in enumerate(questions)
        ],
    )

    outcome = await run_question_bank(action="list", limit=2, store=store)
    assert outcome.ok
    assert outcome.summary["count"] == 2
    assert outcome.summary["total"] == 3
    # `recent` order: newest first, so the hint names exactly one hidden entry.
    assert outcome.summary["entry_ids"] == sorted(outcome.summary["entry_ids"], reverse=True)
    assert "1 more" in outcome.text


@pytest.mark.asyncio
async def test_list_clamps_limit_to_the_tool_ceiling(store: SQLiteSessionStore) -> None:
    session = await store.create_session(title="Bulk")
    await store.upsert_notebook_entries(
        session["id"],
        [
            {
                "turn_id": f"t{i}",
                "question_id": f"q{i}",
                "question": f"Q{i}?",
                "correct_answer": "a",
                "user_answer": "b",
                "is_correct": False,
            }
            for i in range(105)
        ],
    )

    greedy = await run_question_bank(action="list", limit=10_000, store=store)
    assert greedy.ok
    assert greedy.summary["count"] == 100  # MAX_LIST_LIMIT, not the model's 10_000

    zero = await run_question_bank(action="list", limit=0, store=store)
    assert zero.ok
    assert zero.summary["count"] == 20  # falls back to DEFAULT_LIST_LIMIT, not 0


# ── dedup: id coercion collapses duplicates and junk ──────────────────────


@pytest.mark.asyncio
async def test_organize_dedupes_ids_and_reports_the_junk(store: SQLiteSessionStore) -> None:
    await _seed(store)
    ids = (await run_question_bank(action="list", store=store)).summary["entry_ids"]

    outcome = await run_question_bank(
        action="organize",
        entry_ids=[ids[0], ids[0], str(ids[0]), "junk", 0, -3, None],
        category="Dedup check",
        store=store,
    )
    assert outcome.ok, outcome.error
    # Three spellings of the same id collapse to one request.
    assert outcome.summary["requested"] == 1
    assert outcome.summary["changed"] == 1
    assert "junk" in outcome.text
    assert len(await store.list_categories()) == 1


@pytest.mark.asyncio
async def test_single_id_shaped_like_a_scalar_still_files(store: SQLiteSessionStore) -> None:
    await _seed(store)
    ids = (await run_question_bank(action="list", store=store)).summary["entry_ids"]

    as_string = await run_question_bank(
        action="organize", entry_ids=str(ids[1]), category="Scalars", store=store
    )
    assert as_string.ok, as_string.error
    assert as_string.summary["requested"] == 1


# ── unfile: taking entries back out of a category ─────────────────────────


@pytest.mark.asyncio
async def test_unfile_returns_entries_to_the_uncategorized_inbox(
    store: SQLiteSessionStore,
) -> None:
    await _seed(store)
    ids = (await run_question_bank(action="list", store=store)).summary["entry_ids"]
    await run_question_bank(action="organize", entry_ids=ids, category="Temp", store=store)

    outcome = await run_question_bank(action="unfile", entry_ids=ids, category="Temp", store=store)
    assert outcome.ok, outcome.error
    assert outcome.summary["changed"] == len(ids)
    assert outcome.summary["created_category"] is False
    assert (await store.question_bank_stats())["uncategorized"] == len(ids)
    # The category survives with zero entries — removal is not deletion.
    assert [(c["name"], c["entry_count"]) for c in await store.list_categories()] == [("Temp", 0)]


@pytest.mark.asyncio
async def test_unfile_without_ids_is_an_actionable_error(store: SQLiteSessionStore) -> None:
    outcome = await run_question_bank(action="unfile", entry_ids=[], category="Temp", store=store)
    assert not outcome.ok
    assert "`entry_ids`" in outcome.error


# ── bookmark: partial store failures degrade instead of dying ─────────────


class _FlakyBookmarkStore:
    """Delegates everything to a real store, but update_notebook_entry raises
    for one poisoned id — a locked row, a transient db hiccup."""

    def __init__(self, inner: SQLiteSessionStore, poison_id: int) -> None:
        self._inner = inner
        self._poison = poison_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def update_notebook_entry(self, entry_id: int, updates: dict[str, Any]) -> bool:
        if entry_id == self._poison:
            raise RuntimeError("database is locked")
        return await self._inner.update_notebook_entry(entry_id, updates)


@pytest.mark.asyncio
async def test_bookmark_survives_a_poisoned_row_and_reports_the_rest(
    store: SQLiteSessionStore,
) -> None:
    await _seed(store)
    ids = (await run_question_bank(action="list", store=store)).summary["entry_ids"]
    flaky = _FlakyBookmarkStore(store, poison_id=ids[0])

    outcome = await run_question_bank(action="bookmark", entry_ids=ids, store=flaky)
    assert outcome.ok
    assert outcome.summary["updated"] == len(ids) - 1
    assert (await store.question_bank_stats())["bookmarked"] == len(ids) - 1


@pytest.mark.asyncio
async def test_bookmark_that_updates_nothing_stays_typed(store: SQLiteSessionStore) -> None:
    outcome = await run_question_bank(action="bookmark", entry_ids=[424242], store=store)
    assert not outcome.ok
    assert outcome.summary["updated"] == 0
    assert "No matching entries were updated" in outcome.error


# ── malformed data: the tool never raises, it degrades ────────────────────


class _StaticStore:
    """Returns canned listing payloads; everything else is unused."""

    def __init__(self, items: Any, total: int = 1) -> None:
        self._items = items
        self._total = total

    async def list_notebook_entries(self, **_kwargs: Any) -> dict[str, Any]:
        return {"items": self._items, "total": self._total}

    async def list_categories(self) -> list[dict[str, Any]]:
        return []

    async def question_bank_stats(self) -> dict[str, int]:
        return {"total": self._total, "wrong": 0, "bookmarked": 0, "uncategorized": 0}


@pytest.mark.asyncio
async def test_entries_with_missing_fields_render_without_raising() -> None:
    store = _StaticStore(
        items=[
            {
                "id": 7,
                "question": None,
                "user_answer": None,
                "correct_answer": "42",
                "is_correct": None,
                "bookmarked": None,
                "categories": None,
            }
        ]
    )
    outcome = await run_question_bank(action="list", store=store)
    assert outcome.ok, outcome.error
    assert outcome.summary["entry_ids"] == [7]
    assert "[7]" in outcome.text
    assert "answered: — | correct: 42" in outcome.text
    assert "(nothing yet)" in outcome.text


@pytest.mark.asyncio
async def test_structurally_broken_listing_degrades_to_a_typed_error() -> None:
    store = _StaticStore(items=["not-an-entry-dict"])
    outcome = await run_question_bank(action="list", store=store)
    assert not outcome.ok
    assert outcome.action == "list"
    assert "Question bank error" in outcome.error


class _ExplodingStore:
    async def question_bank_stats(self) -> dict[str, int]:
        raise RuntimeError("db gone")

    async def list_categories(self) -> list[dict[str, Any]]:
        raise RuntimeError("db gone")

    async def list_notebook_entries(self, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("db gone")


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["overview", "list"])
async def test_store_failures_come_back_as_sentences_not_exceptions(action: str) -> None:
    outcome = await run_question_bank(action=action, store=_ExplodingStore())
    assert not outcome.ok
    assert outcome.action == action
    assert "Question bank error" in outcome.error


# ── record: store-side rejections and filing fallbacks ────────────────────


class _RejectingStore:
    async def upsert_notebook_entries(self, _session_id: Any, _items: Any) -> list[Any]:
        return []


@pytest.mark.asyncio
async def test_record_reports_a_rejected_entry_without_raising() -> None:
    outcome = await run_question_bank(
        action="record", question="What is 2 + 2?", store=_RejectingStore()
    )
    assert not outcome.ok
    assert "The bank rejected the entry" in outcome.error


class _EntryLostStore:
    """The upsert 'succeeds' but the recorded entry can no longer be found,
    so the optional category filing has nothing to attach to."""

    async def upsert_notebook_entries(self, _session_id: Any, items: Any) -> list[Any]:
        return list(items)

    async def find_notebook_entry_by_origin(self, *_args: Any) -> None:
        return None


@pytest.mark.asyncio
async def test_record_degrades_gracefully_when_the_entry_cannot_be_filed() -> None:
    outcome = await run_question_bank(
        action="record",
        question="What is 2 + 2?",
        category="Arithmetic",
        store=_EntryLostStore(),
    )
    assert outcome.ok, outcome.error  # the record itself worked
    assert "Could not file it into a category" in outcome.text
    assert outcome.summary["question_id"].startswith("pq_")


@pytest.mark.asyncio
async def test_record_truncates_oversized_fields_and_keeps_the_dedup_id_stable(
    store: SQLiteSessionStore,
) -> None:
    long_question = "What is seven times eight? " * 300  # well past MAX_RECORD_QUESTION
    long_answer = "56 " * 1000  # well past MAX_RECORD_FIELD

    first = await run_question_bank(
        action="record",
        question=long_question,
        correct_answer=long_answer,
        user_answer=long_answer,
        explanation=long_answer,
        store=store,
    )
    assert first.ok, first.error

    # Same question, re-spaced — the content hash must still collapse it.
    re_spaced = "  " + "\t".join(long_question.split()) + "  "
    again = await run_question_bank(action="record", question=re_spaced, store=store)
    assert again.ok, again.error
    assert again.summary["question_id"] == first.summary["question_id"]
    assert (await store.question_bank_stats())["total"] == 1

    entry = await store.find_notebook_entry_by_origin(
        "external_import", first.summary["origin_ref"], first.summary["question_id"]
    )
    assert entry is not None
    assert len(entry["question"]) <= 4000
    assert len(entry["correct_answer"]) <= 2000
    assert len(entry["user_answer"]) <= 2000
    assert len(entry["explanation"]) <= 2000


# ── action dispatch: tolerant parsing at the front door ───────────────────


@pytest.mark.asyncio
async def test_action_and_filter_names_tolerate_case_and_padding(
    store: SQLiteSessionStore,
) -> None:
    padded = await run_question_bank(action="  OVERVIEW  ", store=store)
    assert padded.ok, padded.error

    listing = await run_question_bank(action="List", filter_mode="  WRONG  ", store=store)
    assert listing.ok, listing.error
    assert listing.summary["filter"] == "wrong"


@pytest.mark.asyncio
async def test_unknown_action_names_the_supported_set(store: SQLiteSessionStore) -> None:
    outcome = await run_question_bank(action="delete-everything", store=store)
    assert not outcome.ok
    for verb in ("overview", "list", "organize", "unfile", "bookmark", "record"):
        assert verb in outcome.error
