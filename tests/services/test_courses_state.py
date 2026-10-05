"""Focused tests for course-state aggregation and persistence boundaries.

Covers the mastery-stage derivation table (stored state may not be silently
overridden), rejection of invalid resource references, and the best-effort
degradation contract: one failing subsystem must blank only its own slice of
the snapshot, never the whole course state.
"""

from __future__ import annotations

import pytest

from deeptutor.services import courses_state
from deeptutor.services.courses import (
    COURSE_RESOURCE_KINDS,
    CourseNotFoundError,
    CourseService,
)

# ---------------------------------------------------------------------------
# Mastery stage derivation (the state table)
# ---------------------------------------------------------------------------


def test_mastery_stage_follows_derivation_precedence() -> None:
    # A stored stage wins even when the row also says "complete": the complete
    # flag may not override an explicit stage.
    assert courses_state._mastery_stage({"stage": "learning", "complete": True}, 0) == "learning"
    assert courses_state._mastery_stage({"current_stage": " complete "}, 0) == "complete"

    # Without a stored stage, the complete flag promotes.
    assert courses_state._mastery_stage({"complete": True}, 0) == "complete"

    # Any activity signal promotes to learning.
    assert courses_state._mastery_stage({"open_question": True}, 0) == "learning"
    assert courses_state._mastery_stage({"learning": 2}, 0) == "learning"
    assert courses_state._mastery_stage({}, 3) == "learning"

    # Nothing recorded stays not_started.
    assert courses_state._mastery_stage({}, 0) == "not_started"


def test_mastery_stage_rejects_unsupported_row_values() -> None:
    # Non-numeric activity markers cannot invent a transition.
    assert courses_state._mastery_stage({"learning": "not-a-number"}, 0) == "not_started"
    assert courses_state._mastery_stage({"learning": None}, 0) == "not_started"

    # Weak points keep only well-formed entries.
    row = {
        "weak_points": [
            {"name": "  Vectors "},
            {"label": "Limits", "name": ""},
            {"id": "wp_1"},
            {"irrelevant": True},
            "Derivatives",
            "   ",
            None,
        ]
    }
    assert courses_state._weak_points(row) == ["Vectors", "Limits", "wp_1", "Derivatives"]
    assert courses_state._weak_points({"weak_points": "not-a-list"}) == []
    assert courses_state._weak_points({}) == []


# ---------------------------------------------------------------------------
# Single-reference lookup: rejection and isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_reference_rejects_unknown_kind_blank_ref_and_loader_failure(
    monkeypatch,
) -> None:
    calls: list[str] = []

    async def book_loader() -> dict:
        calls.append("book")
        return {"b1": {"title": "Operating Systems"}, "123": {"title": "Numeric id"}}

    async def broken_loader() -> dict:
        raise RuntimeError("subsystem down")

    monkeypatch.setattr(
        courses_state,
        "_INDEX_LOADERS",
        {"book": book_loader, "mastery_path": broken_loader},
    )

    # Unknown kinds and blank references are rejected before any loader runs.
    assert await courses_state.resolve_resource_reference("partner_group", "b1") is None
    assert await courses_state.resolve_resource_reference("book", "   ") is None
    assert await courses_state.resolve_resource_reference("book", "") is None
    assert calls == []

    # A real lookup resolves, and numeric ids normalize to their string form.
    assert await courses_state.resolve_resource_reference("book", "b1") == {
        "title": "Operating Systems"
    }
    assert await courses_state.resolve_resource_reference("book", 123) == {"title": "Numeric id"}

    # A failing owning subsystem degrades to "not resolvable", not an error.
    assert await courses_state.resolve_resource_reference("mastery_path", "any") is None


@pytest.mark.asyncio
async def test_resolve_reference_returns_isolated_copy(monkeypatch) -> None:
    detail = {"title": "Shared", "pages": 3}

    async def book_loader() -> dict:
        return {"b1": detail}

    monkeypatch.setattr(courses_state, "_INDEX_LOADERS", {"book": book_loader})

    resolved = await courses_state.resolve_resource_reference("book", "b1")
    resolved["title"] = "Mutated"

    assert detail["title"] == "Shared"
    assert (await courses_state.resolve_resource_reference("book", "b1"))["title"] == "Shared"


# ---------------------------------------------------------------------------
# Whole-set candidates: per-kind degradation and stable ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_candidates_degrade_one_kind_at_a_time(monkeypatch) -> None:
    async def broken_book_loader() -> dict:
        raise RuntimeError("book engine down")

    async def notebook_loader() -> dict:
        return {
            "n2": {"name": "beta"},
            "n1": {"name": "Alpha"},
            "n3": {},
            "n4": {"name": "   "},
        }

    monkeypatch.setattr(
        courses_state,
        "_INDEX_LOADERS",
        {"book": broken_book_loader, "notebook": notebook_loader},
    )

    candidates = await courses_state.build_course_resource_candidates()

    # Every public kind stays present; a failed loader and a registry-less
    # kind both degrade to an empty list instead of vanishing.
    assert set(candidates) == set(COURSE_RESOURCE_KINDS)
    assert candidates["book"] == []
    assert candidates["partner_group"] == []

    # Labels sort case-insensitively and fall back to the ref id.
    assert [row["ref_id"] for row in candidates["notebook"]] == ["n1", "n2", "n3", "n4"]
    assert [row["label"] for row in candidates["notebook"]] == ["Alpha", "beta", "n3", "n4"]


