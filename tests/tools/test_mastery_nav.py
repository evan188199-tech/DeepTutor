"""Regression cover for the mastery navigation tools (``tools/mastery_nav``).

These four tools resolve fuzzy learner references against the mastery atlas
and hand back frontend cards. Two contracts matter enough to pin:

* **Resolve, then hand off** — every id on a card is validated against the
  store first, and a bad reference fails with the ids to try instead.
* **Never re-enter the topic you are teaching** — ``mastery_new_session``
  must refuse a card for the topic of the current session (#1412/#1411),
  while a card for a *different* topic still works.

The store-facing ``navigation`` helpers are stubbed per test; the pure
resolvers (``resolve_module``, ``navigable_session_rows``) run for real.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from deeptutor.core.tool_protocol import ToolPromptHints
from deeptutor.learning import navigation
from deeptutor.tools.mastery_nav import (
    HANDOFF_META_KEY,
    MASTERY_NAV_TOOL_NAMES,
    MASTERY_NAV_TOOL_TYPES,
    MasteryNewSessionTool,
    MasteryOpenSessionTool,
    MasterySessionsTool,
    MasteryTopicsTool,
)


def _topic() -> dict[str, Any]:
    return {
        "path_id": "path-stats",
        "name": "Statistics",
        "emoji": "📊",
        "modules": [
            {"module_id": "m1", "name": "Descriptive Stats", "order": 1},
            {"module_id": "m2", "name": "Probability", "order": 2},
        ],
        "due_reviews": 3,
        "mastered": 5,
        "objectives": 8,
    }


def _session_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "session_id": "sess-1",
        "title": "Lesson 1 review",
        "created_at": 1.0,
        "updated_at": 20.0,
        "status": "idle",
        "active_turn_id": "",
        "message_count": 4,
        "last_message": "what is a median?",
        "pinned": False,
        "archived": False,
        "has_pending_question": True,
    }
    row.update(overrides)
    return row


@pytest.fixture
def patch_nav(monkeypatch: pytest.MonkeyPatch):
    def _patch(
        *,
        topic: dict[str, Any] | None = None,
        rows: list[dict[str, Any]] | None = None,
        cards: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        seen: dict[str, Any] = {}

        def _find_topic(ref: str, **_: Any) -> dict[str, Any] | None:
            seen["find_topic_ref"] = ref
            return dict(topic) if topic is not None else None

        async def _topic_sessions(path_id: str, **_: Any) -> list[dict[str, Any]]:
            seen["sessions_path_id"] = path_id
            return list(rows or [])

        def _topic_cards(**kwargs: Any) -> dict[str, Any]:
            seen["cards_query"] = kwargs.get("query")
            return cards or {"topics": [], "query": kwargs.get("query", "")}

        monkeypatch.setattr(navigation, "find_topic", _find_topic)
        monkeypatch.setattr(navigation, "topic_sessions", _topic_sessions)
        monkeypatch.setattr(navigation, "topic_cards", _topic_cards)
        return seen

    return _patch


def test_tool_registry_names_match_the_definitions() -> None:
    assert (
        tuple(tool().get_definition().name for tool in MASTERY_NAV_TOOL_TYPES)
        == MASTERY_NAV_TOOL_NAMES
    )


@pytest.mark.parametrize("tool_type", MASTERY_NAV_TOOL_TYPES)
@pytest.mark.parametrize("language", ["en", "zh"])
def test_prompt_hints_load_from_yaml(tool_type: type, language: str) -> None:
    hints = tool_type().get_prompt_hints(language)
    assert isinstance(hints, ToolPromptHints)
    assert hints.short_description


# --- mastery_topics -----------------------------------------------------------


@pytest.mark.asyncio
async def test_topics_lists_cards_with_resolution_instruction(patch_nav) -> None:
    cards = {"topics": [{"path_id": "path-stats", "name": "Statistics"}], "query": ""}
    patch_nav(cards=cards)
    result = await MasteryTopicsTool().execute(query="stats")
    assert result.success
    payload = result.metadata["mastery_topics"]
    assert payload["topics"] == cards["topics"]
    assert "path_id" in payload["instruction"]


@pytest.mark.asyncio
async def test_topics_with_no_match_suggests_dropping_the_filter(patch_nav) -> None:
    patch_nav(cards={"topics": [], "query": "calculus"})
    result = await MasteryTopicsTool().execute(query="calculus")
    assert result.success
    assert "no query" in result.metadata["mastery_topics"]["instruction"]


@pytest.mark.asyncio
async def test_topics_for_a_learner_with_no_topics_says_so(patch_nav) -> None:
    patch_nav(cards={"topics": [], "query": ""})
    result = await MasteryTopicsTool().execute()
    assert result.success
    assert "no mastery topics yet" in result.metadata["mastery_topics"]["instruction"]


@pytest.mark.asyncio
async def test_topics_normalizes_the_query_before_filtering(patch_nav) -> None:
    seen = patch_nav(cards={"topics": [{"path_id": "p"}], "query": ""})
    await MasteryTopicsTool().execute(query="  stats \n course ")
    assert seen["cards_query"] == "stats course"


# --- mastery_sessions ---------------------------------------------------------


@pytest.mark.asyncio
async def test_sessions_requires_a_topic_id(patch_nav) -> None:
    result = await MasterySessionsTool().execute(path_id="   ")
    assert not result.success
    assert "path_id is required" in result.content


@pytest.mark.asyncio
async def test_sessions_unknown_topic_names_the_typo(patch_nav) -> None:
    patch_nav(topic=None)
    result = await MasterySessionsTool().execute(path_id="path-nope")
    assert not result.success
    assert "path-nope" in result.content
    assert "mastery_topics" in result.content


@pytest.mark.asyncio
async def test_sessions_lists_live_conversations_and_drops_archived(patch_nav) -> None:
    seen = patch_nav(
        topic=_topic(),
        rows=[
            _session_row(),
            _session_row(session_id="sess-old", archived=True, has_pending_question=False),
        ],
    )
    result = await MasterySessionsTool().execute(path_id="path-stats")
    assert result.success
    payload = result.metadata["mastery_sessions"]
    assert seen["sessions_path_id"] == "path-stats"
    assert [s["session_id"] for s in payload["sessions"]] == ["sess-1"]
    assert payload["sessions"][0]["awaiting_answer"] is True
    assert "mastery_open_session" in payload["instruction"]


@pytest.mark.asyncio
async def test_sessions_on_an_untouched_topic_offers_the_first_session(patch_nav) -> None:
    patch_nav(topic=_topic(), rows=[])
    result = await MasterySessionsTool().execute(path_id="path-stats")
    assert result.success
    assert "mastery_new_session" in result.metadata["mastery_sessions"]["instruction"]


# --- mastery_open_session -----------------------------------------------------


@pytest.mark.asyncio
async def test_open_session_builds_a_validated_handoff_card(patch_nav) -> None:
    patch_nav(topic=_topic(), rows=[_session_row()])
    result = await MasteryOpenSessionTool().execute(
        path_id="path-stats",
        session_id="sess-1",
        module="lesson 2",
        opening_message="Review probability with me",
        reason="they asked to continue",
    )
    assert result.success
    payload = result.metadata[HANDOFF_META_KEY]
    assert payload["kind"] == "open"
    assert payload["path_id"] == "path-stats"
    assert payload["path_name"] == "Statistics"
    assert payload["session_id"] == "sess-1"
    assert payload["session_messages"] == 4
    assert payload["session_awaiting"] is True
    assert payload["session_running"] is False
    assert payload["module_id"] == "m2"
    assert payload["module_name"] == "Probability"
    assert payload["opening_message"] == "Review probability with me"
    assert payload["instruction"]


@pytest.mark.asyncio
async def test_open_session_handoff_content_is_valid_json(patch_nav) -> None:
    patch_nav(topic=_topic(), rows=[_session_row()])
    result = await MasteryOpenSessionTool().execute(path_id="path-stats", session_id="sess-1")
    decoded = json.loads(result.content)
    assert decoded["path_id"] == "path-stats"
    assert decoded["session_id"] == "sess-1"


@pytest.mark.asyncio
async def test_open_session_requires_a_session_id(patch_nav) -> None:
    patch_nav(topic=_topic(), rows=[_session_row()])
    result = await MasteryOpenSessionTool().execute(path_id="path-stats", session_id="")
    assert not result.success
    assert "session_id is required" in result.content


@pytest.mark.asyncio
async def test_open_session_rejects_a_conversation_from_another_topic(patch_nav) -> None:
    patch_nav(topic=_topic(), rows=[_session_row()])
    result = await MasteryOpenSessionTool().execute(path_id="path-stats", session_id="sess-other")
    assert not result.success
    assert "sess-other" in result.content


@pytest.mark.asyncio
async def test_open_session_unknown_module_lists_the_lessons(patch_nav) -> None:
    patch_nav(topic=_topic(), rows=[_session_row()])
    result = await MasteryOpenSessionTool().execute(
        path_id="path-stats", session_id="sess-1", module="calculus"
    )
    assert not result.success
    assert "1. Descriptive Stats (m1)" in result.content
    assert "2. Probability (m2)" in result.content


@pytest.mark.asyncio
async def test_open_session_resolves_a_module_by_name_substring(patch_nav) -> None:
    patch_nav(topic=_topic(), rows=[_session_row()])
    result = await MasteryOpenSessionTool().execute(
        path_id="path-stats", session_id="sess-1", module="descriptive"
    )
    assert result.success
    assert result.metadata[HANDOFF_META_KEY]["module_id"] == "m1"


# --- mastery_new_session ------------------------------------------------------


@pytest.mark.asyncio
async def test_new_session_refuses_a_card_for_the_topic_already_being_taught(patch_nav) -> None:
    patch_nav(topic=_topic())
    result = await MasteryNewSessionTool().execute(
        path_id="path-stats", _tutoring_path_id="path-stats"
    )
    assert not result.success
    assert "already the study session" in result.content


@pytest.mark.asyncio
async def test_new_session_still_allows_a_different_topic(patch_nav) -> None:
    patch_nav(topic=_topic())
    result = await MasteryNewSessionTool().execute(
        path_id="path-stats", _tutoring_path_id="path-algebra"
    )
    assert result.success
    payload = result.metadata[HANDOFF_META_KEY]
    assert payload["kind"] == "new"
    assert payload["path_id"] == "path-stats"
    # No session exists yet: the card carries empty hand-off placeholders.
    assert payload["session_id"] == ""
    assert payload["session_messages"] == 0
    assert payload["session_awaiting"] is False
    assert payload["session_running"] is False


@pytest.mark.asyncio
async def test_new_session_without_a_tutoring_context_is_allowed(patch_nav) -> None:
    patch_nav(topic=_topic())
    result = await MasteryNewSessionTool().execute(path_id="path-stats")
    assert result.success
    assert result.metadata[HANDOFF_META_KEY]["kind"] == "new"


@pytest.mark.asyncio
async def test_new_session_carries_topic_progress_numbers(patch_nav) -> None:
    patch_nav(topic=_topic())
    result = await MasteryNewSessionTool().execute(path_id="path-stats")
    payload = result.metadata[HANDOFF_META_KEY]
    assert payload["due_reviews"] == 3
    assert payload["mastered"] == 5
    assert payload["objectives"] == 8
