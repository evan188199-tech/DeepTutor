"""Antigravity CLI backend transport behavior, fully offline.

``stream_process_lines`` is monkeypatched with a scripted async generator, so
``consult`` is driven end-to-end over ``agy -p … --output-format stream-json``
frames (``event``-tagged with same-named bodies). Covers request assembly
(fresh vs resumed prompts, image listings, permission and effort mapping),
per-step text-delta accumulation, tool steps, result events, conversation-id
capture, and the failure branches (failed statuses, empty stream hint, non-zero
exit, stderr/malformed lines).
"""

from __future__ import annotations

import json

import pytest

from deeptutor.services.subagent import antigravity as agy_mod
from deeptutor.services.subagent.antigravity import AntigravityBackend
from deeptutor.services.subagent.config import BackendConfig
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

    monkeypatch.setattr(agy_mod, "stream_process_lines", stream)


def _frames(*events: dict) -> list[tuple[str, str]]:
    return [("stdout", json.dumps(e)) for e in events] + [("exit", "0")]


def _init(conv="conv-1", model="gemini-3-pro") -> dict:
    return {
        "event": "init",
        "conversation_id": conv,
        "init": {"model": model, "permission_mode": "default", "tools": ["Shell"]},
    }


# ---- request assembly ----------------------------------------------------------


@pytest.mark.asyncio
async def test_build_command_maps_flags_prompt_and_images() -> None:
    config = BackendConfig(
        system_prompt="delegate",
        model="gemini-3-pro",
        effort="high",
        permission_mode="acceptEdits",
    )
    cmd = AntigravityBackend()._build_command(
        "Explain this", session_id=None, config=config, images=["/tmp/a.png", "/tmp/b.png"]
    )
    assert cmd[0] == "agy" and cmd[1] == "-p"
    # fresh session prepends the system prompt; images are named as paths
    prompt = cmd[2]
    assert prompt.startswith("delegate\n\nExplain this")
    assert "Attached image files (read them from disk):\n/tmp/a.png\n/tmp/b.png" in prompt
    assert "--dangerously-skip-permissions" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert cmd[cmd.index("--model") + 1] == "gemini-3-pro"
    assert cmd[cmd.index("--effort") + 1] == "high"
    assert "--conversation" not in cmd


@pytest.mark.asyncio
async def test_build_command_resume_drops_system_prompt_and_filters_effort() -> None:
    config = BackendConfig(system_prompt="delegate", effort="extreme", permission_mode="default")
    cmd = AntigravityBackend()._build_command("next", session_id="conv-9", config=config, images=[])
    joined = " ".join(cmd)
    assert "delegate" not in joined  # resumed conversation already carries the instruction
    assert "--effort" not in joined  # unknown effort values are dropped, not passed through
    assert "--dangerously-skip-permissions" not in joined  # cautious modes keep the soft-deny
    assert cmd[cmd.index("--conversation") + 1] == "conv-9"
    assert "Attached image files" not in joined


# ---- streaming event mapping ---------------------------------------------------


@pytest.mark.asyncio
async def test_consult_accumulates_text_per_step_and_closes_block_on_tool(monkeypatch) -> None:
    _patch_stream(
        monkeypatch,
        _frames(
            _init(),
            {
                "event": "step_update",
                "conversation_id": "conv-1",
                "step_update": {"step_index": 0, "text_delta": "Hello"},
            },
            {
                "event": "step_update",
                "conversation_id": "conv-1",
                "step_update": {"step_index": 0, "text_delta": " there"},
            },
            {
                "event": "step_update",
                "conversation_id": "conv-1",
                "step_update": {
                    "step_index": 1,
                    "state": "RUNNING",
                    "tool_name": "Shell",
                    "tool_info": {"args": {"command": "ls -la"}},
                },
            },
            {
                "event": "step_update",
                "conversation_id": "conv-1",
                "step_update": {"step_index": 2, "text_delta": "The listing shows 3 files."},
            },
        ),
    )
    events, on_event = _collector()
    result = await AntigravityBackend().consult("q", on_event=on_event)

    assert result.success
    assert result.session_id == "conv-1"
    # no aggregate response in result → joined per-step blocks
    assert result.final_text == "Hello there\n\nThe listing shows 3 files."
    texts = [e for e in events if e.kind == EVENT_TEXT]
    assert [e.text for e in texts] == ["Hello", " there", "The listing shows 3 files."]
    assert all(e.meta["partial"] is True for e in texts)
    assert [e.meta["step"] for e in texts] == [0, 0, 2]
    tool = events[3]
    assert tool.kind == EVENT_TOOL
    assert tool.text == "Shell(ls -la)"
    assert tool.meta["tool"] == "Shell"


