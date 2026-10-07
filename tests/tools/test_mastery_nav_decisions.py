"""Decision-path cover for the mastery navigation tools (``tools/mastery_nav``).

Where the module's card-shape cover pins the happy hand-off, this file pins
the three decision areas a model's raw arguments stress most:

* **Input normalization** — model-supplied ids, lesson references and card
  copy arrive padded, multi-line or ``None``; every one still lands resolved.
* **Loop / out-of-bounds targets** — a card back into the topic already being
  taught is refused (the refusal wins over module validation), while lesson
  positions beyond the outline fail instead of wrapping around.
* **No-progress-data fallbacks** — topics without an outline or progress
  numbers, and sessions without progress metadata, still produce defaulted,
  well-formed cards.

The store-facing ``navigation`` helpers are stubbed per test; the pure
``resolve_module`` runs for real.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.learning import navigation
from deeptutor.tools.mastery_nav import (
    HANDOFF_META_KEY,
    MasteryNewSessionTool,
    MasteryOpenSessionTool,
    MasteryTopicsTool,
)


def _topic(**overrides: Any) -> dict[str, Any]:
    topic: dict[str, Any] = {
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
    topic.update(overrides)
    return topic


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


# --- input normalization ------------------------------------------------------


@pytest.mark.asyncio
async def test_open_session_normalizes_padded_ids_and_multiline_card_copy(
    patch_nav,
) -> None:
    patch_nav(topic=_topic(), rows=[{"session_id": "sess-1", "message_count": 2}])
    result = await MasteryOpenSessionTool().execute(
        path_id="  path-stats \n",
        session_id=" sess-1 ",
        module=" m2 ",
        opening_message="Review\n  lesson 2\twith me",
        reason="  picking up where they left off ",
    )
    assert result.success
    payload = result.metadata[HANDOFF_META_KEY]
    assert payload["path_id"] == "path-stats"
    assert payload["session_id"] == "sess-1"
    assert payload["module_id"] == "m2"
    assert payload["opening_message"] == "Review lesson 2 with me"
    assert payload["reason"] == "picking up where they left off"


@pytest.mark.asyncio
async def test_topics_treats_a_none_query_as_no_filter(patch_nav) -> None:
    seen = patch_nav(cards={"topics": [{"path_id": "p"}], "query": ""})
    result = await MasteryTopicsTool().execute(query=None)
    assert result.success
    assert seen["cards_query"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("ref", ["2", "lesson 2", "第2课"])
async def test_open_session_resolves_a_module_by_its_position_phrase(patch_nav, ref: str) -> None:
    patch_nav(topic=_topic(), rows=[{"session_id": "sess-1"}])
    result = await MasteryOpenSessionTool().execute(
        path_id="path-stats", session_id="sess-1", module=ref
    )
    assert result.success
    assert result.metadata[HANDOFF_META_KEY]["module_id"] == "m2"


# --- loop / out-of-bounds targets ----------------------------------------------


@pytest.mark.asyncio
async def test_new_session_loop_guard_normalizes_the_current_topic_id(patch_nav) -> None:
    patch_nav(topic=_topic())
    result = await MasteryNewSessionTool().execute(
        path_id="path-stats", _tutoring_path_id="  path-stats "
    )
    assert not result.success
    assert "already the study session" in result.content


@pytest.mark.asyncio
async def test_new_session_whitespace_only_tutoring_context_is_no_context(
    patch_nav,
) -> None:
    patch_nav(topic=_topic())
    result = await MasteryNewSessionTool().execute(path_id="path-stats", _tutoring_path_id="   ")
    assert result.success
    assert result.metadata[HANDOFF_META_KEY]["kind"] == "new"


@pytest.mark.asyncio
async def test_new_session_loop_refusal_wins_over_module_validation(patch_nav) -> None:
    patch_nav(topic=_topic())
    result = await MasteryNewSessionTool().execute(
        path_id="path-stats", _tutoring_path_id="path-stats", module="9"
    )
    assert not result.success
    assert "already the study session" in result.content
    assert "lesson" not in result.content.split("already")[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("ref", ["0", "9", "第99课"])
async def test_out_of_bounds_lesson_positions_fail_without_wrapping(patch_nav, ref: str) -> None:
    patch_nav(topic=_topic(), rows=[{"session_id": "sess-1"}])
    result = await MasteryOpenSessionTool().execute(
        path_id="path-stats", session_id="sess-1", module=ref
    )
    assert not result.success
    assert "1. Descriptive Stats (m1)" in result.content
    assert "2. Probability (m2)" in result.content


@pytest.mark.asyncio
async def test_module_ref_on_a_topic_without_an_outline_falls_back_to_none_yet(
    patch_nav,
) -> None:
    patch_nav(topic=_topic(modules=[]), rows=[{"session_id": "sess-1"}])
    result = await MasteryOpenSessionTool().execute(
        path_id="path-stats", session_id="sess-1", module="m1"
    )
    assert not result.success
    assert "none yet" in result.content
    assert "Leave `module` out" in result.content


# --- no-progress-data fallbacks ------------------------------------------------


@pytest.mark.asyncio
async def test_new_session_card_defaults_a_topic_without_progress_numbers(
    patch_nav,
) -> None:
    patch_nav(
        topic={
            "path_id": "path-stats",
            "name": "Statistics",
            "modules": [],
        }
    )
    result = await MasteryNewSessionTool().execute(path_id="path-stats")
    assert result.success
    payload = result.metadata[HANDOFF_META_KEY]
    assert payload["emoji"] == ""
    assert payload["due_reviews"] == 0
    assert payload["mastered"] == 0
    assert payload["objectives"] == 0
    assert payload["session_id"] == ""
    assert payload["module_id"] == ""


@pytest.mark.asyncio
async def test_open_session_defaults_a_session_row_without_progress_metadata(
    patch_nav,
) -> None:
    patch_nav(topic=_topic(), rows=[{"session_id": "sess-1"}])
    result = await MasteryOpenSessionTool().execute(path_id="path-stats", session_id="sess-1")
    assert result.success
    payload = result.metadata[HANDOFF_META_KEY]
    assert payload["session_id"] == "sess-1"
    assert payload["session_title"] == ""
    assert payload["session_messages"] == 0
    assert payload["session_updated_at"] == 0
    assert payload["session_awaiting"] is False
    assert payload["session_running"] is False


@pytest.mark.asyncio
async def test_open_session_module_validation_precedes_the_session_lookup(
    patch_nav,
) -> None:
    patch_nav(topic=_topic(), rows=[])
    result = await MasteryOpenSessionTool().execute(
        path_id="path-stats", session_id="sess-gone", module="calculus"
    )
    assert not result.success
    assert "calculus" in result.content
    assert "sess-gone" not in result.content
