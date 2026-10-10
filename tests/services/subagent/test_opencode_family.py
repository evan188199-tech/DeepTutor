"""Focused tests for the opencode-family backend driver.

Covers the areas the shared suite leaves thin: ``detect`` probing, the full
``consult`` orchestration over a mocked HTTP transport (session creation,
config merge into the posted prompt body, authoritative vs streamed final
text, server-start / message-post / bus-error failures, turn cancellation
with a best-effort abort), SSE attach waiting, and the small pure helpers.

The transport layer is fully mocked via ``httpx.MockTransport`` — no real CLI
is spawned and no network is touched.
"""

from __future__ import annotations

import asyncio
import json
import typing

import httpx
import pytest

from deeptutor.services.subagent import opencode_family as of
from deeptutor.services.subagent.config import BackendConfig
from deeptutor.services.subagent.opencode_family import MimoBackend, OpencodeBackend

# ---- fakes & plumbing --------------------------------------------------------


class _FakeHandle:
    """Minimal stand-in for ``opencode_server.ServerHandle``."""

    base_url = "http://opencode.test"
    auth = None

    def __init__(self) -> None:
        self.touches = 0
        self.kwargs: dict = {}

    def touch(self) -> None:
        self.touches += 1


def _sse_bytes(events: typing.Sequence[dict]) -> bytes:
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


async def _stream(payload: bytes):
    yield payload


def _install_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Route every ``AsyncClient`` the driver opens through ``handler``."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs.setdefault("transport", transport)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(of.httpx, "AsyncClient", factory)


def _router(
    *,
    sse_events: typing.Sequence[dict] = (),
    message_response: httpx.Response | Exception | None = None,
    session_id: str = "ses_new",
    on_message=None,
    on_abort=None,
):
    """Build a MockTransport handler routing the serve-API surface."""
    requests: list[tuple[str, str]] = []
    bodies: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        requests.append((request.method, path))
        if request.method == "GET" and path == "/event":
            return httpx.Response(200, content=_stream(_sse_bytes(sse_events)))
        if request.method == "POST" and path == "/session":
            return httpx.Response(200, json={"id": session_id})
        if request.method == "POST" and path.endswith("/message"):
            if on_message is not None:
                on_message(json.loads(request.content))
                bodies.append(json.loads(request.content))
            if isinstance(message_response, BaseException):
                raise message_response
            return message_response or httpx.Response(200, json={"parts": []})
        if request.method == "POST" and path.endswith("/abort"):
            if on_abort is not None:
                on_abort()
            return httpx.Response(200, json={})
        if request.method == "POST" and "/permissions/" in path:
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"error": "unexpected route"})

    return handler, requests, bodies


async def _fake_acquire(handle: _FakeHandle):
    async def acquire(cli_command, **kwargs):
        handle.kwargs = {"cli": cli_command, **kwargs}
        return handle

    return acquire


async def _collect_events():
    emitted: list[tuple[str, str]] = []

    async def on_event(event):
        emitted.append((event.kind, event.text))

    return emitted, on_event


def _delta(session: str, pid: str, text: str) -> dict:
    return {
        "type": "message.part.delta",
        "properties": {"sessionID": session, "partID": pid, "field": "text", "delta": text},
    }


# ---- detect: backend probing ---------------------------------------------------


@pytest.mark.asyncio
async def test_detect_reports_version_when_probe_succeeds(monkeypatch) -> None:
    seen: list[list[str]] = []

    async def probe(cmd, **kwargs):
        seen.append(list(cmd))
        return True, "opencode 1.2.3"

    monkeypatch.setattr(of, "probe_version", probe)
    result = await OpencodeBackend().detect()
    assert seen == [["opencode", "--version"]]
    assert result.available is True
    assert result.version == "opencode 1.2.3"
    assert result.detail == ""


@pytest.mark.asyncio
async def test_detect_reports_detail_when_cli_missing(monkeypatch) -> None:
    async def probe(cmd, **kwargs):
        return False, ""

    monkeypatch.setattr(of, "probe_version", probe)
    result = await MimoBackend().detect()
    assert result.available is False
    assert result.version == ""
    assert "not found on PATH" in result.detail


