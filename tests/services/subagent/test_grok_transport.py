"""Grok CLI backend transport behavior, fully offline.

``stream_process_lines`` is monkeypatched with a scripted async generator, so
``consult`` is driven end-to-end over the CLI's native ``streaming-json``
frames. Covers request assembly (flags, resume, equals-form prompt), delta
accumulation with usage-block boundaries, sparse tool-call updates, and the
failure branches (malformed frames, missing completion, non-end_turn stops,
image rejection, non-zero exit).
"""

from __future__ import annotations

import json

import pytest

from deeptutor.services.subagent import grok as grok_mod
from deeptutor.services.subagent.config import BackendConfig
from deeptutor.services.subagent.grok import GrokBackend
from deeptutor.services.subagent.types import (
    EVENT_ERROR,
    EVENT_LOG,
    EVENT_TEXT,
    EVENT_TOOL,
    EVENT_TOOL_RESULT,
    SubagentEvent,
)


def _collector() -> tuple[list[SubagentEvent], object]:
    events: list[SubagentEvent] = []

    async def on_event(event: SubagentEvent) -> None:
        events.append(event)

    return events, on_event


def _patch_stream(monkeypatch, lines: list[tuple[str, str]], captured: list | None = None):
    async def stream(cmd, *, cwd=None):
        if captured is not None:
            captured.append(list(cmd))
        for item in lines:
            yield item

    monkeypatch.setattr(grok_mod, "stream_process_lines", stream)


def _frames(*events: dict) -> list[tuple[str, str]]:
    return [("stdout", json.dumps(e)) for e in events] + [("exit", "0")]


# ---- request assembly ----------------------------------------------------------


@pytest.mark.asyncio
async def test_build_command_flags_and_equals_form_prompt() -> None:
    config = BackendConfig(
        model="grok-4",
        effort="high",
        system_prompt="delegate rules",
        extra_args=["--flag"],
    )
    cmd = GrokBackend()._build_command("What is 2+2?", session_id="g-sess", config=config)
    assert cmd[:6] == [
        "grok",
        "--output-format",
        "streaming-json",
        "--permission-mode",
        "bypassPermissions",
        "--no-memory",
    ]
    assert "--verbatim" in cmd
    assert cmd[cmd.index("--model") + 1] == "grok-4"
    assert cmd[cmd.index("--reasoning-effort") + 1] == "high"
    assert cmd[cmd.index("--rules") + 1] == "delegate rules"
    assert cmd[cmd.index("--resume") + 1] == "g-sess"
    assert cmd[-2:] == ["--flag", "--single=What is 2+2?"]


@pytest.mark.asyncio
async def test_build_command_omits_optionals_without_resume(monkeypatch) -> None:
    config = BackendConfig(model="", effort="", system_prompt="", permission_mode="")
    cmd = GrokBackend()._build_command("-starts-with-dash", session_id=None, config=config)
    assert "--resume" not in cmd
    assert "--model" not in cmd
    assert "--reasoning-effort" not in cmd
    assert "--rules" not in cmd
    # the equals form keeps a leading-dash prompt a value, not a flag
    assert cmd[-1] == "--single=-starts-with-dash"
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"


# ---- streaming event mapping ---------------------------------------------------


@pytest.mark.asyncio
async def test_consult_accumulates_text_deltas_with_usage_block_boundary(monkeypatch) -> None:
    _patch_stream(
        monkeypatch,
        _frames(
            {"type": "text", "data": "Hello"},
            {"type": "usage"},
            {"type": "text", "data": " world"},
            {"type": "end", "sessionId": "g-42", "stopReason": "end_turn"},
        ),
    )
    events, on_event = _collector()
    result = await GrokBackend().consult("q", on_event=on_event)

    assert result.success
    assert result.final_text == " world"  # usage starts a fresh merge block
    assert result.session_id == "g-42"
    assert [e.kind for e in events] == [EVENT_TEXT, EVENT_TEXT]
    assert [e.meta["merge_id"] for e in events] == ["grok-text-1", "grok-text-2"]
    assert events[0].text == "Hello" and events[1].text == " world"


@pytest.mark.asyncio
async def test_consult_tool_preamble_resets_answer_and_merges_sparse_updates(monkeypatch) -> None:
    _patch_stream(
        monkeypatch,
        _frames(
            {"type": "text", "data": "let me check"},
            {"type": "tool_call", "toolCallId": "t1", "toolName": "Shell", "rawInput": "ls"},
            {"type": "text", "data": "the dir has 3 files. "},
            {"type": "text", "data": "done."},
            {
                "type": "tool_call_update",
                "toolCallId": "t1",
                "status": "completed",
                "rawOutput": "a b",
            },
            {"type": "end", "sessionId": "g-42", "stopReason": "end_turn"},
        ),
    )
    events, on_event = _collector()
    result = await GrokBackend().consult("q", on_event=on_event)

    assert result.success and result.final_text == "the dir has 3 files. done."
    tool_start = events[1]
    assert tool_start.kind == EVENT_TOOL
    assert tool_start.text.startswith("Shell")
    assert tool_start.meta["merge_id"] == "grok-tool-t1"
    tool_done = events[4]
    assert tool_done.kind == EVENT_TOOL_RESULT
    # the update keeps the start frame's name and reports status + compacted IO
    assert tool_done.text == 'Shell · completed · "ls" · "a b"'
    assert tool_done.meta["merge_id"] == "grok-tool-t1"
    # the preamble text is not the answer; deltas after the tool form the reply
    assert events[0].text == "let me check"


