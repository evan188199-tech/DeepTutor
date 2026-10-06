"""Behavioral tests for Hermes gateway SSE event mapping."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from deeptutor.services.subagent.hermes_remote_client import (
    HermesRemoteClient,
    HermesRemoteHTTPError,
    HermesRemoteProtocolError,
)
from deeptutor.services.subagent.hermes_remote_events import HermesRemoteEventMapper
from deeptutor.services.subagent.types import (
    EVENT_ERROR,
    EVENT_LOG,
    EVENT_REASONING,
    EVENT_TEXT,
    EVENT_TOOL,
    EVENT_TOOL_RESULT,
    ConsultResult,
)

_SSE_STREAM_PATH = "/v1/runs/run-1/events"


class _FakeClient:
    """In-memory HermesRemoteClient double: records posts, raises on demand."""

    def __init__(self, *, failures: dict[str, BaseException] | None = None) -> None:
        self.approvals: list[tuple[str, dict[str, Any]]] = []
        self.stops: list[str] = []
        self.failures = failures or {}

    async def post_json(self, path: str, payload: dict[str, Any], **_: Any) -> dict[str, Any]:
        if path.endswith("/approval"):
            if "/approval" in self.failures:
                raise self.failures["/approval"]
            self.approvals.append((path, payload))
            return {"resolved": 1}
        if path.endswith("/stop"):
            self.stops.append(path)
            if "/stop" in self.failures:
                raise self.failures["/stop"]
            return {"status": "stopping"}
        return {}


def _mapper(
    client: Any,
    result: ConsultResult | None = None,
    *,
    auto_approve: bool = True,
    emit_log: list[tuple[str, str, dict[str, Any], dict[str, Any] | None]] | None = None,
) -> HermesRemoteEventMapper:
    record = emit_log if emit_log is not None else []

    async def emit(
        kind: str,
        text: str,
        event: dict[str, Any],
        meta: dict[str, Any] | None = None,
    ) -> None:
        record.append((kind, text, event, meta))

    return HermesRemoteEventMapper(
        client,
        "run-1",
        result if result is not None else ConsultResult(),
        emit,
        auto_approve=auto_approve,
    )


def _sse_response(frames: list[str]) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content="".join(frames).encode(),
    )


def _event_frame(name: str, payload: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


# --- SSE 解码：event:/data: 帧拼装、keepalive 注释、终止标记、畸形帧 ---


@pytest.mark.asyncio
async def test_stream_events_decodes_named_frames() -> None:
    """event: 帧名合并进 data 载荷后按序交付。"""
    transport = httpx.MockTransport(
        lambda _: _sse_response(
            [
                _event_frame("message.delta", {"delta": "Hi"}),
                _event_frame("run.completed", {"output": "Hi"}),
            ]
        )
    )
    async with HermesRemoteClient("http://hermes.test", "key", transport=transport) as client:
        decoded = [event async for event in client.stream_events("run-1")]

    assert decoded == [
        {"event": "message.delta", "delta": "Hi"},
        {"event": "run.completed", "output": "Hi"},
    ]


@pytest.mark.asyncio
async def test_stream_events_treats_comments_as_keepalive_and_stops_on_done() -> None:
    """`: ping` 注释帧映射为 keepalive；`[DONE]` 静默终止迭代器。"""
    body = (
        b": ping\n\n"
        b'data: {"event": "message.delta", "delta": "x"}\n\n'
        b"data: [DONE]\n\n"
        b'data: {"event": "message.delta", "delta": "after-done"}\n\n'
    )
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body,
        )
    )
    async with HermesRemoteClient("http://hermes.test", "key", transport=transport) as client:
        decoded = [event async for event in client.stream_events("run-1")]

    assert decoded == [{"event": "gateway.keepalive"}, {"event": "message.delta", "delta": "x"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b"data: not-json\n\n", "invalid_sse_json"),
        (b"data: [1, 2]\n\n", "invalid_sse_event"),
    ],
)
async def test_stream_events_rejects_malformed_frames(raw: bytes, code: str) -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=raw,
        )
    )
    async with HermesRemoteClient("http://hermes.test", "key", transport=transport) as client:
        with pytest.raises(HermesRemoteProtocolError) as excinfo:
            async for _ in client.stream_events("run-1"):
                pass

    assert excinfo.value.code == code


@pytest.mark.asyncio
async def test_stream_events_surfaces_http_failure_status() -> None:
    """非 2xx 流响应直接抛 HTTPError，调用方据此走断流降级路径。"""
    transport = httpx.MockTransport(lambda _: httpx.Response(503))
    async with HermesRemoteClient("http://hermes.test", "key", transport=transport) as client:
        with pytest.raises(HermesRemoteHTTPError) as excinfo:
            async for _ in client.stream_events("run-1"):
                pass

    assert excinfo.value.status_code == 503


# --- 正常映射：文本累积、工具合并、推理、日志兜底 ---


@pytest.mark.asyncio
async def test_handle_accumulates_text_and_tracks_final() -> None:
    result = ConsultResult()
    emitted: list[Any] = []
    mapper = _mapper(_FakeClient(), result, emit_log=emitted)

    text = await mapper.handle({"event": "message.delta", "delta": "Hello "}, "")
    text = await mapper.handle({"event": "message.delta", "delta": "world"}, text)

    assert text == "Hello world"
    assert result.final_text == "Hello world"
    assert [(kind, payload) for kind, payload, _, _ in emitted] == [
        (EVENT_TEXT, "Hello "),
        (EVENT_TEXT, "Hello world"),
    ]
    assert all(meta == {"merge_id": "hermes_remote:final"} for _, _, _, meta in emitted)


@pytest.mark.asyncio
async def test_handle_maps_tools_and_reasoning_with_merge_ids() -> None:
    emitted: list[Any] = []
    mapper = _mapper(_FakeClient(), emit_log=emitted)

    await mapper.handle({"event": "tool.started", "tool": "read", "preview": "notes"}, "")
    await mapper.handle({"event": "tool.completed", "tool": "read", "error": True}, "")
    await mapper.handle({"event": "reasoning.available", "text": "plan"}, "")

    kinds = [(kind, payload, meta) for kind, payload, _, meta in emitted]
    assert kinds == [
        (EVENT_TOOL, "read: notes", {"merge_id": "hermes_remote:tool:read"}),
        (EVENT_TOOL_RESULT, "read: error", {"merge_id": "hermes_remote:tool:read"}),
        (EVENT_REASONING, "plan", None),
    ]


@pytest.mark.asyncio
async def test_handle_emits_log_for_unknown_and_unnamed_events() -> None:
    emitted: list[Any] = []
    mapper = _mapper(_FakeClient(), emit_log=emitted)

    text = await mapper.handle({"event": "gateway.hiccup"}, "kept")
    text = await mapper.handle({}, text)

    assert text == "kept"
    assert [(kind, payload) for kind, payload, _, _ in emitted] == [
        (EVENT_LOG, "gateway.hiccup"),
        (EVENT_LOG, "gateway event"),
    ]


@pytest.mark.asyncio
async def test_handle_swallows_keepalive_without_emitting() -> None:
    emitted: list[Any] = []
    mapper = _mapper(_FakeClient(), emit_log=emitted)

    text = await mapper.handle({"event": "gateway.keepalive"}, "same")

    assert text == "same"
    assert emitted == []


@pytest.mark.asyncio
@pytest.mark.parametrize("auto_approve", [True, False])
async def test_handle_answers_approval_per_policy(auto_approve: bool) -> None:
    client = _FakeClient()
    emitted: list[Any] = []
    mapper = _mapper(client, auto_approve=auto_approve, emit_log=emitted)

    text = await mapper.handle({"event": "approval.request", "tool": "shell"}, "")

    expected_choice = "once" if auto_approve else "deny"
    assert client.approvals == [("/v1/runs/run-1/approval", {"choice": expected_choice})]
    verb = "approved" if auto_approve else "denied"
    assert [(kind, payload) for kind, payload, _, _ in emitted] == [
        (EVENT_LOG, f"approval {verb}"),
    ]
    assert client.stops == []
    assert text == ""


# --- 断流/失败边界：审批失败触发 stop 并短路，run.failed/cancelled 置败 ---


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        HermesRemoteHTTPError(500),
        HermesRemoteProtocolError("invalid_json_object"),
        httpx.ConnectError("offline"),
    ],
    ids=["http", "protocol", "request"],
)
async def test_handle_marks_approval_failure_and_stops_run(exc: BaseException) -> None:
    client = _FakeClient(failures={"/approval": exc})
    result = ConsultResult(final_text="partial")
    emitted: list[Any] = []
    mapper = _mapper(client, result, emit_log=emitted)

    text = await mapper.handle({"event": "approval.request"}, "partial")

    assert text == "partial"
    assert result.success is False
    assert result.error == "approval_failed"
    assert client.stops == ["/v1/runs/run-1/stop"]
    kinds = [(kind, payload) for kind, payload, _, _ in emitted]
    assert kinds == [(EVENT_ERROR, "approval_failed")]


@pytest.mark.asyncio
async def test_stop_swallows_stop_endpoint_failure() -> None:
    """审批失败后再调 stop 也失败时异常被吞掉，结果仍标记 approval_failed。"""
    client = _FakeClient(
        failures={
            "/approval": HermesRemoteHTTPError(500),
            "/stop": HermesRemoteHTTPError(409),
        }
    )
    result = ConsultResult()
    emitted: list[Any] = []
    mapper = _mapper(client, result, emit_log=emitted)

    text = await mapper.handle({"event": "approval.request"}, "")

    assert text == ""
    assert result.error == "approval_failed"
    assert client.stops == ["/v1/runs/run-1/stop"]
    assert [(kind, payload) for kind, payload, _, _ in emitted] == [
        (EVENT_ERROR, "approval_failed"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event", "error"),
    [
        ({"event": "run.failed"}, "run_failed"),
        ({"event": "run.cancelled"}, "run_cancelled"),
    ],
)
async def test_handle_marks_terminal_failures(event: dict[str, Any], error: str) -> None:
    result = ConsultResult(final_text="draft")
    emitted: list[Any] = []
    mapper = _mapper(_FakeClient(), result, emit_log=emitted)

    text = await mapper.handle(event, "draft")

    assert text == "draft"
    assert result.success is False
    assert result.error == error
    assert [(kind, payload) for kind, payload, _, _ in emitted] == [(EVENT_ERROR, error)]


@pytest.mark.asyncio
async def test_run_completed_reports_reconciled_output_once() -> None:
    """网关 output 与已流出文本一致时不重复播报；不一致时整体替换一次。"""
    result = ConsultResult()
    emitted: list[Any] = []
    mapper = _mapper(_FakeClient(), result, emit_log=emitted)

    text = await mapper.handle({"event": "message.delta", "delta": "streamed"}, "")
    reconciled = await mapper.handle({"event": "run.completed", "output": "streamed"}, text)
    replaced = await mapper.handle(
        {"event": "run.completed", "output": "authoritative answer"},
        reconciled,
    )

    assert result.final_text == "authoritative answer"
    assert replaced == "streamed"
    assert [(kind, payload) for kind, payload, _, _ in emitted] == [
        (EVENT_TEXT, "streamed"),
        (EVENT_TEXT, "authoritative answer"),
    ]


# --- 畸形事件容错：缺失字段一律降级为空串/占位标签 ---


@pytest.mark.asyncio
async def test_handle_tolerates_missing_delta_and_empty_output() -> None:
    result = ConsultResult(final_text="")
    emitted: list[Any] = []
    mapper = _mapper(_FakeClient(), result, emit_log=emitted)

    text = await mapper.handle({"event": "message.delta"}, "kept")
    text = await mapper.handle({"event": "run.completed"}, text)

    assert text == "kept"
    assert result.final_text == "kept"
    assert emitted == []


@pytest.mark.asyncio
async def test_handle_uses_placeholder_labels_for_missing_tool_fields() -> None:
    emitted: list[Any] = []
    mapper = _mapper(_FakeClient(), emit_log=emitted)

    await mapper.handle({"event": "tool.started", "preview": "ps aux"}, "")
    await mapper.handle({"event": "tool.completed", "error": "boom"}, "")
    await mapper.handle({"event": "reasoning.available"}, "")

    payloads = [payload for _, payload, _, _ in emitted]
    assert payloads == ["tool: ps aux", "tool: error", ""]


@pytest.mark.asyncio
async def test_handle_coerces_nonstring_scalar_fields() -> None:
    """delta/output 是任意标量时按 str() 降级，不抛异常。"""
    result = ConsultResult()
    emitted: list[Any] = []
    mapper = _mapper(_FakeClient(), result, emit_log=emitted)

    text = await mapper.handle({"event": "message.delta", "delta": 42}, "")
    text = await mapper.handle({"event": "run.completed", "output": 3.5}, text)

    assert text == "42"
    assert result.final_text == "3.5"
    assert [payload for _, payload, _, _ in emitted] == ["42", "3.5"]
