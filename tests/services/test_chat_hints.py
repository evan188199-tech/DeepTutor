"""Focused tests for the home chat's dynamic composer line."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest

from deeptutor.services import chat_hints


@pytest.fixture(autouse=True)
def clear_hint_state() -> None:
    chat_hints._cache.clear()
    chat_hints._inflight.clear()


def _material() -> chat_hints._Material:
    return chat_hints._Material(
        transcript=[
            ("user", "How do retries work here?"),
            ("assistant", "It retries up to three times with backoff."),
        ],
        transcript_length=2,
    )


def test_sanitize_allows_non_question_lines() -> None:
    # Unlike the mastery/reading hints, this one must NOT require a question
    # mark — a plausible next turn is often a request, not a question.
    assert chat_hints._sanitize("Make the tone more casual", "en") == "Make the tone more casual"


def test_sanitize_rejects_meta_and_assistant_voice() -> None:
    assert chat_hints._sanitize("You could ask about the retry limit", "en") == ""
    assert chat_hints._sanitize("Sure, here's a more casual version.", "en") == ""
    assert chat_hints._sanitize("好的，这是更随意一点的版本。", "zh") == ""
    assert chat_hints._sanitize("你可以问问重试上限", "zh") == ""


def test_sanitize_rejects_echo_of_last_user_message() -> None:
    assert (
        chat_hints._sanitize("How do retries work here?", "en", "How do retries work here?") == ""
    )
    assert chat_hints._sanitize(
        "What happens after the third retry fails?",
        "en",
        "How do retries work here?",
    )


@pytest.mark.asyncio
async def test_empty_transcript_never_calls_the_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def call_llm(_material: chat_hints._Material, _language: str) -> str:
        nonlocal calls
        calls += 1
        return "should not be reached"

    monkeypatch.setattr(chat_hints, "_call_llm", call_llm)

    async def collect(_session_id: str) -> chat_hints._Material:
        return chat_hints._Material(transcript=[], transcript_length=0)

    monkeypatch.setattr(chat_hints, "_collect", collect)

    result = await chat_hints.get_ask_hint("session-1")

    assert result["hint"] == ""
    assert calls == 0


@pytest.mark.asyncio
async def test_cache_hit_does_not_invoke_llm_again(monkeypatch: pytest.MonkeyPatch) -> None:
    material = _material()
    calls = 0

    async def collect(_session_id: str) -> chat_hints._Material:
        return material

    async def call_llm(_material: chat_hints._Material, _language: str) -> str:
        nonlocal calls
        calls += 1
        return "What happens after the third retry fails?"

    monkeypatch.setattr(chat_hints, "_collect", collect)
    monkeypatch.setattr(chat_hints, "_call_llm", call_llm)
    monkeypatch.setattr(chat_hints, "_response_language", lambda: "en")

    first = await chat_hints.get_ask_hint("session-1")
    second = await chat_hints.get_ask_hint("session-1")

    assert first == second
    assert first["hint"] == "What happens after the third retry fails?"
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
    async def collect(_session_id: str) -> chat_hints._Material:
        return _material()

    async def fail_llm(_material: chat_hints._Material, _language: str) -> str:
        raise error

    monkeypatch.setattr(chat_hints, "_collect", collect)
    monkeypatch.setattr(chat_hints, "_call_llm", fail_llm)
    monkeypatch.setattr(chat_hints, "_response_language", lambda: "en")

    result = await chat_hints.get_ask_hint("session-1")

    assert result["hint"] == ""


# -- Input normalization -------------------------------------------------------


class _ScriptedStore:
    """Session store stand-in returning one canned session record."""

    def __init__(self, session: dict[str, Any] | None, *, read_raises: bool = False) -> None:
        self._session = session
        self._read_raises = read_raises
        self.calls = 0

    async def get_session_with_messages(self, session_id: str) -> dict[str, Any] | None:
        self.calls += 1
        if self._read_raises:
            raise RuntimeError("store read failed")
        return self._session


_COLLECT_CASES = [
    (
        "filters-non-chat-roles",
        {
            "messages": [
                {"role": "system", "content": "be helpful"},
                {"role": "user", "content": "hi"},
                {"role": "tool", "content": "tool output"},
                {"role": "assistant", "content": "hello"},
                "not-a-dict",
            ]
        },
        [("user", "hi"), ("assistant", "hello")],
        2,
    ),
    (
        "collapses-whitespace",
        {"messages": [{"role": "user", "content": "  a\n\n  b \t c "}]},
        [("user", "a b c")],
        1,
    ),
    (
        "drops-empty-content-but-counts-role",
        {
            "messages": [
                {"role": "user", "content": "   "},
                {"role": "assistant", "content": None},
                {"role": "user", "content": "real"},
            ]
        },
        [("user", "real")],
        3,
    ),
    (
        "truncates-long-messages",
        {"messages": [{"role": "user", "content": "x" * 701}]},
        [("user", "x" * 700)],
        1,
    ),
    (
        "keeps-last-four-turns",
        {
            "messages": [
                {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
                for i in range(6)
            ]
        },
        [("user", "m2"), ("assistant", "m3"), ("user", "m4"), ("assistant", "m5")],
        6,
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "session", "expected_tail", "expected_length"),
    _COLLECT_CASES,
    ids=[case[0] for case in _COLLECT_CASES],
)
async def test_collect_normalizes_session_messages(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
    session: dict[str, Any],
    expected_tail: list[tuple[str, str]],
    expected_length: int,
) -> None:
    monkeypatch.setattr(
        "deeptutor.services.session.get_session_store",
        lambda: _ScriptedStore(session),
    )

    material = await chat_hints._collect("session-1")

    assert material.transcript == expected_tail
    assert material.transcript_length == expected_length
    assert bool(material) is bool(expected_tail)


_COLLECT_DEGRADE_CASES = [
    ("blank-id", "", None, True, "none"),
    ("store-getter-raises", "session-1", None, False, "getter"),
    ("store-read-raises", "session-1", None, False, "read"),
    ("session-missing", "session-1", None, False, "read"),
    ("no-messages-key", "session-1", {}, False, "read"),
    ("messages-none", "session-1", {"messages": None}, False, "read"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "session_id", "session", "getter_raises", "expected_progress"),
    _COLLECT_DEGRADE_CASES,
    ids=[case[0] for case in _COLLECT_DEGRADE_CASES],
)
async def test_collect_degrades_to_empty_material(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
    session: dict[str, Any] | None,
    getter_raises: bool,
    expected_progress: str,
) -> None:
    events: list[str] = []
    store = _ScriptedStore(session, read_raises=expected_progress == "read")

    def fake_getter() -> _ScriptedStore:
        events.append("getter")
        if getter_raises:
            raise RuntimeError("store unavailable")
        return store

    real_read = store.get_session_with_messages

    async def tracking_read(read_id: str) -> dict[str, Any] | None:
        events.append("read")
        return await real_read(read_id)

    store.get_session_with_messages = tracking_read  # type: ignore[method-assign]
    monkeypatch.setattr("deeptutor.services.session.get_session_store", fake_getter)

    material = await chat_hints._collect(session_id)

    assert not material
    assert material.transcript == []
    assert material.transcript_length == 0
    if expected_progress == "none":
        assert events == []
    else:
        assert events[0] == "getter"


# -- Prompt assembly -----------------------------------------------------------


_RENDER_CASES = [
    (
        "english",
        False,
        [("user", "hi"), ("assistant", "hello")],
        "# End of the conversation",
        ["[User] hi", "[Assistant] hello"],
        "Write that single next line.",
    ),
    (
        "chinese",
        True,
        [("user", "第三次重试会怎样"), ("assistant", "会退避")],
        "# 对话结尾",
        ["[用户] 第三次重试会怎样", "[助手] 会退避"],
        "请写出用户接下来最可能说的那一句。",
    ),
]


@pytest.mark.parametrize(
    ("name", "zh", "transcript", "expected_header", "expected_body", "expected_instruction"),
    _RENDER_CASES,
    ids=[case[0] for case in _RENDER_CASES],
)
def test_render_formats_transcript(
    name: str,
    zh: bool,
    transcript: list[tuple[str, str]],
    expected_header: str,
    expected_body: list[str],
    expected_instruction: str,
) -> None:
    material = chat_hints._Material(transcript=transcript, transcript_length=len(transcript))

    rendered = chat_hints._render(material, zh)

    lines = rendered.split("\n")
    assert lines[0] == expected_header
    assert lines[1 : 1 + len(expected_body)] == expected_body
    assert lines[1 + len(expected_body) :] == ["", "", expected_instruction]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "language", "expect_zh"),
    [("english", "en", False), ("chinese", "zh-CN", True)],
)
async def test_call_llm_selects_language_specific_prompts(
    name: str, monkeypatch: pytest.MonkeyPatch, language: str, expect_zh: bool
) -> None:
    captured: dict[str, Any] = {}

    async def fake_complete(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "继续" if expect_zh else "Keep going"

    monkeypatch.setattr("deeptutor.services.llm.complete", fake_complete)
    monkeypatch.setattr(
        "deeptutor.services.model_selection.tasks.task_llm_scope",
        lambda _kind: contextlib.nullcontext(),
    )

    material = _material()
    raw = await chat_hints._call_llm(material, language)

    assert raw in {"继续", "Keep going"}
    assert captured["system_prompt"] is (
        chat_hints._SYSTEM_ZH if expect_zh else chat_hints._SYSTEM_EN
    )
    assert ("# 对话结尾" in captured["prompt"]) is expect_zh
    assert ("# End of the conversation" in captured["prompt"]) is not expect_zh
    assert captured["max_retries"] == 0


@pytest.mark.parametrize(
    ("name", "get_language_raises", "expected"),
    [
        ("falls-back-to-english", True, "en"),
        ("returns-configured-language", False, "zh-CN"),
    ],
)
def test_response_language_resolution(
    name: str, monkeypatch: pytest.MonkeyPatch, get_language_raises: bool, expected: str
) -> None:
    def fake_get_response_language(default: str = "en") -> str:
        if get_language_raises:
            raise RuntimeError("settings unavailable")
        return "zh-CN"

    monkeypatch.setattr(
        "deeptutor.services.settings.interface_settings.get_response_language",
        fake_get_response_language,
    )

    assert chat_hints._response_language() == expected


# -- Sanitizer boundaries ------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "language", "raw", "expected"),
    [
        ("zh-at-limit", "zh", "预" * 44, "预" * 44),
        ("zh-over-limit", "zh", "预" * 45, ""),
        ("en-at-limit", "en", "x" * 110, "x" * 110),
        ("en-over-limit", "en", "x" * 111, ""),
    ],
)
def test_sanitize_enforces_length_boundaries(
    name: str, language: str, raw: str, expected: str
) -> None:
    assert chat_hints._sanitize(raw, language) == expected


_SANITIZE_REJECT_CASES = [
    ("multiline-raw", "first line\nsecond line"),
    ("code-fence-open", "```what happens next?"),
    ("code-fence-close", "what happens next?```"),
    ("marker-only", "- "),
    ("blank-raw", ""),
    ("none-raw", None),
]


@pytest.mark.parametrize(
    ("name", "raw"),
    _SANITIZE_REJECT_CASES,
    ids=[case[0] for case in _SANITIZE_REJECT_CASES],
)
def test_sanitize_rejects_structurally_invalid_raw(name: str, raw: Any) -> None:
    assert chat_hints._sanitize(raw, "en") == ""


@pytest.mark.parametrize(
    ("name", "raw", "language", "expected"),
    [
        ("double-quotes", '"What happens next?"', "en", "What happens next?"),
        ("single-quotes", "'What happens next?'", "en", "What happens next?"),
        ("curly-quotes", "“第三次重试会怎样？”", "zh", "第三次重试会怎样？"),
        ("corner-brackets", "「继续」", "zh", "继续"),
        ("leading-bullet", "- What happens next?", "en", "What happens next?"),
        ("leading-heading", "## 继续", "zh", "继续"),
    ],
)
def test_sanitize_strips_wrapping_quotes_and_markers(
    name: str, raw: str, language: str, expected: str
) -> None:
    assert chat_hints._sanitize(raw, language) == expected


# -- Public API degradation and output structure -------------------------------


_UNUSABLE_SOURCE_CASES = [
    ("blank-id", "", "getter"),
    ("unreadable-session", "session-1", "getter"),
    ("session-missing", "session-1", "store"),
    ("no-chat-messages", "session-1", "store"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "session_id", "failure_mode"),
    _UNUSABLE_SOURCE_CASES,
    ids=[case[0] for case in _UNUSABLE_SOURCE_CASES],
)
async def test_get_ask_hint_degrades_to_empty_structure_without_llm(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
    failure_mode: str,
) -> None:
    llm_calls = 0

    async def call_llm(_material: chat_hints._Material, _language: str) -> str:
        nonlocal llm_calls
        llm_calls += 1
        return "should not be reached"

    def raise_getter() -> _ScriptedStore:
        raise AssertionError("store must not be touched")

    if failure_mode == "getter":
        monkeypatch.setattr("deeptutor.services.session.get_session_store", raise_getter)
    else:
        canned = {
            "session-missing": None,
            "no-chat-messages": {"messages": [{"role": "system", "content": "x"}]},
        }
        monkeypatch.setattr(
            "deeptutor.services.session.get_session_store",
            lambda: _ScriptedStore(canned[failure_mode]),
        )
    monkeypatch.setattr(chat_hints, "_call_llm", call_llm)

    result = await chat_hints.get_ask_hint(session_id)

    assert set(result) == {"hint", "session_id", "generated_at"}
    assert result["hint"] == ""
    assert result["session_id"] == session_id
    assert isinstance(result["generated_at"], float)
    assert llm_calls == 0


@pytest.mark.asyncio
async def test_empty_hint_is_not_cached_and_generation_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(["first line\nsecond line", "What happens after the third retry fails?"])
    calls = 0

    async def collect(_session_id: str) -> chat_hints._Material:
        return _material()

    async def call_llm(_material: chat_hints._Material, _language: str) -> str:
        nonlocal calls
        calls += 1
        return next(responses)

    monkeypatch.setattr(chat_hints, "_collect", collect)
    monkeypatch.setattr(chat_hints, "_call_llm", call_llm)
    monkeypatch.setattr(chat_hints, "_response_language", lambda: "en")

    first = await chat_hints.get_ask_hint("session-1")
    second = await chat_hints.get_ask_hint("session-1")

    assert first["hint"] == ""
    assert second["hint"] == "What happens after the third retry fails?"
    assert calls == 2
