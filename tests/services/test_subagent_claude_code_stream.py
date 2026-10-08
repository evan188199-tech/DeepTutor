"""Claude Code backend: the headless ``claude -p --output-format stream-json``
consumption path in :mod:`deeptutor.services.subagent.claude_code`.

The child process is always faked — ``stream_process_lines`` is monkeypatched
with a scripted async generator standing in for the CLI, so the suite drives
``consult`` end-to-end over lines exactly as ``claude`` would print them
(stdout / stderr / exit channels) without spawning a real CLI. Covers the four
behavior classes of the stream loop: well-formed event mapping (init /
assistant / tool_use / partial deltas), malformed-line tolerance, process exit
codes, and the probe timeout / spawn-failure paths.
"""

from __future__ import annotations

import json
import sys

import pytest

from deeptutor.services.subagent import claude_code as cc_mod
from deeptutor.services.subagent.claude_code import (
    ClaudeCodeBackend,
    _render_tool_result,
    _render_tool_use,
)
from deeptutor.services.subagent.process import probe_version
from deeptutor.services.subagent.types import SubagentEvent

INIT = {"type": "system", "subtype": "init", "session_id": "sess-7", "model": "sonnet"}


def _json_lines(*events: dict, exit_code: str = "0") -> list[tuple[str, str]]:
    return [("stdout", json.dumps(e)) for e in events] + [("exit", exit_code)]


def _patch_stream(monkeypatch, lines, captured=None) -> None:
    async def stream(cmd, *, cwd=None):
        if captured is not None:
            captured.append(list(cmd))
        for item in lines:
            yield item

    monkeypatch.setattr(cc_mod, "stream_process_lines", stream)


def _collector() -> tuple[list[SubagentEvent], object]:
    events: list[SubagentEvent] = []

    async def on_event(event: SubagentEvent) -> None:
        events.append(event)

    return events, on_event


# ---- well-formed event stream --------------------------------------------------


@pytest.mark.asyncio
async def test_consult_full_stream_maps_init_assistant_tool_and_result(monkeypatch) -> None:
    captured: list[list[str]] = []
    _patch_stream(
        monkeypatch,
        _json_lines(
            INIT,
            {
                "type": "assistant",
                "session_id": "sess-7",
                "message": {
                    "id": "m1",
                    "content": [
                        {"type": "text", "text": "Reading the module."},
                        {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la\nsrc"}},
                    ],
                },
            },
            {
                "type": "user",
                "session_id": "sess-7",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "content": [{"type": "text", "text": "file.py\npkg/"}],
                        }
                    ]
                },
            },
            {
                "type": "assistant",
                "session_id": "sess-7",
                "message": {"id": "m2", "content": [{"type": "text", "text": "All set."}]},
            },
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "All set.",
                "session_id": "sess-7",
            },
        ),
        captured,
    )
    events, on_event = _collector()

    result = await ClaudeCodeBackend().consult("q?", on_event=on_event)

    # The headless command was built as documented.
    assert captured[0][:7] == [
        "claude",
        "-p",
        "q?",
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
    ]
    assert result.success is True
    assert result.session_id == "sess-7"
    assert result.final_text == "All set."
    # init log, assistant text, tool call, tool result, final assistant text —
    # the mirrored result text is NOT re-emitted over the assistant answer.
    assert [(e.kind, e.text) for e in events] == [
        ("log", "Session started · sonnet"),
        ("text", "Reading the module."),
        ("tool", "Bash(ls -la src)"),
        ("tool_result", "file.py\npkg/"),
        ("text", "All set."),
    ]
    assert result.event_count == len(events)
    assert events[0].raw["session_id"] == "sess-7"
    assert events[2].raw["name"] == "Bash"


@pytest.mark.asyncio
async def test_consult_streams_partial_deltas_and_assistant_finalizes(monkeypatch) -> None:
    _patch_stream(
        monkeypatch,
        _json_lines(
            {"type": "stream_event", "event": {"type": "message_start", "message": {"id": "m9"}}},
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            },
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Hel"},
                },
            },
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "lo"},
                },
            },
            {
                "type": "assistant",
                "message": {"id": "m9", "content": [{"type": "text", "text": "Hello"}]},
            },
        ),
    )
    events, on_event = _collector()

    result = await ClaudeCodeBackend().consult("q", on_event=on_event)

    texts = [(e.text, e.meta.get("merge_id")) for e in events if e.kind == "text"]
    assert texts == [("Hel", "txt:m9:0"), ("Hello", "txt:m9:0"), ("Hello", "txt:m9:0")]
    assert result.final_text == "Hello"
    assert result.success is True