@pytest.mark.asyncio
async def test_consult_result_event_sets_final_text_and_failed_status_errors(monkeypatch) -> None:
    _patch_stream(
        monkeypatch,
        _frames(
            _init(),
            {"event": "step_update", "step_update": {"step_index": 0, "text_delta": "draft"}},
            {
                "event": "result",
                "result": {"status": "OK", "response": "final verdict", "num_turns": 3},
            },
        ),
    )
    events, on_event = _collector()
    result = await AntigravityBackend().consult("q", on_event=on_event)

    assert result.success
    assert result.final_text == "final verdict"  # the aggregate beats accumulated blocks

    events2, on_event2 = _collector()
    _patch_stream(
        monkeypatch,
        _frames({"event": "result", "result": {"status": "ERROR", "error": "quota blown"}}),
    )
    result2 = await AntigravityBackend().consult("q", on_event=on_event2)
    assert not result2.success
    assert result2.error == "quota blown"
    assert [e.kind for e in events2] == [EVENT_ERROR]

    # a failed status without a message still names the status
    events3, on_event3 = _collector()
    _patch_stream(monkeypatch, _frames({"event": "result", "result": {"status": "interrupted"}}))
    result3 = await AntigravityBackend().consult("q", on_event=on_event3)
    assert not result3.success
    assert result3.error == "agy reported status INTERRUPTED"


@pytest.mark.asyncio
async def test_consult_init_logs_session_and_done_tool_step_reports_result(monkeypatch) -> None:
    _patch_stream(
        monkeypatch,
        _frames(
            _init(conv="conv-77", model="gemini-3-flash"),
            {
                "event": "step_update",
                "step_update": {
                    "step_index": 1,
                    "state": "DONE",
                    "tool_name": "Read",
                    "tool_info": {"output": "file body"},
                },
            },
            {"event": "result", "result": {"status": "OK", "response": "done answer"}},
        ),
    )
    events, on_event = _collector()
    result = await AntigravityBackend().consult("q", on_event=on_event)

    assert result.success and result.final_text == "done answer"
    assert result.session_id == "conv-77"
    assert events[0].kind == EVENT_LOG and events[0].text == "Session started · gemini-3-flash"
    tool_result = events[1]
    assert tool_result.kind == EVENT_TOOL_RESULT
    assert tool_result.text == "file body"
    assert tool_result.meta["tool"] == "Read"


# ---- failure and interruption branches -----------------------------------------


@pytest.mark.asyncio
async def test_consult_empty_stream_reports_the_known_tty_cause(monkeypatch) -> None:
    _patch_stream(monkeypatch, [("exit", "0")])
    events, on_event = _collector()
    result = await AntigravityBackend().consult("q", on_event=on_event)

    assert not result.success
    assert "antigravity-cli#76" in result.error
    assert [e.kind for e in events] == [EVENT_ERROR]


@pytest.mark.asyncio
async def test_consult_nonzero_exit_stderr_and_malformed_lines(monkeypatch) -> None:
    events, on_event = _collector()
    _patch_stream(monkeypatch, [("stderr", "agy: boom"), ("exit", "3")])
    result = await AntigravityBackend().consult("q", on_event=on_event)
    assert not result.success
    assert result.error == "agy exited with code 3"
    assert [e.kind for e in events] == [EVENT_LOG, EVENT_ERROR]
    assert events[0].raw == {"stream": "stderr"}

    # a non-zero exit after content keeps the success (the answer landed)
    events2, on_event2 = _collector()
    _patch_stream(
        monkeypatch,
        _frames({"event": "result", "result": {"status": "OK", "response": "kept"}})
        + [("exit", "1")],
    )
    result2 = await AntigravityBackend().consult("q", on_event=on_event2)
    assert result2.success and result2.final_text == "kept"

    # malformed stdout degrades to a log line, not a crash
    events3, on_event3 = _collector()
    _patch_stream(
        monkeypatch,
        [("stdout", "not json"), ("stdout", "[1, 2]")]
        + _frames({"event": "result", "result": {"status": "OK", "response": "ok"}}),
    )
    result3 = await AntigravityBackend().consult("q", on_event=on_event3)
    assert result3.success and result3.final_text == "ok"
    logs = [e for e in events3 if e.kind == EVENT_LOG and e.raw.get("stream") == "stdout"]
    assert [e.text for e in logs] == ["not json", "[1, 2]"]
