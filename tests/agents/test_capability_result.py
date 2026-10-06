"""Contract tests for the shared capability result envelope.

``emit_capability_result`` is the single final emission every capability
converges on (fan-in 7). These tests pin the envelope contract: payload
passthrough, source forwarding, and the cost/usage summary enrichment —
all against fakes, with no services started.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.agents._shared.capability_result import emit_capability_result
from deeptutor.services.llm.metrics import current_usage


class _RecordingStream:
    """Stand-in for StreamBus capturing the final result emission."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def result(self, data: dict[str, Any], source: str = "", **_kwargs) -> None:
        self.calls.append({"data": data, "source": source})


class _FakeUsage:
    """Stand-in for UsageTracker / TurnUsage with a canned summary()."""

    def __init__(self, summary: dict[str, Any] | None) -> None:
        self._summary = summary
        self.summary_calls = 0

    def summary(self) -> dict[str, Any] | None:
        self.summary_calls += 1
        return self._summary


#: Realistic payload shapes the fan-in consumers emit today
#: (question followup / research partial / labelled failure).
ENVELOPE_CASES = {
    "success": {"response": "answer", "mode": "followup", "question_id": "q1"},
    "partial": {
        "response": "partial report",
        "partial": True,
        "failed_block_count": 2,
        "failed_block_titles": ["intro", "method"],
    },
    "failure": {"response": "", "error": "pipeline failed"},
}

COST_SUMMARY = {"total_cost_usd": 0.02, "total_tokens": 120, "total_calls": 3}
USAGE_SUMMARY = {"total_calls": 3, "total_tokens": 120, "cache_input_tokens": 40}


def _collector(summary: dict[str, Any] | None) -> _FakeUsage:
    return _FakeUsage(summary)


@pytest.mark.asyncio
@pytest.mark.parametrize(("case_name", "payload"), sorted(ENVELOPE_CASES.items()))
async def test_envelope_passthrough_without_usage(
    case_name: str, payload: dict[str, Any]
) -> None:
    """No usage, no turn collector: the payload is emitted unchanged."""
    stream = _RecordingStream()

    await emit_capability_result(stream, dict(payload), source="question")

    assert len(stream.calls) == 1
    assert stream.calls[0]["data"] == payload
    assert stream.calls[0]["source"] == "question"
    assert "metadata" not in stream.calls[0]["data"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("case_name", "payload"), sorted(ENVELOPE_CASES.items()))
async def test_envelope_cost_summary_merged_for_every_shape(
    case_name: str, payload: dict[str, Any]
) -> None:
    """Usage summary lands under metadata.cost_summary; business fields stay."""
    stream = _RecordingStream()
    usage = _FakeUsage(dict(COST_SUMMARY))
    enriched = dict(payload)

    await emit_capability_result(stream, enriched, source="research", usage=usage)

    emitted = stream.calls[0]["data"]
    assert emitted["metadata"]["cost_summary"] == COST_SUMMARY
    for key, value in payload.items():
        assert emitted[key] == value
    assert stream.calls[0]["source"] == "research"


@pytest.mark.asyncio
async def test_usage_with_empty_summary_is_skipped() -> None:
    """A tracker with zero recorded calls reports None — no metadata appears."""
    stream = _RecordingStream()
    usage = _FakeUsage(None)

    await emit_capability_result(stream, {"response": "x"}, source="cap", usage=usage)

    assert usage.summary_calls == 1
    assert "metadata" not in stream.calls[0]["data"]


@pytest.mark.asyncio
async def test_non_dict_metadata_is_replaced_by_cost_envelope() -> None:
    """A non-dict metadata field cannot survive: it is swapped for a dict."""
    stream = _RecordingStream()
    payload = {"response": "x", "metadata": "legacy-string"}

    await emit_capability_result(
        stream, payload, source="cap", usage=_FakeUsage(dict(COST_SUMMARY))
    )

    emitted = stream.calls[0]["data"]
    assert emitted["metadata"] == {"cost_summary": COST_SUMMARY}


@pytest.mark.asyncio
async def test_preexisting_metadata_dict_is_preserved() -> None:
    """Existing metadata keys survive cost_summary merging (same dict)."""
    stream = _RecordingStream()
    metadata = {"mode": "followup"}
    payload = {"response": "x", "metadata": metadata}

    await emit_capability_result(
        stream, payload, source="cap", usage=_FakeUsage(dict(COST_SUMMARY))
    )

    emitted = stream.calls[0]["data"]
    assert emitted["metadata"] is metadata
    assert emitted["metadata"]["mode"] == "followup"
    assert emitted["metadata"]["cost_summary"] == COST_SUMMARY


@pytest.mark.asyncio
async def test_turn_collector_summary_attached_as_usage_summary() -> None:
    """A bound turn collector contributes metadata.usage_summary."""
    stream = _RecordingStream()
    token = current_usage.set(_collector(dict(USAGE_SUMMARY)))
    try:
        await emit_capability_result(stream, {"response": "x"}, source="cap")
    finally:
        current_usage.reset(token)

    assert stream.calls[0]["data"]["metadata"]["usage_summary"] == USAGE_SUMMARY


@pytest.mark.asyncio
async def test_turn_collector_without_calls_is_skipped() -> None:
    """A collector with no recorded calls emits no usage_summary."""
    stream = _RecordingStream()
    token = current_usage.set(_collector(None))
    try:
        await emit_capability_result(stream, {"response": "x"}, source="cap")
    finally:
        current_usage.reset(token)

    assert "metadata" not in stream.calls[0]["data"]


@pytest.mark.asyncio
async def test_no_collector_bound_leaves_payload_alone() -> None:
    """Default (unbound) ContextVar: no usage_summary, payload untouched."""
    stream = _RecordingStream()

    await emit_capability_result(stream, {"response": "x"}, source="cap")

    assert "metadata" not in stream.calls[0]["data"]


@pytest.mark.asyncio
async def test_usage_and_collector_both_attached() -> None:
    """Both sources present: cost_summary and usage_summary coexist."""
    stream = _RecordingStream()
    metadata = {"existing": 1}
    token = current_usage.set(_collector(dict(USAGE_SUMMARY)))
    try:
        await emit_capability_result(
            stream,
            {"response": "x", "metadata": metadata},
            source="cap",
            usage=_FakeUsage(dict(COST_SUMMARY)),
        )
    finally:
        current_usage.reset(token)

    emitted = stream.calls[0]["data"]["metadata"]
    assert emitted["existing"] == 1
    assert emitted["cost_summary"] == COST_SUMMARY
    assert emitted["usage_summary"] == USAGE_SUMMARY


@pytest.mark.asyncio
async def test_payload_mutation_is_in_place() -> None:
    """The contract promises in-place mutation: caller's dict is enriched."""
    stream = _RecordingStream()
    payload: dict[str, Any] = {"response": "x"}

    await emit_capability_result(
        stream, payload, source="cap", usage=_FakeUsage(dict(COST_SUMMARY))
    )

    assert payload["metadata"]["cost_summary"] == COST_SUMMARY