@pytest.mark.asyncio
async def test_consult_emits_reasoning_from_block_and_delta(monkeypatch) -> None:
    _patch_stream(
        monkeypatch,
        _json_lines(
            {"type": "stream_event", "event": {"type": "message_start", "message": {"id": "m1"}}},
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "thinking_delta", "thinking": "Plan"},
                },
            },
            {
                "type": "assistant",
                "message": {
                    "id": "m1",
                    "content": [
                        {"type": "thinking", "thinking": "Plan the approach."},
                        {"type": "text", "text": "Done."},
                    ],
                },
            },
        ),
    )
    events, on_event = _collector()

    result = await ClaudeCodeBackend().consult("q", on_event=on_event)

    reasoning = [(e.text, e.meta.get("merge_id")) for e in events if e.kind == "reasoning"]
    assert reasoning == [("Plan", "rsn:m1:0"), ("Plan the approach.", "rsn:m1:0")]
    assert result.final_text == "Done."


@pytest.mark.asyncio
async def test_consult_result_error_subtype_fails_run_and_surfaces_text(monkeypatch) -> None:
    # Degenerate failing run: no assistant text streamed, the result event both
    # fails the run and carries the only answer text, so it is still surfaced.
    _patch_stream(
        monkeypatch,
        _json_lines(
            {
                "type": "result",
                "subtype": "error_max_turns",
                "is_error": True,
                "result": "Hit the turn limit.",
            }
        ),
    )
    events, on_event = _collector()

    result = await ClaudeCodeBackend().consult("q", on_event=on_event)

    assert result.success is False
    assert result.final_text == "Hit the turn limit."
    assert ("text", "Hit the turn limit.") in [(e.kind, e.text) for e in events]


# ---- malformed lines ------------------------------------------------------------


@pytest.mark.asyncio
async def test_consult_tolerates_malformed_lines(monkeypatch) -> None:
    _patch_stream(
        monkeypatch,
        [
            ("stdout", ""),  # blank: dropped entirely
            ("stdout", "claude: some plain-text banner"),  # not JSON
            ("stdout", '["a", "b"]'),  # JSON but not an object
            ("stdout", '{"type": "assistant", "message"'),  # truncated JSON
            (
                "stdout",
                json.dumps(
                    {"type": "assistant", "message": {"content": [{"type": "text", "text": "OK"}]}}
                ),
            ),
            ("exit", "0"),
        ],
    )
    events, on_event = _collector()

    result = await ClaudeCodeBackend().consult("q", on_event=on_event)

    logs = [e for e in events if e.kind == "log"]
    assert [(e.text, e.raw) for e in logs] == [
        ("claude: some plain-text banner", {"stream": "stdout"}),
        ('["a", "b"]', {"stream": "stdout"}),
        ('{"type": "assistant", "message"', {"stream": "stdout"}),
    ]
    # The stream kept flowing after the garbage and the answer still landed.
    assert result.success is True
    assert result.final_text == "OK"


@pytest.mark.asyncio
async def test_consult_forwards_stderr_as_log_events(monkeypatch) -> None:
    _patch_stream(
        monkeypatch,
        [
            ("stderr", "background hook started"),
            ("stderr", "   "),  # blank stderr: ignored
            (
                "stdout",
                json.dumps(
                    {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}
                ),
            ),
            ("stderr", "hook finished"),
            ("exit", "0"),
        ],
    )
    events, on_event = _collector()

    result = await ClaudeCodeBackend().consult("q", on_event=on_event)

    assert [(e.kind, e.text, e.raw) for e in events if e.kind == "log"] == [
        ("log", "background hook started", {"stream": "stderr"}),
        ("log", "hook finished", {"stream": "stderr"}),
    ]
    assert result.final_text == "hi"


@pytest.mark.asyncio
async def test_consult_drops_telemetry_and_logs_unknown_events(monkeypatch) -> None:
    _patch_stream(
        monkeypatch,
        _json_lines(
            {"type": "rate_limit_event", "utilization": 0.5},
            {"type": "control_response", "response": {}},
            {"type": "control_request", "request": {}},
            {"type": "mystery_event", "payload": "x"},
        ),
    )
    events, on_event = _collector()

    result = await ClaudeCodeBackend().consult("q", on_event=on_event)

    # Telemetry noise is dropped, the unknown event stays visible as one log.
    assert [(e.kind, e.text) for e in events] == [
        ("log", '{"type": "mystery_event", "payload": "x"}')
    ]
    assert result.success is True


# ---- process exit codes ---------------------------------------------------------


