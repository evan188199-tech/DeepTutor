"""Focused tests for the session title generation entry.

Covers ``SessionTitleService._maybe_generate_session_title`` itself: the
rename/sentinel guards that keep repeated calls from clobbering a title,
the message prerequisites, the LLM failure / timeout / error-payload
fallbacks, prompt clipping and sanitizing, and the ``session_meta`` event
a successful generation publishes. The sanitizer and error-payload
helpers are covered in ``test_turn_runtime_title.py``; the task-model
scoping of this entry in ``tests/services/test_task_model_call_sites.py``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.services.session.turn_runtime import TurnRuntimeManager

SENTINEL = "New conversation"
USER_MSG = "Explain the chain rule with a worked example."
ASSISTANT_MSG = "It composes derivatives: (f(g))' = f'(g) * g'."


class _Store:
    def __init__(
        self,
        *,
        title: str = SENTINEL,
        messages: list[dict[str, Any]] | None = None,
        exists: bool = True,
    ) -> None:
        self.session: dict[str, Any] | None = (
            {"id": "session-1", "title": title} if exists else None
        )
        self.messages: list[dict[str, Any]] = (
            messages
            if messages is not None
            else [
                {"role": "user", "content": USER_MSG},
                {"role": "assistant", "content": ASSISTANT_MSG},
            ]
        )
        self.titles: list[tuple[str, str]] = []

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self.session

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        return self.messages

    async def update_session_title(self, session_id: str, title: str) -> None:
        self.titles.append((session_id, title))


class _Harness:
    """Duck-typed stand-in exposing the two members the title mixin touches."""

    def __init__(self, store: _Store) -> None:
        self.store = store
        self.events: list[StreamEvent] = []

    async def _publish_live_event(self, execution: Any, event: StreamEvent) -> Any:
        self.events.append(event)
        return event


def _run(harness: _Harness, *, session_id: str = "session-1", ui_language: str = "en") -> None:
    asyncio.run(
        TurnRuntimeManager._maybe_generate_session_title(
            harness,
            execution=object(),
            session_id=session_id,
            ui_language=ui_language,
        )
    )


def _patch_stream(monkeypatch: pytest.MonkeyPatch, chunks: list[str]) -> list[dict[str, Any]]:
    """Swap the LLM stream for a recording fake that yields *chunks*."""
    import deeptutor.services.llm as llm

    calls: list[dict[str, Any]] = []

    async def _stream(**kwargs: Any):
        calls.append(kwargs)
        for chunk in chunks:
            yield chunk

    monkeypatch.setattr(llm, "stream", _stream)
    return calls


class TestEntryGuards:
    def test_empty_session_id_is_a_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _Store()
        store.get_session = self._fail(store)  # type: ignore[method-assign]

        harness = _Harness(store)
        _run(harness, session_id="")

        assert harness.events == []
        assert store.titles == []

    @staticmethod
    def _fail(store: _Store) -> Any:
        async def _unexpected(*_args: Any) -> None:
            raise AssertionError("store must not be queried for an empty session id")

        return _unexpected

    def test_missing_session_skips_generation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = _patch_stream(monkeypatch, ["ignored"])

        harness = _Harness(_Store(exists=False))
        _run(harness)

        assert calls == []
        assert harness.store.titles == []
        assert harness.events == []

    def test_renamed_session_is_never_regenerated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A manual rename wins: the LLM must not run again for this session."""
        calls = _patch_stream(monkeypatch, ["A better name"])

        harness = _Harness(_Store(title="数据分析入门"))
        _run(harness)

        assert calls == []
        assert harness.store.titles == []
        assert harness.events == []

    def test_blank_title_is_also_regenerated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = _patch_stream(monkeypatch, ["Chain rule"])

        harness = _Harness(_Store(title="   "))
        _run(harness)

        assert len(calls) == 1
        assert harness.store.titles == [("session-1", "Chain rule")]