def test_family_backends_expose_cli_identity() -> None:
    backend = OpencodeBackend()
    assert (backend.kind, backend.cli_command) == ("opencode", "opencode")
    assert (backend.env_prefix, backend.basic_auth_user) == ("OPENCODE", "opencode")
    mimo = MimoBackend()
    assert (mimo.kind, mimo.cli_command) == ("mimo", "mimo")
    assert (mimo.env_prefix, mimo.basic_auth_user) == ("MIMOCODE", "mimocode")
    assert mimo.display_name == "MiMo Code"
    assert isinstance(backend, of.OpencodeFamilyBackend)


# ---- consult: orchestration over a mocked transport ---------------------------


@pytest.mark.asyncio
async def test_consult_happy_path_authoritative_final_text_and_config_merge(
    monkeypatch,
) -> None:
    handle = _FakeHandle()
    monkeypatch.setattr(of, "acquire_server", await _fake_acquire(handle))
    captured: dict = {}

    def on_message(body: dict) -> None:
        captured.update(body)

    sse = [_delta("ses_new", "p1", "streamed…")]
    handler, requests, _ = _router(
        sse_events=sse,
        message_response=httpx.Response(
            200, json={"parts": [{"type": "text", "text": "Final answer"}]}
        ),
        on_message=on_message,
    )
    _install_transport(monkeypatch, handler)
    emitted, on_event = await _collect_events()

    config = BackendConfig(model="anthropic/claude-x", effort="high", system_prompt="sys")
    result = await OpencodeBackend().consult(
        "what?", on_event=on_event, cwd="/tmp/wd", config=config
    )

    assert result.success is True
    assert result.error == ""
    assert result.session_id == "ses_new"
    assert result.final_text == "Final answer"  # authoritative POST body wins
    assert handle.touches == 1
    assert handle.kwargs["cli"] == "opencode" and handle.kwargs["cwd"] == "/tmp/wd"
    assert handle.kwargs["env_prefix"] == "OPENCODE"
    assert ("POST", "/session") in requests and ("POST", "/session/ses_new/message") in requests
    # config merged into the fresh-session prompt body
    assert captured["model"] == {"providerID": "anthropic", "modelID": "claude-x"}
    assert captured["variant"] == "high"
    assert captured["system"] == "sys"
    assert captured["parts"][0] == {"type": "text", "text": "what?"}
    # the streamed delta reached the trace as a text event
    assert ("text", "streamed…") in emitted
    assert result.event_count >= 1


@pytest.mark.asyncio
async def test_consult_reuses_provided_session_without_creating_one(monkeypatch) -> None:
    handle = _FakeHandle()
    monkeypatch.setattr(of, "acquire_server", await _fake_acquire(handle))
    handler, requests, _ = _router(
        session_id="ses_new",
        message_response=httpx.Response(200, json={"parts": [{"type": "text", "text": "ok"}]}),
    )
    _install_transport(monkeypatch, handler)
    _, on_event = await _collect_events()

    result = await OpencodeBackend().consult(
        "again",
        on_event=on_event,
        session_id="ses_resume",
        config=BackendConfig(system_prompt="should be skipped on resume"),
    )

    assert result.session_id == "ses_resume"
    assert ("POST", "/session") not in requests  # no session created
    assert ("POST", "/session/ses_resume/message") in requests
    assert result.final_text == "ok"


@pytest.mark.asyncio
async def test_consult_server_start_failure_marks_result_and_emits_error(
    monkeypatch,
) -> None:
    async def broken_acquire(cli_command, **kwargs):
        raise RuntimeError("spawn failed")

    monkeypatch.setattr(of, "acquire_server", broken_acquire)
    emitted, on_event = await _collect_events()

    result = await OpencodeBackend().consult("q", on_event=on_event)

    assert result.success is False
    assert "failed to start opencode server" in result.error
    assert "spawn failed" in result.error
    assert emitted == [("error", result.error)]
    assert result.event_count == 1


@pytest.mark.asyncio
async def test_consult_message_post_failure_marks_result(monkeypatch) -> None:
    handle = _FakeHandle()
    monkeypatch.setattr(of, "acquire_server", await _fake_acquire(handle))
    handler, _, _ = _router(
        message_response=httpx.Response(500, json={"error": "nope"}),
    )
    _install_transport(monkeypatch, handler)
    emitted, on_event = await _collect_events()

    result = await OpencodeBackend().consult("q", on_event=on_event)

    assert result.success is False
    assert "500" in result.error
    assert emitted[-1][0] == "error" and "500" in emitted[-1][1]
    assert handle.touches == 1


