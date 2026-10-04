"""Focused tests for the mastery path composer's dynamic question."""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace

import pytest

from deeptutor.learning import policy as learning_policy
from deeptutor.learning import storage as learning_storage
from deeptutor.services import mastery_hints
from deeptutor.services.model_selection import tasks as model_tasks


@pytest.fixture(autouse=True)
def clear_hint_state() -> None:
    mastery_hints._cache.clear()
    mastery_hints._inflight.clear()


def _material(**overrides: object) -> mastery_hints._Material:
    values: dict[str, object] = {
        "path_name": "Networking Basics",
        "goal": "Understand how packets find their way",
        "module_name": "Routing",
        "waypoint": "Why routers match on intent",
        "waypoint_type": "concept",
        "status": "learning",
        "transcript": [
            ("user", "How does a router decide where to send a packet?"),
            ("assistant", "It matches the destination against its forwarding table."),
        ],
        "anchor": "kp-router:2",
    }
    values.update(overrides)
    return mastery_hints._Material(**values)


def _patch_llm(monkeypatch: pytest.MonkeyPatch, *responses: str) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    async def fake_complete(**kwargs: object) -> str:
        calls.append(kwargs)
        return responses[len(calls) - 1] if len(calls) <= len(responses) else responses[-1]

    monkeypatch.setattr("deeptutor.services.llm.complete", fake_complete)
    return calls


def _patch_language(monkeypatch: pytest.MonkeyPatch, language: str | Exception) -> None:
    def fake_language(default: str = "en") -> str:
        if isinstance(language, Exception):
            raise language
        return language

    monkeypatch.setattr(
        "deeptutor.services.settings.interface_settings.get_response_language", fake_language
    )


def _patch_collect(monkeypatch: pytest.MonkeyPatch, material: mastery_hints._Material) -> None:
    async def collect(_path_id: str, _session_id: str) -> mastery_hints._Material:
        return material

    monkeypatch.setattr(mastery_hints, "_collect", collect)


# ── _sanitize: the question mark is the gate ────────────────────────────


def test_sanitize_keeps_a_question() -> None:
    assert (
        mastery_hints._sanitize("Why does the router need the intent?", "en")
        == "Why does the router need the intent?"
    )
    assert mastery_hints._sanitize("路由为什么需要意图？", "zh") == "路由为什么需要意图？"


def test_sanitize_rejects_non_question_output() -> None:
    assert mastery_hints._sanitize("Routing picks the tool by intent.", "en") == ""
    assert mastery_hints._sanitize("路由按意图选工具。", "zh") == ""
    assert mastery_hints._sanitize("", "en") == ""
    assert mastery_hints._sanitize("   ", "en") == ""
    assert mastery_hints._sanitize(None, "en") == ""


def test_sanitize_strips_fences_quotes_and_bullets() -> None:
    assert mastery_hints._sanitize('"Why does routing need intent?"', "en") == (
        "Why does routing need intent?"
    )
    assert mastery_hints._sanitize("「路由为什么需要意图？」", "zh") == "路由为什么需要意图？"
    assert mastery_hints._sanitize("- Why does routing need intent?", "en") == (
        "Why does routing need intent?"
    )
    assert mastery_hints._sanitize("# Why does routing need intent?", "en") == (
        "Why does routing need intent?"
    )
    assert mastery_hints._sanitize("```Why does routing need intent?```", "en") == (
        "Why does routing need intent?"
    )


def test_sanitize_normalizes_whitespace_and_joins_lines() -> None:
    assert mastery_hints._sanitize("  Why   does  it  route?  ", "en") == "Why does it route?"
    # The transcript tail is collapsed before the newline check, so a
    # multi-line answer survives only when the joined text still ends in "?".
    assert mastery_hints._sanitize(
        "Routing picks by intent.\nWhy does it need the intent?", "en"
    ) == ("Routing picks by intent. Why does it need the intent?")
    assert mastery_hints._sanitize("First line\nsecond line.", "en") == ""


def test_sanitize_enforces_per_language_length_limit() -> None:
    long_en = "Why does the router need the intent? " * 4  # > 110 chars
    assert len(long_en.rstrip()) > mastery_hints._MAX_HINT_CHARS["en"]
    assert mastery_hints._sanitize(long_en, "en") == ""

    long_zh = "路由" * 23 + "为什么需要意图？"  # > 44 chars
    assert len(long_zh) > mastery_hints._MAX_HINT_CHARS["zh"]
    assert mastery_hints._sanitize(long_zh, "zh") == ""
    # The same string under the english bound is well within it.
    assert mastery_hints._sanitize(long_zh, "en") == long_zh