class TestMessagePrerequisites:
    def test_conversation_without_a_user_message_skips(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _patch_stream(monkeypatch, ["ignored"])
        messages = [{"role": "assistant", "content": ASSISTANT_MSG}]

        harness = _Harness(_Store(messages=messages))
        _run(harness)

        assert calls == []
        assert harness.store.titles == []
        assert harness.events == []

    def test_conversation_without_an_assistant_message_skips(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _patch_stream(monkeypatch, ["ignored"])
        messages = [{"role": "user", "content": USER_MSG}]

        harness = _Harness(_Store(messages=messages))
        _run(harness)

        assert calls == []
        assert harness.store.titles == []
        assert harness.events == []

    def test_blank_messages_are_skipped_until_real_content(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _patch_stream(monkeypatch, ["Chain rule"])
        messages = [
            {"role": "user", "content": "   "},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": USER_MSG},
            {"role": "assistant", "content": ASSISTANT_MSG},
        ]

        harness = _Harness(_Store(messages=messages))
        _run(harness)

        assert len(calls) == 1
        assert calls[0]["prompt"].count(USER_MSG) == 1
        assert harness.store.titles == [("session-1", "Chain rule")]


class TestFailureFallbacks:
    def test_llm_failure_falls_back_to_the_first_user_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import deeptutor.services.llm as llm

        async def _broken_stream(**_kwargs: Any):
            raise RuntimeError("provider exploded")
            yield ""  # pragma: no cover

        monkeypatch.setattr(llm, "stream", _broken_stream)

        harness = _Harness(_Store())
        _run(harness)  # must not raise

        assert harness.store.titles == [("session-1", USER_MSG)]
        # The fallback name is still broadcast, so a live client's sidebar
        # leaves the sentinel even though the model failed.
        assert [e.content for e in harness.events] == [USER_MSG]

    def test_llm_timeout_falls_back_to_the_first_user_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import deeptutor.services.llm as llm

        async def _slow_stream(**_kwargs: Any):
            raise asyncio.TimeoutError
            yield ""  # pragma: no cover

        monkeypatch.setattr(llm, "stream", _slow_stream)

        harness = _Harness(_Store())
        _run(harness)

        assert harness.store.titles == [("session-1", USER_MSG)]

    def test_error_payload_stream_is_never_stored_as_a_title(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A provider failure streams as content — it must not become the name."""
        _patch_stream(monkeypatch, ["Error: {'message': 'Your api key is invalid'}"])

        harness = _Harness(_Store())
        _run(harness)

        assert harness.store.titles == [("session-1", USER_MSG)]

    def test_long_user_message_fallback_is_truncated_to_50_chars(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import deeptutor.services.llm as llm

        async def _broken_stream(**_kwargs: Any):
            raise RuntimeError("down")
            yield ""  # pragma: no cover

        monkeypatch.setattr(llm, "stream", _broken_stream)
        long_user = (
            "请帮我详细解释一下反向传播算法的数学推导过程，特别是链式法则在其中扮演的角色"
            + "，谢谢" * 20
        )

        harness = _Harness(
            _Store(
                messages=[
                    {"role": "user", "content": long_user},
                    {"role": "assistant", "content": ASSISTANT_MSG},
                ]
            )
        )
        _run(harness)

        stored = harness.store.titles[0][1]
        assert stored == long_user[:50] + "..."
        assert len(stored) == 53


class TestTitleCleaning:
    def test_generated_title_is_sanitized_before_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _patch_stream(
            monkeypatch, ['  "**Quantum', ' Computing, explained**"\nUnrelated second line.']
        )

        harness = _Harness(_Store())
        _run(harness)

        assert len(calls) == 1
        assert harness.store.titles == [("session-1", "Quantum Computing, explained")]

    def test_overlong_generated_title_is_capped_at_80(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_stream(monkeypatch, ["A" * 100])

        harness = _Harness(_Store())
        _run(harness)

        stored = harness.store.titles[0][1]
        assert stored == "A" * 80

    def test_oversized_messages_are_clipped_in_the_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        long_user = "u" * 900 + "USER_TAIL"
        long_assistant = "a" * 2000 + "ASSISTANT_TAIL"
        calls = _patch_stream(monkeypatch, ["Any title"])

        harness = _Harness(
            _Store(
                messages=[
                    {"role": "user", "content": long_user},
                    {"role": "assistant", "content": long_assistant},
                ]
            )
        )
        _run(harness)

        prompt = calls[0]["prompt"]
        assert prompt.count("\n...[truncated]") == 2
        assert "USER_TAIL" not in prompt
        assert "ASSISTANT_TAIL" not in prompt

    def test_chinese_language_switches_the_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = _patch_stream(monkeypatch, ["链式法则"])

        harness = _Harness(_Store())
        _run(harness, ui_language="zh-CN")

        assert calls[0]["system_prompt"].startswith("你需要为一段对话生成一个简洁的标题")
        assert harness.store.titles == [("session-1", "链式法则")]


class TestPersistenceAndEvents:
    def test_success_publishes_one_session_meta_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_stream(monkeypatch, ["Chain rule"])

        harness = _Harness(_Store())
        _run(harness)

        assert len(harness.events) == 1
        event = harness.events[0]
        assert event.type is StreamEventType.SESSION_META
        assert event.source == "turn_runtime"
        assert event.stage == "title"
        assert event.content == "Chain rule"
        assert event.metadata == {"title": "Chain rule", "session_id": "session-1"}

    def test_store_failure_swallows_the_error_and_skips_the_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_stream(monkeypatch, ["Chain rule"])

        class _BrokenStore(_Store):
            async def update_session_title(self, session_id: str, title: str) -> None:
                raise RuntimeError("disk full")

        harness = _Harness(_BrokenStore())
        _run(harness)  # must not raise

        assert harness.events == []