@pytest.mark.asyncio
async def test_consult_falls_back_to_streamed_text(monkeypatch) -> None:
    handle = _FakeHandle()
    monkeypatch.setattr(of, "acquire_server", await _fake_acquire(handle))
    sse = [_delta("ses_new", "p1", "Hello "), _delta("ses_new", "p1", "world")]
    handler, _, _ = _router(
        sse_events=sse,
        # the POST response carries no usable text part
        message_response=httpx.Response(200, json={"parts": [{"type": "step-start"}]}),
    )
    _install_transport(monkeypatch, handler)
    _, on_event = await _collect_events()

    result = await OpencodeBackend().consult("q", on_event=on_event)

    assert result.success is True
    assert result.final_text == "Hello world"


@pytest.mark.asyncio
async def test_consult_bus_error_fails_result_when_no_text(monkeypatch) -> None:
    handle = _FakeHandle()
    monkeypatch.setattr(of, "acquire_server", await _fake_acquire(handle))
    sse = [
        {
            "type": "session.error",
            "properties": {
                "sessionID": "ses_new",
                "error": {"name": "ProviderError", "data": {"message": "boom"}},
            },
        }
    ]
    handler, _, _ = _router(sse_events=sse, message_response=httpx.Response(200, json={}))
    _install_transport(monkeypatch, handler)
    emitted, on_event = await _collect_events()

    result = await OpencodeBackend().consult("q", on_event=on_event)

    assert result.success is False
    assert result.error == "boom"
    assert ("error", "boom") in emitted
    assert result.final_text == ""


@pytest.mark.asyncio
async def test_consult_cancelled_turn_calls_abort(monkeypatch) -> None:
    handle = _FakeHandle()
    monkeypatch.setattr(of, "acquire_server", await _fake_acquire(handle))
    aborted: list[str] = []
    handler, requests, _ = _router(
        message_response=asyncio.CancelledError(),  # the user aborted the turn
        on_abort=lambda: aborted.append("yes"),
    )
    _install_transport(monkeypatch, handler)
    _, on_event = await _collect_events()

    with pytest.raises(asyncio.CancelledError):
        await OpencodeBackend().consult("q", on_event=on_event)

    assert aborted == ["yes"]
    assert ("POST", "/session/ses_new/abort") in requests
    assert handle.touches == 1


@pytest.mark.asyncio
async def test_consult_permission_asked_posts_reply_over_transport(monkeypatch) -> None:
    handle = _FakeHandle()
    monkeypatch.setattr(of, "acquire_server", await _fake_acquire(handle))
    ask = {
        "type": "permission.asked",
        "properties": {"id": "perm1", "sessionID": "ses_new", "title": "Run bash"},
    }
    handler, requests, bodies = _router(sse_events=[ask])
    _install_transport(monkeypatch, handler)
    emitted, on_event = await _collect_events()

    result = await OpencodeBackend().consult("q", on_event=on_event)

    assert ("POST", "/session/ses_new/permissions/perm1") in requests
    assert bodies == [{"response": "once"}]  # auto_approve defaults to True
    assert any(kind == "log" and "auto-approved" in text for kind, text in emitted)
    assert result.success is True


# ---- consult internals: session creation & SSE attach --------------------------


@pytest.mark.asyncio
async def test_create_session_rejects_missing_id() -> None:
    for payload in ({}, [1, 2]):
        client = httpx.AsyncClient(
            base_url="http://opencode.test",
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
        )
        try:
            with pytest.raises(RuntimeError, match="without an id"):
                await OpencodeBackend()._create_session(client)
        finally:
            await client.aclose()


def test_wait_attached_returns_when_attached() -> None:
    async def scenario() -> None:
        attached = asyncio.Event()

        async def setter() -> None:
            await asyncio.sleep(0.01)
            attached.set()

        setter_task = asyncio.create_task(setter())
        listener = asyncio.create_task(asyncio.sleep(5))
        try:
            await of._wait_attached(listener, attached)
        finally:
            listener.cancel()
            await asyncio.gather(listener, setter_task, return_exceptions=True)

    asyncio.run(scenario())


