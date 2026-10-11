"""The lifecycle edges of the ``ask_user`` draft emitter.

Complements ``test_ask_user_drafts.py`` with the branches that file does not
pin down: the first publish bypassing the throttle, the interval and growth
gates in isolation, unrenderable frames holding the baseline instead of
advancing it, a shrinking frame being refused in favour of the last good
preview, and call-id normalisation keeping one card per call.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.agents.loop import ask_user_drafts as drafts_module
from deeptutor.agents.loop.ask_user_drafts import AskUserDraftEmitter

_INTRO_ONLY = '{"intro": "Hi"'
_LONG_INTRO = '{"intro": "Hi, this is a longer intro now"}'
_UNPARSEABLE = "just prose, not a json object at all"
_GROWN_INTRO = (
    '{"intro": "Hi there, this intro is long enough to clear the growth floor", '
    '"questions": [{"prompt": "Ready?", "options": [{"label": "yes"}]}'
)
_TWO_QUESTIONS = (
    '{"intro": "I", "questions": [{"prompt": "A", "options": [{"label": "x"}]}, '
    '{"prompt": "B", "options": [{"label": "y"}]}'
)
_ONE_QUESTION_LONG = (
    '{"intro": "I", "questions": [{"prompt": "A", "options": [{"label": "x", '
    '"description": "padded well past the length of the two-question frame"}]}]}'
)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _RecordingStream:
    def __init__(self) -> None:
        self.metadata: list[dict[str, Any]] = []

    async def progress(
        self,
        message: str,
        source: str = "",
        stage: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.metadata.append(metadata or {})


def _emitter(stream: _RecordingStream) -> AskUserDraftEmitter:
    return AskUserDraftEmitter(
        stream=stream,
        source="chat",
        stage="responding",
        metadata={"call_id": "chat-responding-1"},
    )


def _draft_shapes(stream: _RecordingStream) -> list[tuple[int, ...]]:
    shapes = []
    for meta in stream.metadata:
        questions = meta["ask_user_draft"]["questions"]
        shapes.append((len(questions), *(len(q["options"]) for q in questions)))
    return shapes


async def _observe(
    emitter: AskUserDraftEmitter,
    arguments: str,
    *,
    call_id: str = "call_1",
    tool_name: str = "ask_user",
) -> None:
    await emitter.observe(call_id=call_id, tool_name=tool_name, arguments=arguments)


@pytest.mark.asyncio
async def test_the_first_renderable_frame_publishes_without_throttling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A short intro publishes immediately; no published state means no gate."""
    stream = _RecordingStream()
    monkeypatch.setattr(drafts_module, "time", _Clock())

    await _observe(_emitter(stream), _INTRO_ONLY)

    assert len(stream.metadata) == 1
    assert stream.metadata[0]["ask_user_draft"]["intro"] == "Hi"
    assert stream.metadata[0]["ask_user_draft"]["questions"] == []


@pytest.mark.asyncio
async def test_the_interval_floor_holds_a_fast_burst_until_time_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Large growth right after a publish waits; the same frame publishes later."""
    stream = _RecordingStream()
    clock = _Clock()
    monkeypatch.setattr(drafts_module, "time", clock)
    emitter = _emitter(stream)

    await _observe(emitter, _INTRO_ONLY)
    await _observe(emitter, _GROWN_INTRO)
    assert len(stream.metadata) == 1

    clock.advance(0.2)
    await _observe(emitter, _GROWN_INTRO)

    assert len(stream.metadata) == 2
    assert _draft_shapes(stream)[-1] == (1, 1)


@pytest.mark.asyncio
async def test_the_growth_floor_holds_a_tiny_delta_even_after_time_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Past the interval, a delta too small to render still waits."""
    stream = _RecordingStream()
    clock = _Clock()
    monkeypatch.setattr(drafts_module, "time", clock)
    emitter = _emitter(stream)

    await _observe(emitter, _INTRO_ONLY)
    clock.advance(1.0)
    await _observe(emitter, _INTRO_ONLY + " ")

    assert len(stream.metadata) == 1


@pytest.mark.asyncio
async def test_an_unrenderable_frame_leaves_the_baseline_for_the_next_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prose that parses to nothing publishes nothing and is not measured."""
    stream = _RecordingStream()
    clock = _Clock()
    monkeypatch.setattr(drafts_module, "time", clock)
    emitter = _emitter(stream)

    await _observe(emitter, _INTRO_ONLY)
    await _observe(emitter, _UNPARSEABLE)
    assert len(stream.metadata) == 1

    clock.advance(0.2)
    await _observe(emitter, _LONG_INTRO)

    # From the true baseline the growth clears the floor; had the unrenderable
    # frame advanced it, this delta would have been throttled away.
    assert len(stream.metadata) == 2
    assert stream.metadata[-1]["ask_user_draft"]["intro"] == "Hi, this is a longer intro now"


@pytest.mark.asyncio
async def test_a_stream_of_unrenderable_arguments_publishes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _RecordingStream()
    clock = _Clock()
    monkeypatch.setattr(drafts_module, "time", clock)
    emitter = _emitter(stream)

    await _observe(emitter, _UNPARSEABLE)
    clock.advance(1.0)
    await _observe(emitter, _UNPARSEABLE + " and more prose")

    assert stream.metadata == []


@pytest.mark.asyncio
async def test_blank_arguments_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _RecordingStream()
    monkeypatch.setattr(drafts_module, "time", _Clock())

    await _observe(_emitter(stream), "")

    assert stream.metadata == []


@pytest.mark.asyncio
async def test_a_shrinking_frame_is_refused_and_the_last_preview_stands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A longer frame that renders fewer questions never replaces the card."""
    stream = _RecordingStream()
    clock = _Clock()
    monkeypatch.setattr(drafts_module, "time", clock)
    emitter = _emitter(stream)
    assert len(_ONE_QUESTION_LONG) > len(_TWO_QUESTIONS) + drafts_module._MIN_GROWTH_CHARS

    await _observe(emitter, _TWO_QUESTIONS)
    clock.advance(0.5)
    await _observe(emitter, _ONE_QUESTION_LONG)
    assert _draft_shapes(stream) == [(2, 1, 1)]

    # The round's own settle pass repeats the finished arguments; the identical
    # payload must not republish the card the refused frame never replaced.
    await emitter.settle([{"id": "call_1", "name": "ask_user", "arguments": _TWO_QUESTIONS}])

    assert _draft_shapes(stream) == [(2, 1, 1)]


@pytest.mark.asyncio
async def test_a_composite_call_id_shares_state_with_its_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Responses-API composite id lands on the same card as the bare id."""
    stream = _RecordingStream()
    clock = _Clock()
    monkeypatch.setattr(drafts_module, "time", clock)
    emitter = _emitter(stream)

    await _observe(emitter, _INTRO_ONLY, call_id="call_1|item_9")
    await _observe(emitter, _INTRO_ONLY, call_id="call_1")

    assert len(stream.metadata) == 1
    assert stream.metadata[0]["draft_call_id"] == "call_1"


@pytest.mark.asyncio
async def test_settle_skips_a_call_that_is_not_ask_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _RecordingStream()
    clock = _Clock()
    monkeypatch.setattr(drafts_module, "time", clock)
    emitter = _emitter(stream)

    await _observe(emitter, _INTRO_ONLY)
    await emitter.settle([{"id": "call_1", "name": "rag_search", "arguments": _TWO_QUESTIONS}])

    assert len(stream.metadata) == 1