# ---------------------------------------------------------------------------
# Session aggregation over the persisted session store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_state_aggregates_course_scope(monkeypatch) -> None:
    import deeptutor.services.session as session_pkg
    import deeptutor.services.session.organization as organization

    rows = [
        {
            "session_id": "s1",
            "title": "Newest",
            "preferences": {"course_id": "c1"},
            "updated_at": "30.5",
        },
        {
            "session_id": "s2",
            "title": "Archived",
            "preferences": {"course_id": "c1", "archived": True},
            "updated_at": 40,
        },
        {
            "session_id": "s3",
            "title": "Undated",
            "preferences": {"course_id": "c1"},
            "updated_at": "not-a-number",
        },
        {"id": "s4", "title": "Other course", "preferences": {"course_id": "c2"}, "updated_at": 99},
        {"session_id": "s5", "title": "No course", "preferences": {}, "updated_at": 50},
        {
            "session_id": "   ",
            "title": "Blank id",
            "preferences": {"course_id": "c1"},
            "updated_at": 10,
        },
    ]

    async def fake_snapshot(store):
        return rows

    monkeypatch.setattr(session_pkg, "get_session_store", lambda: object())
    monkeypatch.setattr(organization, "list_all_sessions_snapshot", fake_snapshot)

    sessions, ids = await courses_state._session_state("c1")

    assert sessions["archived"] == 1
    assert sessions["active"] == 3
    # Newest first; unparseable timestamps sort as zero, not crash.
    assert [row["session_id"] for row in sessions["recent"]] == ["s2", "s1", "   ", "s3"]
    assert sessions["recent"][0]["updated_at"] == 40.0
    assert sessions["recent"][1]["updated_at"] == 30.5
    # Blank ids never enter the id set even though their row counts as a session.
    assert ids == {"s1", "s2", "s3"}


@pytest.mark.asyncio
async def test_session_state_degrades_when_snapshot_unavailable(monkeypatch) -> None:
    import deeptutor.services.session as session_pkg
    import deeptutor.services.session.organization as organization

    async def broken_snapshot(store):
        raise RuntimeError("store down")

    monkeypatch.setattr(session_pkg, "get_session_store", lambda: object())
    monkeypatch.setattr(organization, "list_all_sessions_snapshot", broken_snapshot)

    sessions, ids = await courses_state._session_state("c1")

    assert sessions == {"active": 0, "archived": 0, "recent": []}
    assert ids == set()


# ---------------------------------------------------------------------------
# Question-bank aggregation: pagination, counting, degradation
# ---------------------------------------------------------------------------


class _FakeSqliteStore:
    def __init__(self, totals: dict[str, int], wrong_names: dict[str, list[str]]) -> None:
        self._totals = totals
        self._wrong = wrong_names
        self.total_queries = 0
        self.wrong_queries = 0

    async def list_notebook_entries(self, *, limit=10, offset=0, session_id=None, is_correct=None):
        if is_correct is None:
            self.total_queries += 1
            return {"total": self._totals[session_id], "items": []}
        self.wrong_queries += 1
        names = self._wrong[session_id][offset:]
        return {
            "total": len(self._wrong[session_id]),
            "items": [{"categories": [{"name": n}]} for n in names],
        }


@pytest.mark.asyncio
async def test_question_bank_skips_store_for_empty_course(monkeypatch) -> None:
    import deeptutor.services.session as session_pkg

    def forbidden_store():
        raise AssertionError("store must not be queried for a course without sessions")

    monkeypatch.setattr(session_pkg, "get_sqlite_session_store", forbidden_store)

    assert await courses_state._question_bank_state(set()) == {
        "total": 0,
        "wrong": 0,
        "weak_categories": [],
    }


@pytest.mark.asyncio
async def test_question_bank_paginates_wrong_entries_and_ranks_categories(monkeypatch) -> None:
    import deeptutor.services.session as session_pkg

    store = _FakeSqliteStore(
        totals={"s-a": 4, "s-b": 1},
        wrong_names={
            "s-a": ["Algebra"] * 250 + ["geometry"] * 250 + ["Geometry"] * 3,
            "s-b": [],
        },
    )
    monkeypatch.setattr(session_pkg, "get_sqlite_session_store", lambda: store)

    result = await courses_state._question_bank_state({"s-a", "s-b"})

    assert result["total"] == 5
    assert result["wrong"] == 503
    # Ranked by wrong count descending, ties broken case-insensitively by name.
    assert result["weak_categories"] == [
        {"name": "Algebra", "wrong": 250},
        {"name": "geometry", "wrong": 250},
        {"name": "Geometry", "wrong": 3},
    ]
    # The 503 wrong entries needed two pages for one session.
    assert store.wrong_queries == 3
    assert store.total_queries == 2