# ── _render: what the model is told ─────────────────────────────────────


def test_render_english_structure() -> None:
    text = mastery_hints._render(_material(), zh=False)
    assert "# Topic\nNetworking Basics" in text
    assert "# Goal\nUnderstand how packets find their way" in text
    assert "# Current waypoint\nWhy routers match on intent" in text
    assert "(module: Routing)" in text
    assert "\nType: concept" in text
    assert "\nStatus: learning" in text
    assert "[Learner] How does a router decide where to send a packet?" in text
    assert "[Tutor] It matches the destination against its forwarding table." in text
    assert "# End of the conversation" in text
    assert text.endswith("Write that one question.")


def test_render_chinese_structure() -> None:
    text = mastery_hints._render(_material(), zh=True)
    assert "# 学习主题\nNetworking Basics" in text
    assert "# 学习目标\nUnderstand how packets find their way" in text
    assert "# 当前知识点\nWhy routers match on intent" in text
    assert "（所属模块：Routing）" in text
    assert "\n类型：concept" in text
    assert "\n掌握状态：learning" in text
    assert "[学习者] How does a router decide where to send a packet?" in text
    assert "[导师] It matches the destination against its forwarding table." in text
    assert "# 对话结尾" in text
    assert text.endswith("请写出那一个问题。")


def test_render_omits_goal_when_empty() -> None:
    en = mastery_hints._render(_material(goal=""), zh=False)
    assert "# Goal" not in en
    zh = mastery_hints._render(_material(goal=""), zh=True)
    assert "# 学习目标" not in zh


def test_render_opening_question_without_transcript() -> None:
    en = mastery_hints._render(_material(transcript=[]), zh=False)
    assert "(Nothing yet — this is their opening question.)" in en
    zh = mastery_hints._render(_material(transcript=[]), zh=True)
    assert "（还没开始，这是他要问的第一个问题。）" in zh


def test_ask_hint_to_dict_round_trip() -> None:
    hint = mastery_hints.AskHint(
        hint="Why does it route?", knowledge_point_id="kp-router", generated_at=12.5
    )
    assert hint.to_dict() == {
        "hint": "Why does it route?",
        "knowledge_point_id": "kp-router",
        "generated_at": 12.5,
    }


# ── get_ask_hint: triggers, cache, failures ─────────────────────────────


@pytest.mark.asyncio
async def test_no_position_never_calls_the_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_llm(monkeypatch, "should not be reached")
    _patch_collect(monkeypatch, _material(waypoint=""))

    result = await mastery_hints.get_ask_hint("path-1", "session-1")

    assert result["hint"] == ""
    assert result["knowledge_point_id"] == ""
    assert calls == []


