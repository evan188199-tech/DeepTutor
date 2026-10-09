"""Unit tests for the authenticated Hermes gateway HTTP/SSE client."""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
from typing import Any

import httpx
import pytest

from deeptutor.services.subagent.hermes_remote_client import (
    HermesRemoteClient,
    HermesRemoteHTTPError,
    HermesRemoteProtocolError,
)

API_KEY = "synthetic-secret"
BASE_URL = "http://hermes.test"


def _sse_transport(frames: bytes) -> httpx.MockTransport:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=frames,
        )

    return httpx.MockTransport(handler)


async def _collect(stream: AsyncIterator[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event async for event in stream]


def test_http_error_carries_status_code() -> None:
    error = HermesRemoteHTTPError(503)
    assert error.status_code == 503
    assert str(error) == "HTTP status 503"


def test_protocol_error_carries_code() -> None:
    error = HermesRemoteProtocolError("invalid_json")
    assert error.code == "invalid_json"
    assert str(error) == "invalid_json"


def test_module_exports_the_public_contract() -> None:
    from deeptutor.services.subagent import hermes_remote_client

    assert set(hermes_remote_client.__all__) == {
        "HermesRemoteClient",
        "HermesRemoteHTTPError",
        "HermesRemoteProtocolError",
    }


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("  http://hermes.test  ", "http://hermes.test"),
        ("https://hermes.test/", "https://hermes.test"),
        ("https://hermes.test/p/study///", "https://hermes.test/p/study"),
        ("http://localhost:8080", "http://localhost:8080"),
    ],
)
def test_validate_base_url_canonicalizes_acceptable_roots(raw: str, canonical: str) -> None:
    assert HermesRemoteClient.validate_base_url(raw) == canonical


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "ftp://hermes.test",
        "hermes.test",
        "https://",
        "https://user@hermes.test",
        "https://user:secret@hermes.test",
        "https://hermes.test?key=secret",
        "https://hermes.test#fragment",
        "https://hermes.test:invalid",
    ],
)
def test_validate_base_url_rejects_unsafe_input(raw: str) -> None:
    with pytest.raises(HermesRemoteProtocolError, match="invalid_base_url"):
        HermesRemoteClient.validate_base_url(raw)


@pytest.mark.asyncio
async def test_requests_carry_bearer_authorization_and_paths_join_cleanly() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    async with HermesRemoteClient(
        BASE_URL, API_KEY, transport=httpx.MockTransport(handler)
    ) as client:
        got = await client.get_json("/v1/capabilities")

    assert got == {"ok": True}
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/v1/capabilities"
    assert requests[0].headers["Authorization"] == f"Bearer {API_KEY}"


@pytest.mark.asyncio
async def test_post_json_sends_payload_and_extra_headers() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"accepted": True})

    async with HermesRemoteClient(
        BASE_URL, API_KEY, transport=httpx.MockTransport(handler)
    ) as client:
        result = await client.post_json(
            "/v1/runs",
            {"prompt": "hello"},
            headers={"X-Request-Id": "req-1"},
        )

    assert result == {"accepted": True}
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/v1/runs"
    assert json.loads(requests[0].content) == {"prompt": "hello"}
    assert requests[0].headers["X-Request-Id"] == "req-1"
    assert requests[0].headers["Authorization"] == f"Bearer {API_KEY}"


@pytest.mark.parametrize("status", [400, 401, 404, 500])
@pytest.mark.asyncio
async def test_json_helpers_raise_http_error_on_failure_status(status: int) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "nope"})

    async with HermesRemoteClient(
        BASE_URL, API_KEY, transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(HermesRemoteHTTPError) as exc_info:
            await client.get_json("/v1/capabilities")
    assert exc_info.value.status_code == status


@pytest.mark.asyncio
async def test_get_json_rejects_non_json_body() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    async with HermesRemoteClient(
        BASE_URL, API_KEY, transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(HermesRemoteProtocolError, match="invalid_json"):
            await client.get_json("/v1/capabilities")


@pytest.mark.parametrize("payload", [[1, 2, 3], "text", 42])
@pytest.mark.asyncio
async def test_json_helpers_require_a_json_object(payload: Any) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with HermesRemoteClient(
        BASE_URL, API_KEY, transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(HermesRemoteProtocolError, match="invalid_json_object"):
            await client.get_json("/v1/capabilities")


def _history_handler(
    payload: dict[str, Any] | None = None,
    *,
    status: int = 200,
    capture: list[httpx.Request] | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json=payload if payload is not None else {})

    return httpx.MockTransport(handler)


HISTORY_OK = {
    "object": "list",
    "data": [
        {"role": "system", "content": "instructions"},
        {"role": "user", "content": "  hello  "},
        {"role": "assistant", "content": "hi there"},
        {"role": "user", "content": "   "},
        {"role": "tool", "content": "tool output"},
        {"role": "user", "content": 123},
        "not-a-dict",
    ],
}


@pytest.mark.asyncio
async def test_session_history_keeps_only_non_empty_user_assistant_rows() -> None:
    async with HermesRemoteClient(
        BASE_URL, API_KEY, transport=_history_handler(HISTORY_OK)
    ) as client:
        history = await client.get_session_history("session-1")

    assert history == [
        {"role": "user", "content": "  hello  "},
        {"role": "assistant", "content": "hi there"},
    ]


@pytest.mark.asyncio
async def test_session_history_truncates_to_the_last_40_rows() -> None:
    payload = {
        "object": "list",
        "data": [{"role": "user", "content": f"message-{index}"} for index in range(60)],
    }
    async with HermesRemoteClient(BASE_URL, API_KEY, transport=_history_handler(payload)) as client:
        history = await client.get_session_history("session-1")

    assert len(history) == 40
    assert history[0]["content"] == "message-20"
    assert history[-1]["content"] == "message-59"


@pytest.mark.asyncio
async def test_session_history_encodes_identifier_into_the_path() -> None:
    capture: list[httpx.Request] = []
    async with HermesRemoteClient(
        BASE_URL,
        API_KEY,
        transport=_history_handler(HISTORY_OK, capture=capture),
    ) as client:
        await client.get_session_history("session id/1")

    assert capture[0].url.raw_path == b"/api/sessions/session%20id%2F1/messages"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"object": "collection", "data": []},
        {"object": "list", "data": "not-a-list"},
        {"object": "list"},
    ],
)
@pytest.mark.asyncio
async def test_session_history_rejects_payloads_off_contract(payload: dict[str, Any]) -> None:
    async with HermesRemoteClient(BASE_URL, API_KEY, transport=_history_handler(payload)) as client:
        with pytest.raises(HermesRemoteProtocolError, match="invalid_session_history"):
            await client.get_session_history("session-1")


