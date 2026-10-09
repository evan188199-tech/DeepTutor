"""Kimi CLI backend transport behavior, fully offline.

``stream_process_lines`` is monkeypatched with a scripted async generator, so
``consult`` is driven end-to-end over ``("stdout" | "stderr" | "exit", line)``
tuples exactly as the real ``kimi --print --output-format stream-json`` child
would surface them. Covers request assembly, event mapping (assistant text /
think / tool calls, tool results, role-less service lines), and the failure
branches (non-zero exit codes incl. the retryable 75, stderr, malformed
stdout) plus the tool-header renderer's fallbacks.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.services.subagent import kimi as kimi_mod
from deeptutor.services.subagent.config import BackendConfig
from deeptutor.services.subagent.kimi import KimiBackend
from deeptutor.services.subagent.types import (
    EVENT_ERROR,
    EVENT_LOG,
    EVENT_REASONING,
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

    monkeypatch.setattr(kimi_mod, "stream_process_lines", stream)


def _jsonl(*events: dict) -> list[tuple[str, str]]:
    return [("stdout", json.dumps(e)) for e in events] + [("exit", "0")]


# ---- request assembly ----------------------------------------------------------


@pytest.mark.asyncio
async def test_build_command_orders_flags_and_prepends_system_prompt_on_fresh_session() -> None:
    config = BackendConfig(
        system_prompt=" You are a delegate. ",
        model="kimi-k2",
        thinking=True,
        auto_approve=True,
        extra_args=["--foo", "bar"],
    )
    backend = KimiBackend()
    cmd = backend._build_command(
        "What is 2+2?", session_id="sess-1", fresh_session=True, config=config
    )
    assert cmd[:6] == [
        "kimi",
        "--print",
        "--output-format",
        "stream-json",
        "--session",
        "sess-1",
    ]
    assert "--yolo" in cmd
    assert "--thinking" in cmd
    assert cmd[cmd.index("--model") + 1] == "kimi-k2"
    assert cmd[-4:] == ["--foo", "bar", "--prompt", "You are a delegate.\n\nWhat is 2+2?"]


@pytest.mark.asyncio
async def test_build_command_resumed_session_keeps_prompt_and_respects_flags() -> None:
    backend = KimiBackend()
    resumed = backend._build_command(
        "Follow-up",
        session_id="sess-9",
        fresh_session=False,
        config=BackendConfig(system_prompt="delegate", thinking=False, auto_approve=False),
    )
    assert "--session" in resumed and resumed[resumed.index("--session") + 1] == "sess-9"
    assert "--prompt" in resumed and resumed[-1] == "Follow-up"
    assert "--no-thinking" in resumed
    assert "--yolo" not in resumed
    assert "delegate" not in resumed  # system prompt only on the session-creating consult


# ---- event mapping -------------------------------------------------------------


@pytest.mark.asyncio
async def test_consult_maps_assistant_text_think_and_tool_calls(monkeypatch) -> None:
    _patch_stream(
        monkeypatch,
        _jsonl(
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Reading the module."},
                    {"type": "think", "think": "plan the read"},
                ],
                "tool_calls": [
                    {
                        "function": {
                            "name": "Bash",
                            "arguments": json.dumps({"command": "ls -la\nsrc"}),
                        }
                    }
                ],
            },
            {"role": "assistant", "content": "final answer as a plain string"},
        ),
    )
    events, on_event = _collector()
    result = await KimiBackend().consult("q", on_event=on_event)

    assert result.success and result.final_text == "final answer as a plain string"
    kinds = [e.kind for e in events]
    assert kinds == [EVENT_TEXT, EVENT_REASONING, EVENT_TOOL, EVENT_TEXT]
    tool_event = events[2]
    assert tool_event.text == "Bash(ls -la src)"
    assert tool_event.raw["function"]["name"] == "Bash"
    assert result.event_count == 4


@pytest.mark.asyncio
async def test_consult_tool_role_yields_truncated_result_and_service_lines_log(monkeypatch) -> None:
    long_output = "x" * 5000
    _patch_stream(
        monkeypatch,
        _jsonl(
            {"role": "tool", "content": [{"type": "text", "text": long_output}]},
            {"category": "notify", "title": "Indexing", "body": "halfway"},
            {"file_path": "plan.md", "content": "1. read"},
            {"role": "user", "content": "echoed prompt"},
        ),
    )
    events, on_event = _collector()
    result = await KimiBackend().consult("q", on_event=on_event)

    assert result.success and result.final_text == ""
    tool_result = events[0]
    assert tool_result.kind == EVENT_TOOL_RESULT
    assert len(tool_result.text) == 4000 + 2 and tool_result.text.endswith("…")
    assert events[1].kind == EVENT_LOG and events[1].text == "Indexing · halfway"
    assert events[2].kind == EVENT_LOG and events[2].text == "plan · plan.md"
    # the echoed user/system message is deliberately silent
    assert len(events) == 3


# ---- failure and interruption branches -----------------------------------------


@pytest.mark.asyncio
async def test_consult_retryable_exit_75_marks_transient_error(monkeypatch) -> None:
    _patch_stream(
        monkeypatch,
        [("stderr", "provider 429"), ("exit", "75")],
    )
    events, on_event = _collector()
    result = await KimiBackend().consult("q", on_event=on_event)

    assert not result.success
    assert result.error == "kimi exited with code 75 (transient provider error)"
    assert [e.kind for e in events] == [EVENT_LOG, EVENT_ERROR]
    assert events[1].raw == {"returncode": "75"}


@pytest.mark.asyncio
async def test_consult_nonzero_exit_after_final_text_keeps_success(monkeypatch) -> None:
    _patch_stream(
        monkeypatch,
        _jsonl({"role": "assistant", "content": "the answer"}) + [("exit", "1")],
    )
    events, on_event = _collector()
    result = await KimiBackend().consult("q", on_event=on_event)

    assert result.success
    assert result.final_text == "the answer"
    assert not result.error
    assert [e.kind for e in events] == [EVENT_TEXT]


@pytest.mark.asyncio
async def test_consult_stderr_and_malformed_stdout_become_logs(monkeypatch) -> None:
    _patch_stream(
        monkeypatch,
        [("stdout", "not json at all"), ("stdout", "   "), ("stderr", "  "), ("exit", "0")],
    )
    events, on_event = _collector()
    result = await KimiBackend().consult("q", on_event=on_event)

    assert result.success and result.event_count == 1
    assert events[0].kind == EVENT_LOG
    assert events[0].text == "not json at all"
    assert events[0].raw == {"stream": "stdout"}


# ---- renderer helpers ----------------------------------------------------------


def test_render_tool_call_fallbacks() -> None:
    # malformed JSON arguments degrade to the bare tool name
    assert (
        kimi_mod._render_tool_call({"function": {"name": "Edit", "arguments": "{oops"}}) == "Edit"
    )
    # no usable function dict → bare "tool"
    assert kimi_mod._render_tool_call({"function": "nope"}) == "tool"
    # empty args → name only
    assert kimi_mod._render_tool_call({"function": {"name": "Grep", "arguments": {}}}) == "Grep"
    # non-primary keys fall back to a compacted JSON body
    rendered = kimi_mod._render_tool_call(
        {"function": {"name": "Note", "arguments": {"other": "v"}}}
    )
    assert rendered == 'Note({"other": "v"})'
    # primary-arg values are inlined past newlines and clipped at 160 chars
    long = "y" * 300
    rendered = kimi_mod._render_tool_call(
        {"function": {"name": "Run", "arguments": {"query": long}}}
    )
    assert rendered == "Run(" + "y" * 160 + " …)"


def test_parse_json_rejects_non_objects_and_garbage() -> None:
    assert kimi_mod._parse_json('{"role": "assistant"}') == {"role": "assistant"}
    assert kimi_mod._parse_json("[1, 2]") is None  # arrays are not events
    assert kimi_mod._parse_json("{broken") is None
    assert kimi_mod._parse_json("   ") is None