@pytest.mark.asyncio
async def test_question_bank_degrades_when_store_unavailable(monkeypatch) -> None:
    import deeptutor.services.session as session_pkg

    def broken_store():
        raise RuntimeError("sqlite store down")

    monkeypatch.setattr(session_pkg, "get_sqlite_session_store", broken_store)

    assert await courses_state._question_bank_state({"s1"}) == {
        "total": 0,
        "wrong": 0,
        "weak_categories": [],
    }


# ---------------------------------------------------------------------------
# Full course snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_course_state_marks_missing_resources_and_derives_progress(
    tmp_path, monkeypatch
) -> None:
    import deeptutor.services.courses as courses_pkg
    import deeptutor.services.session as session_pkg
    import deeptutor.services.session.organization as organization

    service = CourseService(root=tmp_path / "courses")
    monkeypatch.setattr(courses_pkg, "get_course_service", lambda: service)

    course = service.create(name="Calculus", description="Limits")
    service.attach_resource(course.id, kind="book", ref_id="b1", label="Textbook")
    service.attach_resource(course.id, kind="book", ref_id="missing", label="Vanished")
    service.attach_resource(course.id, kind="mastery_path", ref_id="p1", label="Path")
    service.attach_resource(course.id, kind="reading_workspace", ref_id="w1", label="Reader")
    updated = service.set_syllabus(
        course.id,
        [
            {"title": "Vectors", "topics": ["algebra"], "covered": True},
            {"title": "ODEs", "topics": ["Differential Equations"]},
        ],
    )
    units = updated.syllabus

    async def book_loader() -> dict:
        return {"b1": {"title": "Textbook", "pages": 120}}

    async def mastery_loader() -> dict:
        return {
            "p1": {
                "path_id": "p1",
                "name": "Path",
                "objectives_total": 4,
                "objectives_mastered": 1,
                "stage": "learning",
                "weak_points": ["Limits"],
            }
        }

    async def reading_loader() -> dict:
        return {"w1": {"workspace_id": "w1", "title": "Reader", "materials": 2}}

    monkeypatch.setattr(
        courses_state,
        "_INDEX_LOADERS",
        {"book": book_loader, "mastery_path": mastery_loader, "reading_workspace": reading_loader},
    )

    session_rows = [
        {
            "session_id": "s1",
            "title": "T1",
            "preferences": {"course_id": course.id},
            "updated_at": 20,
        },
        {
            "session_id": "s2",
            "title": "T2",
            "preferences": {"course_id": course.id, "archived": True},
            "updated_at": 10,
        },
    ]

    async def fake_snapshot(store):
        return session_rows

    monkeypatch.setattr(session_pkg, "get_session_store", lambda: object())
    monkeypatch.setattr(organization, "list_all_sessions_snapshot", fake_snapshot)
    monkeypatch.setattr(
        session_pkg,
        "get_sqlite_session_store",
        lambda: _FakeSqliteStore(
            totals={"s1": 3, "s2": 2},
            wrong_names={"s1": ["algebra"] * 3, "s2": ["Differential Equations"] * 2},
        ),
    )

    state = await courses_state.build_course_state(course.id)

    assert state["course"]["id"] == course.id

    by_ref = {row["ref_id"]: row for row in state["resources"]}
    assert by_ref["b1"]["available"] is True
    assert by_ref["b1"]["detail"] == {"title": "Textbook", "pages": 120}
    assert by_ref["missing"]["available"] is False
    assert by_ref["missing"]["detail"] == {}

    assert state["mastery"]["paths"] == [
        {
            "path_id": "p1",
            "name": "Path",
            "objectives_total": 4,
            "objectives_mastered": 1,
            "stage": "learning",
            "weak_points": ["Limits"],
        }
    ]
    assert state["reading"]["workspaces"] == [
        {"workspace_id": "w1", "title": "Reader", "materials": 2}
    ]

    assert state["sessions"]["active"] == 1
    assert state["sessions"]["archived"] == 1
    assert [row["session_id"] for row in state["sessions"]["recent"]] == ["s1", "s2"]

    assert state["question_bank"]["total"] == 5
    assert state["question_bank"]["wrong"] == 5

    assert state["syllabus"]["total"] == 2
    assert state["syllabus"]["covered"] == 1
    assert state["syllabus"]["next"] == {"id": units[1].id, "title": "ODEs", "position": 1}
    assert [unit["wrong_questions"] for unit in state["syllabus"]["units"]] == [3, 2]


@pytest.mark.asyncio
async def test_build_course_state_raises_for_unknown_course(tmp_path, monkeypatch) -> None:
    import deeptutor.services.courses as courses_pkg

    service = CourseService(root=tmp_path / "courses")
    monkeypatch.setattr(courses_pkg, "get_course_service", lambda: service)

    with pytest.raises(CourseNotFoundError):
        await courses_state.build_course_state("nope")
