"""Failure and degradation branches of ``deeptutor.book.blocks._llm_writer``.

Complements ``tests/book/test_llm_writer.py`` (which covers happy-path payload
normalisation and reasoning-retry selection) with the branches a broken or
stingy provider can hit: truncated streams, unparseable payloads, preamble
pollution, unusable retries, and raw exception propagation.

All LLM access is faked; nothing here talks to a service.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.book.blocks import _llm_writer
from deeptutor.services.llm.types import StreamOutcome


def _install_config(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    config = SimpleNamespace(
        model="test-model",
        api_key="sk-test",
        base_url="http://llm.test/v1",
        api_version=None,
        binding=None,
    )
    monkeypatch.setattr(_llm_writer, "get_llm_config", lambda: config)
    return config


# ---------------------------------------------------------------------------
# llm_text — call plumbing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_text_appends_language_directive_and_forwards_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_config(monkeypatch)
    captured: dict[str, Any] = {}

    async def fake_complete(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "  <think>scratchpad</think>  Answer body.  "

    monkeypatch.setattr(_llm_writer, "llm_complete", fake_complete)

    text = await _llm_writer.llm_text(
        user_prompt="user",
        system_prompt="be terse",
        language="zh",
        reasoning_effort="none",
        response_format={"type": "json_object"},
    )

    assert text == "Answer body."
    assert captured["system_prompt"].startswith("be terse")
    assert captured["system_prompt"] != "be terse"
    assert captured["binding"] == "openai"  # default when config.binding is unset
    assert captured["model"] == "test-model"
    assert captured["api_key"] == "sk-test"
    assert captured["base_url"] == "http://llm.test/v1"
    assert captured["temperature"] == 0.4
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["reasoning_effort"] == "none"
    token_limit = captured.get("max_tokens", captured.get("max_completion_tokens"))
    assert token_limit == 1200


@pytest.mark.asyncio
async def test_llm_text_omits_optional_kwargs_when_not_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_config(monkeypatch)
    captured: dict[str, Any] = {}

    async def fake_complete(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "plain answer\n"

    monkeypatch.setattr(_llm_writer, "llm_complete", fake_complete)

    text = await _llm_writer.llm_text(user_prompt="user", system_prompt="sys")

    assert text == "plain answer"
    assert "response_format" not in captured
    assert "reasoning_effort" not in captured


@pytest.mark.asyncio
async def test_llm_text_streams_through_outcome_when_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_config(monkeypatch)
    complete_calls: list[dict[str, Any]] = []
    outcome = StreamOutcome()

    async def fake_complete(**kwargs: Any) -> str:
        complete_calls.append(kwargs)
        return "unused"

    async def fake_stream(**kwargs: Any) -> Any:
        assert kwargs["outcome"] is outcome
        assert kwargs["prompt"] == "user"
        yield "Hel"
        yield "lo "
        outcome.finish_reason = "stop"

    monkeypatch.setattr(_llm_writer, "llm_complete", fake_complete)
    monkeypatch.setattr(_llm_writer, "llm_stream", fake_stream)

    text = await _llm_writer.llm_text(user_prompt="user", system_prompt="sys", outcome=outcome)

    assert text == "Hello"
    assert complete_calls == []
    assert outcome.finish_reason == "stop"


# ---------------------------------------------------------------------------
# _strip_thinking_preamble / _normalize_json_payload — pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("no json object in this prose", "no json object in this prose"),
        ('Sure. {"a": 1}', '{"a": 1}'),
        ('think: {"old": 1} final {"new": 2}', '{"new": 2}'),
        ('prefix {"bad": ', 'prefix {"bad": '),
        ('{"start": true}', '{"start": true}'),
    ],
)
def test_strip_thinking_preamble_variants(raw: str, expected: str) -> None:
    assert _llm_writer._strip_thinking_preamble(raw) == expected


@pytest.mark.parametrize(
    ("data", "expected_key", "expected"),
    [
        ({"a": 1}, "cards", {"a": 1}),
        ([{"cards": [1]}], "cards", {"cards": [1]}),
        ([{"other": 1}], "cards", {"cards": [{"other": 1}]}),
        ([{"a": 1}, {"b": 2}], "cards", {"cards": [{"a": 1}, {"b": 2}]}),
        ([{"only": 1}], None, {"only": 1}),
        (["junk"], "cards", {"cards": ["junk"]}),
        ("plain string", None, {}),
        (42, None, {}),
    ],
)
def test_normalize_json_payload_shapes(
    data: Any, expected_key: str | None, expected: dict[str, Any]
) -> None:
    assert _llm_writer._normalize_json_payload(data, expected_key=expected_key) == expected


# ---------------------------------------------------------------------------
# llm_json — degradation paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_json_retries_after_truncated_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str | None] = []

    async def fake_llm_text(**kwargs: Any) -> str:
        effort = kwargs.get("reasoning_effort")
        calls.append(effort if isinstance(effort, str) else None)
        if len(calls) == 1:
            kwargs["outcome"].finish_reason = "length"
            return '{"events": [{"date": "20'
        return '{"events": [{"date": "2026", "title": "ok"}]}'

    monkeypatch.setattr(_llm_writer, "llm_text", fake_llm_text)

    data = await _llm_writer.llm_json(user_prompt="u", system_prompt="s", expected_key="events")

    assert calls == [None, "low"]
    assert data["events"][0]["title"] == "ok"
    assert data["_metadata"]["reasoning_retry"] == "low"


@pytest.mark.asyncio
async def test_llm_json_keeps_first_payload_when_retry_also_unusable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = ['{"other": 1}', '{"other": 2}']

    async def fake_llm_text(**kwargs: Any) -> str:
        return payloads.pop(0)

    monkeypatch.setattr(_llm_writer, "llm_text", fake_llm_text)

    data = await _llm_writer.llm_json(user_prompt="u", system_prompt="s", expected_key="events")

    assert data == {"other": 1}
    assert "_metadata" not in data


@pytest.mark.asyncio
async def test_llm_json_returns_empty_dict_when_both_rounds_unparseable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_llm_text(**kwargs: Any) -> str:
        return "Sorry, I cannot help with that."

    monkeypatch.setattr(_llm_writer, "llm_text", fake_llm_text)

    data = await _llm_writer.llm_json(user_prompt="u", system_prompt="s")

    assert data == {}


@pytest.mark.asyncio
async def test_llm_json_propagates_provider_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(**kwargs: Any) -> str:
        raise RuntimeError("provider down")

    monkeypatch.setattr(_llm_writer, "llm_text", boom)

    with pytest.raises(RuntimeError, match="provider down"):
        await _llm_writer.llm_json(user_prompt="u", system_prompt="s")


@pytest.mark.asyncio
async def test_llm_json_single_call_parses_preamble_prefixed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_llm_text(**kwargs: Any) -> str:
        calls.append(kwargs)
        return 'Let me think about it.\n{"cards": [{"front": "A", "back": "B"}]}'

    monkeypatch.setattr(_llm_writer, "llm_text", fake_llm_text)

    data = await _llm_writer.llm_json(
        user_prompt="u", system_prompt="s", expected_key="cards", max_tokens=100
    )

    assert len(calls) == 1
    assert data["cards"][0]["front"] == "A"
    # Floor: even a caller asking for 100 tokens gets the 2600 room-to-think budget.
    assert calls[0]["max_tokens"] == 2600