@pytest.mark.asyncio
async def test_consult_private_and_protocol_events_stay_silent(monkeypatch) -> None:
    _patch_stream(
        monkeypatch,
        _frames(
            {"type": "thought", "data": "secret reasoning"},
            {"type": "available_commands", "commands": []},
            {"type": "usage"},
            {"type": "mystery_frame", "payload": {"opaque": "signature"}},
            {"type": "end", "stopReason": "end_turn"},
            {"type": "text", "data": "answer"},
        ),
    )
    events, on_event = _collector()
    result = await GrokBackend().consult("q", on_event=on_event)

    assert result.success and result.final_text == "answer"
    assert [e.kind for e in events] == [EVENT_LOG, EVENT_TEXT]
    assert events[0].text == "Grok CLI: mystery_frame"  # type visible, payload withheld


# ---- failure and interruption branches -----------------------------------------


@pytest.mark.asyncio
async def test_consult_malformed_frames_fail_the_consult(monkeypatch) -> None:
    # a non-JSON line is a malformed frame
    events, on_event = _collector()
    _patch_stream(monkeypatch, [("stdout", "{truncated json"), ("exit", "0")])
    result = await GrokBackend().consult("q", on_event=on_event)
    assert not result.success
    assert result.error == "Grok CLI emitted invalid streaming JSON."
    assert [e.kind for e in events] == [EVENT_ERROR]
    # the frame itself is never echoed back
    assert all("truncated" not in e.text for e in events)

    # a JSON value that is not an object is an invalid event
    events2, on_event2 = _collector()
    _patch_stream(monkeypatch, [("stdout", '["a list"]'), ("exit", "0")])
    result2 = await GrokBackend().consult("q", on_event=on_event2)
    assert not result2.success
    assert result2.error == "Grok CLI emitted an invalid streaming event."
    assert [e.kind for e in events2] == [EVENT_ERROR]


@pytest.mark.asyncio
async def test_consult_end_stops_and_empty_completion_branches(monkeypatch) -> None:
    # stopReason other than end_turn is a failure even with an end frame
    events, on_event = _collector()
    _patch_stream(
        monkeypatch,
        _frames(
            {"type": "text", "data": "partial"},
            {"type": "end", "sessionId": "g-7", "stopReason": "max_tokens"},
        ),
    )
    result = await GrokBackend().consult("q", on_event=on_event)
    assert not result.success
    assert "max_tokens" in result.error

    # stream without any end frame → missing-completion failure
    events2, on_event2 = _collector()

    async def stream_no_end(cmd, *, cwd=None):
        yield ("stdout", json.dumps({"type": "text", "data": "dangling"}))
        yield ("exit", "0")

    monkeypatch.setattr(grok_mod, "stream_process_lines", stream_no_end)
    result2 = await GrokBackend().consult("q", on_event=on_event2)
    assert not result2.success
    assert result2.error == "Grok CLI stream ended without a completion event."

    # end_turn but empty answer → completed-without-answer failure
    events3, on_event3 = _collector()
    _patch_stream(monkeypatch, _frames({"type": "end", "stopReason": "end_turn"}))
    result3 = await GrokBackend().consult("q", on_event=on_event3)
    assert not result3.success
    assert result3.error == "Grok CLI completed without an answer."


@pytest.mark.asyncio
async def test_consult_rejects_images_without_spawning(monkeypatch) -> None:
    async def stream_should_not_run(cmd, *, cwd=None):
        raise AssertionError("stream must not be invoked for image consults")
        yield  # pragma: no cover

    monkeypatch.setattr(grok_mod, "stream_process_lines", stream_should_not_run)
    events, on_event = _collector()
    result = await GrokBackend().consult("q", on_event=on_event, images=["/tmp/pic.png"])

    assert not result.success
    assert result.error == "Grok CLI image forwarding is not supported by this connector."
    assert [e.kind for e in events] == [EVENT_ERROR]


@pytest.mark.asyncio
async def test_consult_nonzero_exit_and_cli_error_frame_fail(monkeypatch) -> None:
    events, on_event = _collector()
    _patch_stream(monkeypatch, [("exit", "2")])
    result = await GrokBackend().consult("q", on_event=on_event)
    assert not result.success
    assert result.error == "grok exited with code 2"

    events2, on_event2 = _collector()
    _patch_stream(
        monkeypatch,
        _frames({"type": "error", "message": "quota exhausted"}) + [("exit", "0")],
    )
    result2 = await GrokBackend().consult("q", on_event=on_event2)
    assert not result2.success
    assert result2.error == "quota exhausted"
    assert events2[0].kind == EVENT_ERROR
