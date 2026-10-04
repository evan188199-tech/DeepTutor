"""Failing-test set for the Hermes gateway data-only SSE parser.

``HermesRemoteClient.stream_events`` reassembles SSE frames by hand. These
tests pin the heartbeat/comment-frame, out-of-order-field, and mid-stream
truncation behaviours the parser must honour; the failing ones correspond to
defects found on this branch.
"""

from __future__ import annotations

import httpx
import pytest

from deeptutor.services.subagent.hermes_remote_client import HermesRemoteClient


async def _collect(raw: bytes) -> list[dict]:
    def stream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=raw,
        )

    async with HermesRemoteClient(
        "http://hermes.test",
        "synthetic-secret",
        transport=httpx.MockTransport(stream),
    ) as client:
        return [event async for event in client.stream_events("run-1")]


def _delta_events(events: list[dict]) -> list[dict]:
    """Keep everything except quiet keepalive markers."""
    return [event for event in events if event.get("event") != "gateway.keepalive"]


@pytest.mark.asyncio
async def test_empty_data_heartbeat_frame_is_skipped_not_fatal() -> None:
    """A ``data:`` line with an empty value is a keepalive frame, not a frame.

    Some gateways emit ``data:\\n\\n`` between events as a heartbeat. The
    parser currently dispatches the empty payload into ``json.loads``,
    raising ``HermesRemoteProtocolError("invalid_sse_json")`` and tearing
    down the whole run. Per the SSE framing rules an empty data buffer means
    "nothing to dispatch" — the frame must be skipped and the stream kept
    alive.
    """
    events = await _collect(
        b': ping\n\ndata:\n\ndata: {"event":"message.delta","delta":"hello"}\n\n'
    )

    assert _delta_events(events) == [{"event": "message.delta", "delta": "hello"}]


@pytest.mark.asyncio
async def test_event_field_without_data_does_not_bleed_into_next_frame() -> None:
    """An ``event:`` line whose frame carries no data resets, not sticks.

    A frame that only sets ``event:`` and then ends with a blank line (no
    data) must not label the next data-only frame. SSE framing resets the
    event-type buffer on every blank-line boundary; the parser currently
    keeps it, so a benign ``{"delta": ...}`` frame arrives mislabelled as
    e.g. ``run.failed`` and the mapper acts on the wrong event.
    """
    events = await _collect(b'event: run.failed\n\ndata: {"delta":"still fine"}\n\n')

    assert len(_delta_events(events)) == 1
    payload = _delta_events(events)[0]
    assert payload.get("event") != "run.failed"
    assert payload == {"delta": "still fine"}


@pytest.mark.asyncio
async def test_pending_frame_is_flushed_when_connection_ends_without_blank_line() -> None:
    """A complete frame terminated only by EOF must still be delivered.

    Gateways that end the response right after the last ``data:`` line —
    without the trailing blank line — currently lose that frame silently.
    The usage/report tail frame is exactly the one that tends to be cut this
    way, so the run finishes without its final state.
    """
    events = await _collect(
        b'data: {"event":"message.delta","delta":"hello"}\n\n'
        b'data: {"event":"run.completed","output":"hello"}\n'
    )

    assert _delta_events(events)[-1] == {"event": "run.completed", "output": "hello"}


@pytest.mark.asyncio
async def test_done_marker_without_blank_line_terminates_cleanly_keeping_the_frame() -> None:
    """``[DONE]`` on the next line without a blank line still ends the run.

    The parser joins consecutive ``data:`` lines into one payload, so a
    minimal gateway that streams ``data: {...}\\ndata: [DONE]\\n`` (no blank
    line) currently produces the unparseable payload ``"{...}\\n[DONE]"`` —
    either a protocol error or a dropped frame. The complete frame was fully
    received before the done marker and must be delivered, then the stream
    must end cleanly.
    """
    events = await _collect(
        b'data: {"event":"message.delta","delta":"hello"}\n\n'
        b'data: {"event":"run.completed","output":"hello"}\n'
        b"data: [DONE]\n"
    )

    assert _delta_events(events) == [
        {"event": "message.delta", "delta": "hello"},
        {"event": "run.completed", "output": "hello"},
    ]


@pytest.mark.asyncio
async def test_baseline_comment_heartbeats_and_done_marker_are_quiet() -> None:
    """Baseline: comment heartbeats stay quiet and ``[DONE]`` ends the stream."""
    events = await _collect(
        b': ping\n\ndata: {"event":"message.delta","delta":"hi"}\n\n: ping\n\ndata: [DONE]\n\n'
    )

    assert _delta_events(events) == [{"event": "message.delta", "delta": "hi"}]
    keepalives = [event for event in events if event.get("event") == "gateway.keepalive"]
    assert len(keepalives) == 2
