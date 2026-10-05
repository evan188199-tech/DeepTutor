"""Focused tests for Immersive Reading's dynamic composer question."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from deeptutor.services import reading_hints


@pytest.fixture(autouse=True)
def clear_hint_state() -> None:
    reading_hints._cache.clear()
    reading_hints._inflight.clear()


def _material() -> reading_hints._Material:
    return reading_hints._Material(
        material_id="material-1",
        title="Residual Networks",
        render_mode="pdf",
        locator=7,
        unit_text="A residual block adds its input to the transformed signal.",
        selection="",
        transcript=[],
        transcript_length=2,
    )


def test_sanitize_rejects_non_question_output() -> None:
    assert reading_hints._sanitize("Residual connections stabilize gradients.", "en") == ""
    assert (
        reading_hints._sanitize(
            "Why do I need residual connections?",
            "en",
            "Residual connections are needed to stabilize gradients.",
        )
        == ""
    )
    assert reading_hints._sanitize("Why do I need a residual connection here?", "en")


@pytest.mark.asyncio
async def test_cache_hit_does_not_invoke_llm_again(monkeypatch: pytest.MonkeyPatch) -> None:
    material = _material()
    calls = 0

    async def collect(*_args: object) -> reading_hints._Material:
        return material

    async def call_llm(_material: reading_hints._Material, _language: str) -> str:
        nonlocal calls
        calls += 1
        return "Why do I need a residual connection here?"

    monkeypatch.setattr(reading_hints, "_collect", collect)
    monkeypatch.setattr(reading_hints, "_call_llm", call_llm)
    monkeypatch.setattr(reading_hints, "_response_language", lambda: "en")

    first = await reading_hints.get_ask_hint("workspace-1", locator=7)
    second = await reading_hints.get_ask_hint("workspace-1", locator=7)

    assert first == second
    assert first["hint"] == "Why do I need a residual connection here?"
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [asyncio.TimeoutError(), RuntimeError("model unavailable")],
    ids=["timeout", "failure"],
)
async def test_llm_failure_returns_empty_hint(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    async def collect(*_args: object) -> reading_hints._Material:
        return _material()

    async def fail_llm(_material: reading_hints._Material, _language: str) -> str:
        raise error

    monkeypatch.setattr(reading_hints, "_collect", collect)
    monkeypatch.setattr(reading_hints, "_call_llm", fail_llm)
    monkeypatch.setattr(reading_hints, "_response_language", lambda: "en")

    result = await reading_hints.get_ask_hint("workspace-1", locator=7)

    assert result["hint"] == ""
    assert result["material_id"] == "material-1"


# -- Prompt assembly ----------------------------------------------------------


def test_render_assembles_selection_unit_and_transcript() -> None:
    material = replace(
        _material(),
        selection="the input is added",
        transcript=[
            ("user", "What is a residual block?"),
            ("assistant", "It sums the input with the transform."),
        ],
    )

    en = reading_hints._render(material, zh=False)
    assert "# Active material\nTitle: Residual Networks\nRender mode: pdf" in en
    assert "# Learner's selected quote (strongest signal)\nthe input is added" in en
    assert "# Text near the current location (7)" in en
    assert "[Learner] What is a residual block?" in en
    assert "[Tutor] It sums the input with the transform." in en
    assert en.endswith("Write only that one question.")

    zh = reading_hints._render(material, zh=True)
    assert "# 当前材料\n标题：Residual Networks\n呈现方式：pdf" in zh
    assert "# 学习者刚选中的原文（最强信号）\nthe input is added" in zh
    assert "# 当前位置附近的文字（位置 7）" in zh
    assert "[学习者] What is a residual block?" in zh
    assert "[导师] It sums the input with the transform." in zh
    assert zh.endswith("只写出那一个问题。")

    bare = reading_hints._Material(
        material_id="material-1",
        title="Residual Networks",
        render_mode="text",
        locator=None,
        unit_text="",
        selection="",
        transcript=[],
        transcript_length=0,
    )
    bare_en = reading_hints._render(bare, zh=False)
    assert "selected quote" not in bare_en
    assert "Text near the current location" not in bare_en
    assert "(No conversation yet.)" in bare_en


def test_locator_bucket_groups_positions_into_cache_key() -> None:
    assert reading_hints._locator_bucket(None) == "none"
    assert reading_hints._locator_bucket(0) == "1-5"
    assert reading_hints._locator_bucket(-3) == "1-5"
    assert reading_hints._locator_bucket(5) == "1-5"
    assert reading_hints._locator_bucket(6) == "6-10"

    same_bucket = reading_hints._cache_key("ws", "mat", 7, 3) == reading_hints._cache_key(
        "ws", "mat", 8, 3
    )
    assert same_bucket
    assert reading_hints._cache_key("ws", "mat", 7, 3) != reading_hints._cache_key(
        "ws", "mat", 11, 3
    )
    assert reading_hints._cache_key("ws", "mat", 7, 3) != reading_hints._cache_key(
        "ws", "mat", 7, 4
    )
    assert reading_hints._cache_key("ws", "mat", 7, 3) != reading_hints._cache_key(
        "ws2", "mat", 7, 3
    )


# -- Input anomalies ----------------------------------------------------------


def test_sanitize_normalizes_wrapped_questions() -> None:
    assert (
        reading_hints._sanitize('- "Why do residual networks need shortcuts?"', "en")
        == "Why do residual networks need shortcuts?"
    )
    assert (
        reading_hints._sanitize("为什么  残差网络 需要跳连？", "zh") == "为什么 残差网络 需要跳连？"
    )

    assert reading_hints._sanitize("```Why is the layer skipped?```", "en") == ""
    assert reading_hints._sanitize("Why A?\nWhy B?", "en") == ""
    assert reading_hints._sanitize("Why is A true? And why does B follow?", "en") == ""
    assert (
        reading_hints._sanitize(
            "The author drops the assumption. The proof relies on it later. Why is that allowed?",
            "en",
        )
        == ""
    )


@pytest.mark.parametrize(
    ("raw", "language", "expected"),
    [
        ("Why " + "a" * 105 + "?", "en", True),
        ("Why " + "a" * 106 + "?", "en", False),
        ("为什么" + "这" * 40 + "？", "zh", True),
        ("为什么" + "这" * 41 + "？", "zh", False),
    ],
    ids=["en-limit", "en-over", "zh-limit", "zh-over"],
)
def test_sanitize_enforces_language_length_limits(raw: str, language: str, expected: bool) -> None:
    assert bool(reading_hints._sanitize(raw, language)) is expected


@pytest.mark.asyncio
async def test_load_transcript_filters_roles_and_tails(monkeypatch: pytest.MonkeyPatch) -> None:
    session = {
        "messages": [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "  u1  "},
            {"role": "assistant", "content": "a1"},
            {"role": "tool", "content": "tool output"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "u3"},
            {"role": "assistant", "content": "a3"},
        ]
    }

    class _Store:
        async def get_session_with_messages(self, _session_id: str) -> dict[str, object]:
            return session

    monkeypatch.setattr("deeptutor.services.session.get_session_store", lambda: _Store())

    tail, length = await reading_hints._load_transcript("session-1")

    assert length == 6
    assert tail == [
        ("user", "u2"),
        ("assistant", "a2"),
        ("user", "u3"),
        ("assistant", "a3"),
    ]


@pytest.mark.asyncio
async def test_load_transcript_drops_blank_and_overlong_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = {
        "messages": [
            {"role": "user", "content": "   "},
            {"role": "assistant", "content": "x" * 900},
        ]
    }

    class _Store:
        async def get_session_with_messages(self, _session_id: str) -> dict[str, object]:
            return session

    monkeypatch.setattr("deeptutor.services.session.get_session_store", lambda: _Store())

    tail, length = await reading_hints._load_transcript("session-1")

    assert length == 2
    assert len(tail) == 1
    assert tail[0][0] == "assistant"
    assert len(tail[0][1]) == 700


@pytest.mark.asyncio
async def test_load_transcript_degrades_without_session_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consulted = False

    class _Store:
        async def get_session_with_messages(self, _session_id: str) -> dict[str, object]:
            nonlocal consulted
            consulted = True
            return {"messages": []}

    monkeypatch.setattr("deeptutor.services.session.get_session_store", lambda: _Store())
    assert await reading_hints._load_transcript("") == ([], 0)
    assert consulted is False

    class _Broken:
        async def get_session_with_messages(self, _session_id: str) -> dict[str, object]:
            raise RuntimeError("session store unavailable")

    class _Missing:
        async def get_session_with_messages(self, _session_id: str) -> None:
            return None

    monkeypatch.setattr("deeptutor.services.session.get_session_store", lambda: _Broken())
    assert await reading_hints._load_transcript("session-1") == ([], 0)

    monkeypatch.setattr("deeptutor.services.session.get_session_store", lambda: _Missing())
    assert await reading_hints._load_transcript("session-1") == ([], 0)


@pytest.mark.asyncio
async def test_collect_merges_material_and_transcript(monkeypatch: pytest.MonkeyPatch) -> None:
    def load_material(_workspace_id: str, locator: int | None) -> tuple[str, str, str, str]:
        return ("material-1", "Residual Networks", "pdf", "nearby unit text")

    async def load_transcript(_session_id: str) -> tuple[list[tuple[str, str]], int]:
        return ([("user", "hi")], 5)

    monkeypatch.setattr(reading_hints, "_load_current_material", load_material)
    monkeypatch.setattr(reading_hints, "_load_transcript", load_transcript)

    material = await reading_hints._collect("workspace-1", "session-1", 7, " the  selected text ")

    assert material.material_id == "material-1"
    assert material.title == "Residual Networks"
    assert material.render_mode == "pdf"
    assert material.unit_text == "nearby unit text"
    assert material.locator == 7
    assert material.selection == "the selected text"
    assert material.transcript == [("user", "hi")]
    assert material.transcript_length == 5
    assert bool(material) is True
    assert material.last_answer == ""

    truncated = await reading_hints._collect("workspace-1", "session-1", 7, "s" * 2500)
    assert len(truncated.selection) == reading_hints._MAX_SELECTION_CHARS


def test_material_last_answer_prefers_latest_assistant_turn() -> None:
    material = replace(
        _material(),
        transcript=[("user", "u1"), ("assistant", "a1"), ("user", "u2")],
    )
    assert material.last_answer == "a1"
    assert replace(_material(), transcript=[("user", "u1")]).last_answer == ""


# -- Degradation branches -----------------------------------------------------


@pytest.mark.asyncio
async def test_get_ask_hint_collect_failure_returns_empty_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(*_args: object) -> reading_hints._Material:
        raise RuntimeError("catalog unavailable")

    monkeypatch.setattr(reading_hints, "_collect", boom)

    result = await reading_hints.get_ask_hint("workspace-1", locator=3)

    assert result["hint"] == ""
    assert result["material_id"] == ""
    assert set(result) == {"hint", "material_id", "generated_at"}


@pytest.mark.asyncio
async def test_get_ask_hint_missing_material_skips_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def collect(*_args: object) -> reading_hints._Material:
        return reading_hints._Material(
            material_id="",
            title="",
            render_mode="",
            locator=None,
            unit_text="",
            selection="",
            transcript=[],
            transcript_length=0,
        )

    async def call_llm(_material: reading_hints._Material, _language: str) -> str:
        nonlocal calls
        calls += 1
        return "Why?"

    monkeypatch.setattr(reading_hints, "_collect", collect)
    monkeypatch.setattr(reading_hints, "_call_llm", call_llm)

    result = await reading_hints.get_ask_hint("workspace-1", locator=3)

    assert calls == 0
    assert result["hint"] == ""
    assert result["material_id"] == ""


@pytest.mark.asyncio
async def test_get_ask_hint_selection_bypasses_cache_and_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = replace(_material(), selection="the skip connection")
    calls = 0

    async def collect(*_args: object) -> reading_hints._Material:
        return material

    async def call_llm(_material: reading_hints._Material, _language: str) -> str:
        nonlocal calls
        calls += 1
        return "Why does the selected layer keep its input?"

    monkeypatch.setattr(reading_hints, "_collect", collect)
    monkeypatch.setattr(reading_hints, "_call_llm", call_llm)
    monkeypatch.setattr(reading_hints, "_response_language", lambda: "en")

    first = await reading_hints.get_ask_hint("workspace-1", locator=7)
    second = await reading_hints.get_ask_hint("workspace-1", locator=7)

    assert calls == 2
    assert first["hint"] == second["hint"] == "Why does the selected layer keep its input?"
    assert len(reading_hints._cache) == 0

    async def answerish_llm(_material: reading_hints._Material, _language: str) -> str:
        return "The selection shows that skip connections help."

    monkeypatch.setattr(reading_hints, "_call_llm", answerish_llm)
    degraded = await reading_hints.get_ask_hint("workspace-1", locator=7)

    assert degraded["hint"] == ""
    assert degraded["material_id"] == "material-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "question", "expected"),
    [
        (
            "en",
            "Why do residual blocks stabilize training in deep networks?",
            "",
        ),
        (
            "en",
            "Why does the identity path help early training at all?",
            "Why does the identity path help early training at all?",
        ),
        ("zh", "残差连接为什么可以让深层网络更容易训练？", ""),
        ("zh", "残差连接对训练速度的影响在哪里体现？", "残差连接对训练速度的影响在哪里体现？"),
    ],
    ids=["en-repeat", "en-fresh", "zh-repeat", "zh-fresh"],
)
async def test_generate_filters_repeats_of_last_answer(
    monkeypatch: pytest.MonkeyPatch,
    language: str,
    question: str,
    expected: str,
) -> None:
    last_answer = (
        "Residual blocks stabilize training by keeping identity paths in deep networks."
        if language == "en"
        else "残差连接可以让深层网络更容易训练"
    )
    material = replace(
        _material(),
        transcript=[("assistant", last_answer)],
    )

    async def call_llm(_material: reading_hints._Material, _language: str) -> str:
        return question

    monkeypatch.setattr(reading_hints, "_call_llm", call_llm)
    monkeypatch.setattr(reading_hints, "_response_language", lambda: language)

    result = await reading_hints._generate(material)

    assert result.hint == expected
    assert result.material_id == "material-1"


def test_response_language_failure_falls_back_to_english(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("settings unavailable")

    monkeypatch.setattr(
        "deeptutor.services.settings.interface_settings.get_response_language", boom
    )

    assert reading_hints._response_language() == "en"