@pytest.mark.asyncio
async def test_cache_hit_does_not_invoke_llm_again(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_llm(monkeypatch, "Why does it need the intent?")
    _patch_collect(monkeypatch, _material())
    _patch_language(monkeypatch, "en")

    first = await mastery_hints.get_ask_hint("path-1", "session-1")
    second = await mastery_hints.get_ask_hint("path-1", "session-1")

    assert first == second
    assert first["hint"] == "Why does it need the intent?"
    assert first["knowledge_point_id"] == "kp-router"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_different_conversation_positions_generate_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_llm(monkeypatch, "Why does it need the intent?")
    _patch_collect(monkeypatch, _material())
    _patch_language(monkeypatch, "en")

    await mastery_hints.get_ask_hint("path-1", "session-1")
    await mastery_hints.get_ask_hint("path-1", "session-2")

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_generate_short_circuits_on_empty_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_llm(monkeypatch, "should not be reached")

    result = await mastery_hints._generate("path-1", "session-1", "kp-x:0")

    assert result.hint == ""
    assert result.knowledge_point_id == "kp-x:0"
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [asyncio.TimeoutError(), RuntimeError("model unavailable")],
    ids=["timeout", "failure"],
)
async def test_llm_failure_returns_empty_hint_and_retries_later(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    attempts = 0
    calls: list[dict[str, object]] = []

    async def flaky_complete(**kwargs: object) -> str:
        nonlocal attempts
        attempts += 1
        calls.append(kwargs)
        if attempts == 1:
            raise error
        return "Why does it need the intent?"

    monkeypatch.setattr("deeptutor.services.llm.complete", flaky_complete)
    _patch_collect(monkeypatch, _material())
    _patch_language(monkeypatch, "en")

    first = await mastery_hints.get_ask_hint("path-1", "session-1")
    assert first["hint"] == ""
    assert first["knowledge_point_id"] == "kp-router:2"

    # A failed generation is not cached: the next visit tries again.
    second = await mastery_hints.get_ask_hint("path-1", "session-1")
    assert second["hint"] == "Why does it need the intent?"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_unusable_answer_is_not_cached_next_question_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_llm(monkeypatch, "Routing picks the tool by intent.", "Why does it route?")
    _patch_collect(monkeypatch, _material())
    _patch_language(monkeypatch, "en")

    first = await mastery_hints.get_ask_hint("path-1", "session-1")
    assert first["hint"] == ""

    second = await mastery_hints.get_ask_hint("path-1", "session-1")
    assert second["hint"] == "Why does it route?"

    third = await mastery_hints.get_ask_hint("path-1", "session-1")
    assert third == second
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_generation_crash_returns_empty_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_llm(monkeypatch, "Why does it route?")

    async def collect(_path_id: str, _session_id: str) -> mastery_hints._Material:
        return _material()

    monkeypatch.setattr(mastery_hints, "_collect", collect)
    _patch_language(monkeypatch, "en")

    async def explode(*_args: object) -> mastery_hints.AskHint:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(mastery_hints, "_generate", explode)

    result = await mastery_hints.get_ask_hint("path-1", "session-1")

    assert result["hint"] == ""
    assert result["knowledge_point_id"] == ""


# ── generation: language choice and the mastery task kind ───────────────


@pytest.mark.asyncio
async def test_chinese_language_uses_chinese_prompt_and_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_llm(monkeypatch, "路由为什么需要意图？")
    _patch_collect(monkeypatch, _material())
    _patch_language(monkeypatch, "zh")

    result = await mastery_hints.get_ask_hint("path-1", "session-1")

    assert result["hint"] == "路由为什么需要意图？"
    assert calls[0]["system_prompt"] == mastery_hints._SYSTEM_ZH
    assert "# 学习主题" in str(calls[0]["prompt"])


@pytest.mark.asyncio
async def test_unreadable_language_falls_back_to_english(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_llm(monkeypatch, "Why does it route?")
    _patch_collect(monkeypatch, _material())
    _patch_language(monkeypatch, RuntimeError("no settings"))

    result = await mastery_hints.get_ask_hint("path-1", "session-1")

    assert result["hint"] == "Why does it route?"
    assert calls[0]["system_prompt"] == mastery_hints._SYSTEM_EN


@pytest.mark.asyncio
async def test_generation_runs_on_task_model_with_no_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kinds: list[model_tasks.TaskKind] = []

    @contextlib.contextmanager
    def spy_scope(kind: model_tasks.TaskKind) -> object:
        kinds.append(kind)
        yield None

    monkeypatch.setattr(model_tasks, "task_llm_scope", spy_scope)
    calls = _patch_llm(monkeypatch, "Why does it route?")
    _patch_collect(monkeypatch, _material())
    _patch_language(monkeypatch, "en")

    result = await mastery_hints.get_ask_hint("path-1", "session-1")

    assert kinds == [model_tasks.TaskKind.MASTERY_ASK_HINT]
    assert calls[0]["max_retries"] == 0
    assert calls[0]["max_tokens"] == 120
    assert result["hint"] == "Why does it route?"


def test_mastery_ask_hint_is_registered_on_the_mastery_surface() -> None:
    assert str(model_tasks.TaskKind.MASTERY_ASK_HINT) == "mastery_ask_hint"
    assert model_tasks.TaskKindSpec(model_tasks.TaskKind.MASTERY_ASK_HINT, "mastery") in (
        model_tasks.TASK_KINDS
    )
    assert {"id": "mastery_ask_hint", "group": "mastery"} in model_tasks.task_kind_payload()


# ── inputs: transcript tail and learned position ────────────────────────


@pytest.mark.asyncio
async def test_load_transcript_without_session_is_empty() -> None:
    assert await mastery_hints._load_transcript("") == ([], "")


@pytest.mark.asyncio
@pytest.mark.parametrize("broken", [None, RuntimeError("store down")], ids=["missing", "error"])
async def test_load_transcript_unreadable_session_is_empty(
    monkeypatch: pytest.MonkeyPatch, broken: object
) -> None:
    class _BrokenStore:
        async def get_session_with_messages(self, _session_id: str) -> object:
            if isinstance(broken, Exception):
                raise broken
            return broken

    monkeypatch.setattr("deeptutor.services.session.get_session_store", lambda: _BrokenStore())

    assert await mastery_hints._load_transcript("session-1") == ([], "")


@pytest.mark.asyncio
async def test_load_transcript_filters_roles_truncates_and_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    long_user = "a" * 800 + "?"

    class _Store:
        async def get_session_with_messages(self, _session_id: str) -> dict[str, object]:
            return {
                "messages": [
                    {"role": "system", "content": "hidden"},
                    {"role": "user", "content": "earlier question"},
                    {"role": "assistant", "content": "first answer"},
                    {"role": "tool", "content": "also hidden"},
                    {"role": "user", "content": long_user},
                    {"role": "assistant", "content": "  spaced\tout  "},
                    {"role": "user", "content": "final question?"},
                ]
            }

    monkeypatch.setattr("deeptutor.services.session.get_session_store", lambda: _Store())

    tail, anchor = await mastery_hints._load_transcript("session-1")

    # Five user/assistant messages (system and tool excluded), tail keeps the
    # last four, and content is whitespace-normalized and truncated.
    assert anchor == "5"
    assert len(tail) == 4
    assert tail[0] == ("assistant", "first answer")
    assert tail[1] == ("user", "a" * mastery_hints._MAX_MESSAGE_CHARS)
    assert tail[2] == ("assistant", "spaced out")
    assert tail[3] == ("user", "final question?")


@pytest.mark.asyncio
async def test_collect_composes_anchor_and_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def load_position(_path_id: str) -> tuple[str, str, str, str, str, str, str]:
        return (
            "Networking Basics",
            "goal",
            "Routing",
            "Intent routing",
            "concept",
            "learning",
            "kp-1",
        )

    async def load_transcript(_session_id: str) -> tuple[list[tuple[str, str]], str]:
        return ([("user", "hello?")], "5")

    monkeypatch.setattr(mastery_hints, "_load_position", load_position)
    monkeypatch.setattr(mastery_hints, "_load_transcript", load_transcript)

    material = await mastery_hints._collect("path-1", "session-1")

    assert material.anchor == "kp-1:5"
    assert material.waypoint == "Intent routing"
    assert material.waypoint_type == "concept"
    assert material.status == "learning"
    assert material.transcript == [("user", "hello?")]
    assert bool(material)


def test_load_position_returns_blanks_without_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _EmptyStore:
        def load(self, _path_id: str) -> None:
            return None

    monkeypatch.setattr(learning_storage, "LearningStore", _EmptyStore)

    assert mastery_hints._load_position("path-1") == ("", "", "", "", "", "", "")


def test_load_position_reads_policy_and_prefers_topic_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    progress = object()
    step = SimpleNamespace(
        knowledge_point_id="kp-1",
        knowledge_point_name="Intent routing",
        knowledge_point_type="concept",
        status="learning",
    )
    topic = SimpleNamespace(
        metadata=SimpleNamespace(description="Understand packets", goal="Networking")
    )

    class _FakeStore:
        def load(self, _path_id: str) -> object:
            return progress

        def get_topic(self, _path_id: str, progress: object = None) -> object:
            return topic

    monkeypatch.setattr(learning_storage, "LearningStore", _FakeStore)
    monkeypatch.setattr(learning_policy, "next_objective", lambda _progress: step)
    monkeypatch.setattr(
        learning_policy,
        "find_knowledge_point",
        lambda _progress, _kp_id: (
            SimpleNamespace(name="kp name"),
            "module-1",
            "Routing",
        ),
    )
    monkeypatch.setattr(learning_policy, "path_display_name", lambda _progress: "Networking Basics")

    assert mastery_hints._load_position("path-1") == (
        "Networking Basics",
        "Understand packets",
        "Routing",
        "Intent routing",
        "concept",
        "learning",
        "kp-1",
    )

    # The topic's own name typed twice is not a goal; description wins, and
    # falls back to the goal when there is no description.
    topic.metadata.description = None
    assert mastery_hints._load_position("path-1")[1] == "Networking"
