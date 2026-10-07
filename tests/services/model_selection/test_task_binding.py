"""Task→model binding resolution in ``model_selection.tasks``, pure catalog level.

Covers: valid pins per mode, every shape of absent/malformed override reading as
absent, and the catalog rewrite ``catalog_for_task`` performs without touching
the stored catalog. No catalog service, no network.
"""

from __future__ import annotations

from typing import Any

from deeptutor.services.model_selection.tasks import (
    TASK_KINDS,
    TASK_MODES,
    TaskKind,
    catalog_for_task,
    task_kind_payload,
    task_override,
)

_PROFILE_PIN = {
    "mode": "profiles",
    "active_profile_id": "task-1",
    "active_model_id": "task-nano",
}


def _catalog(**task: Any) -> dict[str, Any]:
    return {
        "services": {
            "llm": {
                "active_profile_id": "chat-1",
                "active_model_id": "chat-model",
                "profiles": [
                    {
                        "id": "chat-1",
                        "binding": "openai",
                        "api_key": "sk-chat",
                        "models": [{"id": "chat-model", "model": "gpt-5"}],
                    }
                ],
            },
            "task": {
                "active_profile_id": "task-1",
                "active_model_id": "task-model",
                "profiles": [
                    {
                        "id": "task-1",
                        "binding": "openai",
                        "api_key": "sk-task",
                        "models": [
                            {"id": "task-model", "model": "gpt-5-mini"},
                            {"id": "task-nano", "model": "gpt-5-nano"},
                        ],
                    }
                ],
                **task,
            },
        }
    }


class TestTaskOverride:
    def test_none_kind_is_always_absent(self) -> None:
        assert task_override(_catalog(overrides={"session_title": _PROFILE_PIN}), None) is None

    def test_string_kind_resolves_like_the_enum_member(self) -> None:
        catalog = _catalog(overrides={"reading_quiz": _PROFILE_PIN})

        assert task_override(catalog, TaskKind.READING_QUIZ) == _PROFILE_PIN
        assert task_override(catalog, "reading_quiz") == _PROFILE_PIN

    def test_missing_or_non_dict_overrides_key_reads_as_absent(self) -> None:
        assert task_override(_catalog(), TaskKind.SESSION_TITLE) is None
        assert task_override(_catalog(overrides=["not", "a", "dict"]), TaskKind.SESSION_TITLE) is (
            None
        )

    def test_malformed_override_shapes_read_as_absent(self) -> None:
        catalog = _catalog(
            overrides={
                "session_title": "gpt-5-nano",
                "chat_starters": {"mode": "global"},
                "chat_ask_hint": {"mode": "reference"},
                "mastery_goal_name": {"mode": "reference", "selection": None},
                "mastery_ask_hint": {"mode": "profiles", "active_profile_id": "task-1"},
                "reading_quiz": {"mode": "profiles", "active_model_id": "task-nano"},
            }
        )

        for kind in (
            TaskKind.SESSION_TITLE,
            TaskKind.CHAT_STARTERS,
            TaskKind.CHAT_ASK_HINT,
            TaskKind.MASTERY_GOAL_NAME,
            TaskKind.MASTERY_ASK_HINT,
            TaskKind.READING_QUIZ,
        ):
            assert task_override(catalog, kind) is None, kind


class TestCatalogForTask:
    def test_absent_override_returns_the_same_catalog(self) -> None:
        catalog = _catalog()

        assert catalog_for_task(catalog, TaskKind.SESSION_TITLE) is catalog

    def test_profiles_pin_rewrites_the_task_service_copy(self) -> None:
        catalog = _catalog(overrides={"reading_translation": _PROFILE_PIN})

        patched = catalog_for_task(catalog, TaskKind.READING_TRANSLATION)

        assert patched is not catalog
        task = patched["services"]["task"]
        assert task["mode"] == "profiles"
        assert task["active_profile_id"] == "task-1"
        assert task["active_model_id"] == "task-nano"
        assert "selection" not in task
        # The stored catalog keeps the global choice.
        assert catalog["services"]["task"]["active_model_id"] == "task-model"
        assert "mode" not in catalog["services"]["task"]

    def test_reference_pin_copies_the_selection_isolation(self) -> None:
        selection = {"profile_id": "chat-1", "model_id": "chat-model"}
        catalog = _catalog(
            overrides={"session_title": {"mode": "reference", "selection": selection}}
        )

        patched = catalog_for_task(catalog, TaskKind.SESSION_TITLE)
        patched["services"]["task"]["selection"]["model_id"] = "mutated"

        assert catalog["services"]["task"]["overrides"]["session_title"]["selection"] == selection

    def test_missing_task_service_reads_as_no_override(self) -> None:
        catalog = {"services": {"llm": {"profiles": []}}}

        assert task_override(catalog, TaskKind.READING_QUIZ) is None
        assert catalog_for_task(catalog, TaskKind.READING_QUIZ) is catalog

    def test_service_that_is_not_a_dict_reads_as_no_override(self) -> None:
        catalog = {"services": {"task": ["not", "a", "dict"]}}

        assert task_override(catalog, TaskKind.READING_QUIZ) is None
        assert catalog_for_task(catalog, TaskKind.READING_QUIZ) is catalog


class TestKindVocabulary:
    def test_payload_lists_every_kind_with_its_group_in_order(self) -> None:
        payload = task_kind_payload()

        assert payload == [{"id": str(spec.kind), "group": spec.group} for spec in TASK_KINDS]
        assert [entry["id"] for entry in payload][0] == str(TaskKind.SESSION_TITLE)

    def test_task_modes_are_exactly_the_three_documented_ones(self) -> None:
        assert TASK_MODES == frozenset({"inherit", "reference", "profiles"})