def test_wait_attached_surfaces_listener_error() -> None:
    async def scenario() -> None:
        async def boom() -> None:
            raise ValueError("bus refused")

        listener = asyncio.create_task(boom())
        with pytest.raises(ValueError, match="bus refused"):
            await of._wait_attached(listener, asyncio.Event())

    asyncio.run(scenario())


def test_wait_attached_times_out(monkeypatch) -> None:
    monkeypatch.setattr(of, "_ATTACH_TIMEOUT_SECONDS", 0.05)

    async def scenario() -> None:
        listener = asyncio.create_task(asyncio.sleep(5))
        try:
            with pytest.raises(RuntimeError, match="timed out attaching"):
                await of._wait_attached(listener, asyncio.Event())
        finally:
            listener.cancel()
            await asyncio.gather(listener, return_exceptions=True)

    asyncio.run(scenario())


# ---- pure helpers --------------------------------------------------------------


def test_image_part_encodes_and_skips_unreadable(tmp_path) -> None:
    img = tmp_path / "shot.jpg"
    payload = b"jpeg-bytes"
    img.write_bytes(payload)

    part = of._image_part(str(img))
    assert part is not None
    assert part["type"] == "file"
    assert part["mime"] == "image/jpeg"
    assert part["filename"] == "shot.jpg"
    assert part["url"].startswith("data:image/jpeg;base64,")

    assert of._image_part(str(tmp_path / "missing.png")) is None
    assert of._image_part(str(tmp_path)) is None  # a directory is unreadable


def test_response_parts_rejects_malformed_bodies() -> None:
    assert of._response_parts(httpx.Response(200, text="not json")) == []
    assert of._response_parts(httpx.Response(200, json=[1, 2])) == []
    assert of._response_parts(httpx.Response(200, json={"no_parts": 1})) == []
    mixed = [{"type": "text", "text": "a"}, "junk", 3]
    assert of._response_parts(httpx.Response(200, json={"parts": mixed})) == [
        {"type": "text", "text": "a"}
    ]


def test_render_tool_header_priority_compact_and_truncation() -> None:
    titled = {"tool": "bash", "id": "t1", "state": {"status": "completed", "title": "List files",
                                                     "input": {"command": "ls"}}}
    assert of._render_tool_header(titled, titled["state"]) == "List files(ls)"

    plain = {"tool": "bash", "id": "t2", "state": {"status": "running", "input": {"command": "ls -la"}}}
    assert of._render_tool_header(plain, plain["state"]) == "bash(ls -la)"

    no_args = {"tool": "bash", "id": "t3", "state": {"status": "running"}}
    assert of._render_tool_header(no_args, no_args["state"]) == "bash"

    compact = {"tool": "bash", "id": "t4", "state": {"status": "running", "input": {"foo": "bar", "n": 1}}}
    header = of._render_tool_header(compact, compact["state"])
    assert header == 'bash({"foo": "bar", "n": 1})'

    long_cmd = "a" * 200
    long_part = {"tool": "bash", "id": "t5", "state": {"status": "running", "input": {"command": long_cmd}}}
    header = of._render_tool_header(long_part, long_part["state"])
    assert header == f"bash({'a' * of._TOOL_HEADER_CHARS} …)"


def test_permission_label_variants() -> None:
    assert of._permission_label({"title": " Run bash "}) == "Run bash"
    assert of._permission_label({"permission": {"title": "Nested"}}) == "Nested"
    assert of._permission_label({"permission": {"id": "perm-id"}}) == "perm-id"
    assert of._permission_label({"permission": "bash"}) == "bash"
    assert of._permission_label({}) == ""


def test_error_message_variants() -> None:
    assert of._error_message({"error": {"data": {"message": "deep"}}}) == "deep"
    assert of._error_message({"error": {"message": "mid"}}) == "mid"
    assert of._error_message({"error": {"name": "ErrName"}}) == "ErrName"
    assert of._error_message({}) == "the agent reported a session error"
    assert of._error_message({"error": "plain string"}) == "the agent reported a session error"


def test_parse_json_rejects_non_json_and_non_dict() -> None:
    assert of._parse_json("") is None
    assert of._parse_json("plain text") is None
    assert of._parse_json("{bad json") is None
    assert of._parse_json("[1, 2]") is None  # array, not an event object
    assert of._parse_json('{"type": "x"}') == {"type": "x"}
