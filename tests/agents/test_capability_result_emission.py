"""Contract tests for the shared capability result emission helper."""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.agents._shared.capability_result import emit_capability_result
from deeptutor.runtime.agentic.usage import UsageTracker
from deeptutor.services.llm.metrics import TurnUsage, current_usage


class RecordingBus:
    """Minimal StreamBus stand-in capturing the final ``result`` emission."""

    def __init__(self) -> None:
        self.results: list[tuple[dict[str, Any], str]] = []

    async def result(self, data: dict[str, Any], source: str = "") -> None:
        self.results.append((data, source))


def _tracker_with_calls() -> UsageTracker:
    tracker = UsageTracker()
    tracker.add_estimated(input_chars=350, output_chars=70)
    assert tracker.calls == 1
    return tracker


def _turn_usage_with_calls() -> TurnUsage:
    turn_usage = TurnUsage(session_id="s1", turn_id="t1", source="test")
    turn_usage.calls.append(
        {
            "prompt_tokens": 10,
            "completion_tokens": 4,
            "total_tokens": 14,
            "duration_seconds": 0.2,
            "ttft_seconds": 0.1,
            "estimated": False,
        }
    )
    return turn_usage


@pytest.mark.asyncio
async def test_without_usage_payload_passes_through() -> None:
    bus = RecordingBus()
    payload: dict[str, Any] = {"response": "answer"}

    await emit_capability_result(bus, payload, source="chat")

    assert bus.results == [({"response": "answer"}, "chat")]
    assert "metadata" not in payload


@pytest.mark.asyncio
async def test_tracker_summary_becomes_cost_summary() -> None:
    bus = RecordingBus()
    payload: dict[str, Any] = {"response": "answer"}

    await emit_capability_result(
        bus, payload, source="deep_research", usage=_tracker_with_calls()
    )

    assert bus.results[0][1] == "deep_research"
    meta = bus.results[0][0]["metadata"]
    assert meta["cost_summary"]["total_calls"] == 1
    assert meta["cost_summary"]["total_tokens"] == 120


@pytest.mark.asyncio
async def test_existing_metadata_is_preserved() -> None:
    bus = RecordingBus()
    payload: dict[str, Any] = {
        "response": "answer",
        "metadata": {"stage": "reporting"},
    }

    await emit_capability_result(bus, payload, source="chat", usage=_tracker_with_calls())

    meta = bus.results[0][0]["metadata"]
    assert meta["stage"] == "reporting"
    assert meta["cost_summary"]["total_calls"] == 1


@pytest.mark.asyncio
async def test_zero_call_tracker_emits_no_cost_summary() -> None:
    bus = RecordingBus()
    payload: dict[str, Any] = {"response": "answer"}

    await emit_capability_result(bus, payload, source="chat", usage=UsageTracker())

    assert bus.results[0][0] == {"response": "answer"}


@pytest.mark.asyncio
async def test_non_dict_metadata_is_replaced() -> None:
    bus = RecordingBus()
    payload: dict[str, Any] = {"response": "answer", "metadata": "stale-scalar"}

    await emit_capability_result(bus, payload, source="chat", usage=_tracker_with_calls())

    meta = bus.results[0][0]["metadata"]
    assert isinstance(meta, dict)
    assert "stale-scalar" not in meta
    assert meta["cost_summary"]["total_calls"] == 1


@pytest.mark.asyncio
async def test_task_collector_adds_usage_summary() -> None:
    bus = RecordingBus()
    payload: dict[str, Any] = {"response": "answer"}
    token = current_usage.set(_turn_usage_with_calls())
    try:
        await emit_capability_result(bus, payload, source="chat")
    finally:
        current_usage.reset(token)

    meta = bus.results[0][0]["metadata"]
    assert meta["usage_summary"]["total_calls"] == 1
    assert meta["usage_summary"]["total_tokens"] == 14
    assert "cost_summary" not in meta


@pytest.mark.asyncio
async def test_collector_summary_wins_over_preexisting_usage_summary() -> None:
    bus = RecordingBus()
    payload: dict[str, Any] = {
        "response": "answer",
        "metadata": {"usage_summary": {"stale": True}},
    }
    token = current_usage.set(_turn_usage_with_calls())
    try:
        await emit_capability_result(bus, payload, source="chat")
    finally:
        current_usage.reset(token)

    meta = bus.results[0][0]["metadata"]
    assert meta["usage_summary"]["total_tokens"] == 14


@pytest.mark.asyncio
async def test_tracker_and_collector_coexist() -> None:
    bus = RecordingBus()
    payload: dict[str, Any] = {"response": "answer"}
    token = current_usage.set(_turn_usage_with_calls())
    try:
        await emit_capability_result(
            bus, payload, source="chat", usage=_tracker_with_calls()
        )
    finally:
        current_usage.reset(token)

    meta = bus.results[0][0]["metadata"]
    assert meta["cost_summary"]["total_tokens"] == 120
    assert meta["usage_summary"]["total_tokens"] == 14