@pytest.mark.asyncio
async def test_session_history_propagates_http_error() -> None:
    async with HermesRemoteClient(
        BASE_URL,
        API_KEY,
        transport=_history_handler(status=502),
    ) as client:
        with pytest.raises(HermesRemoteHTTPError) as exc_info:
            await client.get_session_history("session-1")
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_stream_events_raises_http_error_on_failure_status() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="missing")

    async with HermesRemoteClient(
        BASE_URL, API_KEY, transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(HermesRemoteHTTPError) as exc_info:
            await _collect(client.stream_events("run-1"))
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_stream_events_parses_named_and_data_only_frames() -> None:
    frames = (
        b"event: run.delta\n"
        b'data: {"output":"hi"}\n'
        b"\n"
        b'data: {"event":"tick","output":"t"}\n'
        b"\n"
        b"data: {\n"
        b'data:   "a": 1,\n'
        b'data:   "b": 2\n'
        b"data: }\n"
        b"\n"
        b"data: [DONE]\n"
        b"\n"
        b'data: {"event":"never"}\n'
        b"\n"
    )
    async with HermesRemoteClient(BASE_URL, API_KEY, transport=_sse_transport(frames)) as client:
        events = await _collect(client.stream_events("run-1"))

    assert events == [
        {"output": "hi", "event": "run.delta"},
        {"event": "tick", "output": "t"},
        {"a": 1, "b": 2},
    ]


@pytest.mark.asyncio
async def test_stream_events_ignores_noise_without_pending_data() -> None:
    frames = b'  \nnot-a-directive\ndata: {"event":"run.completed"}\n\n'
    async with HermesRemoteClient(BASE_URL, API_KEY, transport=_sse_transport(frames)) as client:
        events = await _collect(client.stream_events("run-1"))

    assert events == [{"event": "run.completed"}]


@pytest.mark.asyncio
async def test_stream_events_rejects_malformed_json_data() -> None:
    frames = b"data: {not-json}\n\n"
    async with HermesRemoteClient(BASE_URL, API_KEY, transport=_sse_transport(frames)) as client:
        with pytest.raises(HermesRemoteProtocolError, match="invalid_sse_json"):
            await _collect(client.stream_events("run-1"))


@pytest.mark.asyncio
async def test_stream_events_rejects_non_object_json_data() -> None:
    frames = b"data: [1, 2, 3]\n\n"
    async with HermesRemoteClient(BASE_URL, API_KEY, transport=_sse_transport(frames)) as client:
        with pytest.raises(HermesRemoteProtocolError, match="invalid_sse_event"):
            await _collect(client.stream_events("run-1"))


@pytest.mark.asyncio
async def test_stream_events_targets_run_specific_path() -> None:
    capture: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capture.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"data: [DONE]\n\n",
        )

    async with HermesRemoteClient(
        BASE_URL, API_KEY, transport=httpx.MockTransport(handler)
    ) as client:
        await _collect(client.stream_events("run-42"))

    assert capture[0].url.path == "/v1/runs/run-42/events"


@pytest.mark.asyncio
async def test_stream_events_keeps_event_name_only_until_next_frame() -> None:
    frames = b'event: stale\n\ndata: {"event":"named.explicitly"}\n\ndata: {"output":"plain"}\n\n'
    async with HermesRemoteClient(BASE_URL, API_KEY, transport=_sse_transport(frames)) as client:
        events = await _collect(client.stream_events("run-1"))

    assert events == [
        {"event": "named.explicitly"},
        {"output": "plain"},
    ]
