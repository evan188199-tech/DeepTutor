"""Boundary and tolerance tests for the mastery atlas navigator.

:mod:`deeptutor.learning.navigation` walks the store and returns plain
dictionaries, so what can go wrong is pagination and resolution: a cap that
fails to report what it dropped, a lesson reference that jumps past the last
module, a malformed session row. These tests pin the transitions the happy-path
tests elsewhere do not reach — paging forward past the caps, the resolution
fallback ladder, first/last/out-of-bounds positions, and malformed inputs.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.learning import navigation
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    TopicMetadata,
)
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore


def _store_init_factory(root: Path):
    def _init(self, root_arg=None):  # mirrors LearningStore.__init__
        self._root = Path(root) / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    return _init


@pytest.fixture
def store(tmp_path, monkeypatch) -> LearningStore:
    monkeypatch.setattr(LearningStore, "__init__", _store_init_factory(tmp_path))
    return LearningStore()


def _modules(prefix: str = "m", count: int = 2, names: list[str] | None = None):
    modules = []
    for index in range(1, count + 1):
        module_id = f"{prefix}{index}"
        name = names[index - 1] if names else f"Lesson {index}"
        modules.append(
            LearningModule(
                id=module_id,
                name=name,
                order=index,
                knowledge_points=[
                    KnowledgePoint(
                        id=f"{module_id}_kp1",
                        name=f"{name} point",
                        type=KnowledgeType.MEMORY,
                        module_id=module_id,
                    )
                ],
            )
        )
    return modules


def _create_topic(
    path_id: str,
    name: str = "Intro Statistics",
    modules: list[LearningModule] | None = None,
) -> None:
    LearningService().create_topic(
        path_id,
        name=name,
        modules=modules if modules is not None else _modules(),
        metadata=TopicMetadata(path_id=path_id, goal="Pass the exam", emoji="📊"),
        sources=[],
    )


def _resolved_topic(store: LearningStore, path_id: str = "stats_101") -> dict:
    _create_topic(path_id)
    topic = navigation.find_topic(path_id)
    assert topic is not None
    return topic


# ── paging forward: the caps clip and report ─────────────────────────────────


def test_topic_cards_page_forward_past_the_cap_and_report_the_omission(store):
    for index in range(navigation.TOPIC_LIMIT + 2):
        _create_topic(f"path_{index}")

    payload = navigation.topic_cards()

    assert len(payload["topics"]) == navigation.TOPIC_LIMIT
    assert payload["total_topics"] == navigation.TOPIC_LIMIT + 2
    assert payload["topics_omitted"] == 2


def test_topic_cards_at_exactly_the_cap_omit_nothing(store):
    for index in range(navigation.TOPIC_LIMIT):
        _create_topic(f"path_{index}")

    payload = navigation.topic_cards()

    assert len(payload["topics"]) == navigation.TOPIC_LIMIT
    assert payload["total_topics"] == navigation.TOPIC_LIMIT
    assert "topics_omitted" not in payload


def test_module_outline_pages_forward_past_the_cap_and_reports_the_omission(store):
    _create_topic("stats_101", modules=_modules(count=navigation.MODULE_LIMIT + 3))

    card = navigation.find_topic("stats_101")

    assert card is not None
    assert len(card["modules"]) == navigation.MODULE_LIMIT
    assert card["modules_omitted"] == 3
    # The head of the outline survives the clip, so lesson 1 stays findable.
    assert card["modules"][0]["order"] == 1


def test_module_outline_at_exactly_the_cap_omits_nothing(store):
    _create_topic("stats_101", modules=_modules(count=navigation.MODULE_LIMIT))

    card = navigation.find_topic("stats_101")

    assert card is not None
    assert len(card["modules"]) == navigation.MODULE_LIMIT
    assert "modules_omitted" not in card


# ── the resolution ladder: id, name, fragment, position ─────────────────────


def test_resolve_module_matches_the_name_before_the_position(store):
    # A lesson literally called "Lesson 2" in position 1 must not be swapped
    # for the actual second lesson when the learner names it.
    _create_topic(
        "stats_101",
        modules=_modules(names=["Lesson 2", "Sampling", "Regression"]),
    )
    topic = navigation.find_topic("stats_101")
    assert topic is not None

    module = navigation.resolve_module(topic, "Lesson 2")

    assert module is not None and module["module_id"] == "m1"


def test_resolve_module_walks_id_then_name_then_fragment(store):
    _create_topic(
        "stats_101",
        modules=_modules(names=["Regression chapter", "Sampling chapter"]),
    )
    topic = navigation.find_topic("stats_101")
    assert topic is not None

    by_id = navigation.resolve_module(topic, "m1")
    by_name = navigation.resolve_module(topic, "Sampling chapter")
    by_fragment = navigation.resolve_module(topic, "sampling")

    assert by_id is not None and by_id["module_id"] == "m1"
    assert by_name is not None and by_name["module_id"] == "m2"
    assert by_fragment is not None and by_fragment["module_id"] == "m2"


def test_resolve_module_accepts_a_phrase_that_contains_the_lesson_name(store):
    _create_topic(
        "stats_101",
        modules=_modules(names=["Regression chapter", "Sampling chapter"]),
    )
    topic = navigation.find_topic("stats_101")
    assert topic is not None

    module = navigation.resolve_module(topic, "the regression chapter review")

    assert module is not None and module["module_id"] == "m1"


def test_resolve_module_positions_at_the_first_and_last_lesson(store):
    topic = _resolved_topic(store, "stats_101")

    assert navigation.resolve_module(topic, "lesson 1")["module_id"] == "m1"
    assert navigation.resolve_module(topic, "2")["module_id"] == "m2"
    assert navigation.resolve_module(topic, "第二课")["module_id"] == "m2"


def test_resolve_module_refuses_jumps_out_of_bounds(store):
    topic = _resolved_topic(store, "stats_101")

    assert navigation.resolve_module(topic, "0") is None
    assert navigation.resolve_module(topic, "99") is None
    assert navigation.resolve_module(topic, "第九课") is None
    # Two numerals in one phrase are ambiguous, so nothing is picked.
    assert navigation.resolve_module(topic, "十二") is None


def test_resolve_module_tolerates_malformed_references_and_topics(store):
    topic = _resolved_topic(store, "stats_101")

    assert navigation.resolve_module(topic, None) is None
    assert navigation.resolve_module(topic, "") is None
    assert navigation.resolve_module(topic, "   ") is None
    # The digit-run rule reads "-1" as 1, so this lands on the first lesson
    # rather than crashing or inventing a negative position.
    assert navigation.resolve_module(topic, "-1")["module_id"] == "m1"
    assert navigation.resolve_module(topic, 123) is None
    assert navigation.resolve_module({}, "lesson 1") is None
    assert navigation.resolve_module({"modules": None}, "lesson 1") is None


# ── topics that cannot be navigated to ───────────────────────────────────────


def test_a_topic_without_a_map_is_not_a_destination(store):
    _create_topic("empty_101", modules=[])

    assert navigation.topic_cards()["topics"] == []
    assert navigation.find_topic("empty_101") is None


def test_find_topic_misses_an_unknown_path_without_inventing_a_card(store):
    assert navigation.find_topic("ghost_path") is None


# ── the mount gate fails closed ──────────────────────────────────────────────


def test_the_gate_fails_closed_when_the_store_raises(tmp_path, monkeypatch):
    db_path = tmp_path / "learning" / "mastery" / "mastery.sqlite3"
    db_path.parent.mkdir(parents=True)
    db_path.touch()
    monkeypatch.setattr(LearningStore, "default_db_path", staticmethod(lambda: db_path))

    def _broken_init(self, root=None):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(LearningStore, "__init__", _broken_init)

    assert navigation.learner_has_topics() is False


# ── topic sessions: ordering, pending flag, malformed rows ───────────────────


class _FakeMasteryStore:
    def __init__(self, session_ids, active_session_id=None):
        self._session_ids = list(session_ids)
        self._active = SimpleNamespace(session_id=active_session_id) if active_session_id else None

    def list_session_ids(self, path_id):
        return list(self._session_ids)

    def get_active_interaction(self, path_id):
        return self._active


class _FakeSessionStore:
    def __init__(self, summaries):
        self._summaries = list(summaries)

    async def get_session_summaries(self, session_ids):
        return list(self._summaries)


def _mount_session_store(monkeypatch, summaries):
    fake = _FakeSessionStore(summaries)
    monkeypatch.setattr("deeptutor.services.session.get_session_store", lambda: fake)
    return fake


@pytest.mark.asyncio
async def test_topic_sessions_order_newest_first_and_flag_the_pending_one(
    monkeypatch,
):
    _mount_session_store(
        monkeypatch,
        [
            {"session_id": "s1", "updated_at": 30, "title": "Newest"},
            {"session_id": "s2", "updated_at": 10, "title": "Oldest"},
            {"session_id": "s3", "updated_at": 20, "title": "Middle"},
        ],
    )
    mastery_store = _FakeMasteryStore(["s1", "s2", "s3"], active_session_id="s2")

    rows = await navigation.topic_sessions("stats_101", store=mastery_store)

    assert [row["session_id"] for row in rows] == ["s1", "s3", "s2"]
    assert [row["has_pending_question"] for row in rows] == [
        False,
        False,
        True,
    ]


@pytest.mark.asyncio
async def test_topic_sessions_clips_a_runaway_last_message_and_fills_defaults(
    monkeypatch,
):
    _mount_session_store(
        monkeypatch,
        [
            {
                "id": "s9",
                "session_id": None,
                "last_message": "x" * 300,
                "message_count": None,
                "preferences": None,
            }
        ],
    )

    rows = await navigation.topic_sessions("stats_101", store=_FakeMasteryStore(["s9"]))

    assert len(rows) == 1
    row = rows[0]
    assert row["session_id"] == "s9"
    assert row["title"] == ""
    assert row["status"] == "idle"
    assert row["message_count"] == 0
    assert row["last_message"] == "x" * 240
    assert row["pinned"] is False
    assert row["archived"] is False
    assert row["has_pending_question"] is False


@pytest.mark.asyncio
async def test_topic_sessions_return_nothing_without_sessions():
    rows = await navigation.topic_sessions("stats_101", store=_FakeMasteryStore([]))

    assert rows == []


# ── the REST session shape: archived dropped, caps, flags ────────────────────


def _session_row(session_id, *, archived=False, **overrides):
    row = {
        "session_id": session_id,
        "title": f"S{session_id}",
        "created_at": 0,
        "updated_at": 0,
        "status": "idle",
        "active_turn_id": "",
        "message_count": 1,
        "last_message": "hello",
        "pinned": False,
        "archived": archived,
        "has_pending_question": False,
    }
    row.update(overrides)
    return row


def test_navigable_session_rows_drop_archived_and_page_forward():
    rows = [_session_row(f"live_{i}") for i in range(navigation.SESSION_LIMIT + 5)] + [
        _session_row("gone_1", archived=True),
        _session_row("gone_2", archived=True),
    ]

    payload = navigation.navigable_session_rows(rows)

    assert len(payload["sessions"]) == navigation.SESSION_LIMIT
    assert payload["total_sessions"] == navigation.SESSION_LIMIT + 5
    assert payload["sessions_omitted"] == 5
    assert not any(row["session_id"].startswith("gone_") for row in payload["sessions"])


def test_navigable_session_rows_at_exactly_the_cap_omit_nothing():
    rows = [_session_row(f"s{i}") for i in range(navigation.SESSION_LIMIT)]

    payload = navigation.navigable_session_rows(rows)

    assert payload["total_sessions"] == navigation.SESSION_LIMIT
    assert len(payload["sessions"]) == navigation.SESSION_LIMIT
    assert "sessions_omitted" not in payload


def test_navigable_session_rows_flag_running_and_clip_the_reminder():
    rows = [
        _session_row("running_by_status", status="running"),
        _session_row("running_by_turn", active_turn_id="t9"),
        _session_row("sleepy", has_pending_question=True, last_message="y" * 200),
    ]

    payload = navigation.navigable_session_rows(rows)

    by_id = {row["session_id"]: row for row in payload["sessions"]}
    assert by_id["running_by_status"]["running"] is True
    assert by_id["running_by_turn"]["running"] is True
    assert by_id["sleepy"]["running"] is False
    assert by_id["sleepy"]["awaiting_answer"] is True
    assert by_id["sleepy"]["last_message"] == "y" * navigation.LAST_MESSAGE_CHARS