@pytest.mark.asyncio
async def test_consult_nonzero_exit_without_answer_fails(monkeypatch) -> None:
    _patch_stream(
        monkeypatch,
        _json_lines(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "partial"}]},
            },
            exit_code="1",
        ),
    )
    events, on_event = _collector()

    result = await ClaudeCodeBackend().consult("q", on_event=on_event)

    assert result.success is False
    assert result.error == "claude exited with code 1"
    assert result.final_text == "partial"  # streamed text survives the failure
    assert [e for e in events if e.kind == "error"][-1].raw == {"returncode": "1"}


@pytest.mark.asyncio
async def test_consult_nonzero_exit_after_result_keeps_success(monkeypatch) -> None:
    # The final answer was already delivered via the result event, so a late
    # non-zero exit code does not turn the consult into a failure.
    _patch_stream(
        monkeypatch,
        _json_lines(
            {"type": "result", "subtype": "success", "result": "All set."},
            exit_code="2",
        ),
    )
    events, on_event = _collector()

    result = await ClaudeCodeBackend().consult("q", on_event=on_event)

    assert result.success is True
    assert result.final_text == "All set."
    assert not [e for e in events if e.kind == "error"]


# ---- timeout / spawn-failure paths ----------------------------------------------


@pytest.mark.asyncio
async def test_consult_spawn_failure_surfaces_error(monkeypatch) -> None:
    async def missing_cli(cmd, *, cwd=None):
        raise FileNotFoundError(2, "No such file or directory", "claude")
        yield  # pragma: no cover - unreachable; keeps this an async generator

    monkeypatch.setattr(cc_mod, "stream_process_lines", missing_cli)
    events, on_event = _collector()

    result = await ClaudeCodeBackend().consult("q", on_event=on_event)

    assert result.success is False
    assert "No such file or directory" in result.error
    assert [(e.kind, e.text) for e in events] == [
        ("error", "[Errno 2] No such file or directory: 'claude'")
    ]
    assert result.final_text == ""


@pytest.mark.asyncio
async def test_detect_maps_probe_outcome(monkeypatch) -> None:
    backend = ClaudeCodeBackend()

    monkeypatch.setattr(cc_mod, "probe_version", _fake_probe(True, "claude 2.1.0"))
    detected = await backend.detect()
    assert (detected.kind, detected.available, detected.version, detected.detail) == (
        "claude_code",
        True,
        "claude 2.1.0",
        "",
    )

    monkeypatch.setattr(cc_mod, "probe_version", _fake_probe(False, "not installed"))
    detected = await backend.detect()
    assert detected.available is False
    assert detected.version == ""
    assert detected.detail == "not installed"


@pytest.mark.asyncio
async def test_detect_maps_probe_timeout_detail(monkeypatch) -> None:
    monkeypatch.setattr(cc_mod, "probe_version", _fake_probe(False, "probe timed out"))
    detected = await ClaudeCodeBackend().detect()
    assert detected.available is False
    assert detected.detail == "probe timed out"


@pytest.mark.asyncio
async def test_probe_version_times_out_hung_pseudo_process() -> None:
    # A hung child (the probe's own timeout path) fails the probe and is torn
    # down — driven by a python stand-in, never the real claude CLI.
    ok, text = await probe_version(
        [sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.25
    )
    assert ok is False
    assert text == "probe timed out"


def _fake_probe(ok: bool, text: str):
    async def probe(cmd, *, timeout: float = 8.0):
        return ok, text

    return probe


# ---- tool header / result rendering ---------------------------------------------


def test_render_tool_use_single_line_primary_arg_and_cap() -> None:
    # The salient argument is surfaced single-line; "command" wins over other
    # known args; a too-long value is capped with an ellipsis; no input at all
    # degrades to the bare tool name.
    assert _render_tool_use({"name": "Bash", "input": {"command": "ls\n-la", "url": "x"}}) == (
        "Bash(ls -la)"
    )
    long_cmd = "python " + "-".join(["segment"] * 40)
    rendered = _render_tool_use({"name": "Bash", "input": {"command": long_cmd}})
    assert rendered.startswith("Bash(python ") and rendered.endswith("…)")
    # 160-char body cap + "Bash(" + ")" + the ellipsis marker.
    assert "\n" not in rendered and len(rendered) == 168
    assert _render_tool_use({"name": "Read", "input": {}}) == "Read"
    fallback = _render_tool_use({"name": "WebSearch", "input": {"limit": 5}})
    assert fallback.startswith("WebSearch({") and "limit" in fallback


def test_render_tool_result_joins_parts_and_empty_fallback() -> None:
    block = {
        "content": [
            {"type": "text", "text": "first"},
            {"type": "image", "source": {}},
            {"type": "text", "text": "second"},
        ]
    }
    assert _render_tool_result(block) == "first\nsecond"
    assert _render_tool_result({"content": "plain string"}) == "plain string"
    assert _render_tool_result({"content": "   "}) == "(empty result)"
