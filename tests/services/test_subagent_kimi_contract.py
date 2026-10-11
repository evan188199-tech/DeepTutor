"""Focused contract tests for the Kimi CLI backend.

Covers the driver contract (``detect`` / command building), the JSONL stream
parsing fed by the subprocess primitive, and the failure / degradation
branches. Every subprocess interaction is mocked — no real ``kimi`` CLI is
spawned and nothing touches the network.
"""

from __future__ import annotations

import json
import uuid

import pytest

from deeptutor.services.subagent import kimi as kimi_mod
from deeptutor.services.subagent.config import BackendConfig
from deeptutor.services.subagent.kimi import (
    KimiBackend,
    _content_parts,
    _parse_json,
    _render_tool_call,
)
from deeptutor.services.subagent.types import ConsultResult

# ---- helpers -----------------------------------------------------------------


async def _handle(backend: KimiBackend, events: list[dict]) -> tuple[ConsultResult, list[tuple]]:
    result = ConsultResult()
    emitted: list[tuple[str, str]] = []

    async def emit(kind, text, raw, meta=None):
        emitted.append((kind, text))

    for event in events:
        await backend._handle_event(event, result, emit)
    return result, emitted


def _mock_stream(monkeypatch, lines, *, capture: dict | None = None) -> None:
    async def fake_stream(cmd, *, cwd=None):
        if capture is not None:
            capture["cmd"] = list(cmd)
        for channel, line in lines:
            yield channel, line

    monkeypatch.setattr(kimi_mod, "stream_process_lines", fake_stream)


def _collector():
    events: list = []

    async def on_event(event):
        events.append(event)

    return events, on_event


# ---- detect: driver contract --------------------------------------------------


@pytest.mark.asyncio
async def test_kimi_detect_available_reports_version(monkeypatch) -> None:
    seen: dict = {}

    async def fake_probe(cmd):
        seen["cmd"] = list(cmd)
        return True, "kimi-cli 0.9.1"

    monkeypatch.setattr(kimi_mod, "probe_version", fake_probe)
    detect = await KimiBackend().detect()
    assert seen["cmd"] == ["kimi", "--version"]
    assert detect.kind == "kimi"
    assert detect.display_name == "Kimi CLI"
    assert detect.available is True
    assert detect.version == "kimi-cli 0.9.1"
    assert detect.detail == ""


@pytest.mark.asyncio
async def test_kimi_detect_not_installed_keeps_probe_text(monkeypatch) -> None:
    async def fake_probe(cmd):
        return False, "not installed"

    monkeypatch.setattr(kimi_mod, "probe_version", fake_probe)
    detect = await KimiBackend().detect()
    assert detect.available is False
    assert detect.version == ""
    assert detect.detail == "not installed"  # probe text is surfaced verbatim


@pytest.mark.asyncio
async def test_kimi_detect_empty_probe_text_falls_back_to_detail(monkeypatch) -> None:
    async def fake_probe(cmd):
        return False, ""

    monkeypatch.setattr(kimi_mod, "probe_version", fake_probe)
    detect = await KimiBackend().detect()
    assert detect.available is False
    assert detect.detail == "kimi CLI not found on PATH"


@pytest.mark.asyncio
async def test_kimi_detect_probe_error_surfaces_probe_text(monkeypatch) -> None:
    async def fake_probe(cmd):
        return False, "kimi: permission denied"

    monkeypatch.setattr(kimi_mod, "probe_version", fake_probe)
    detect = await KimiBackend().detect()
    assert detect.available is False
    assert detect.detail == "kimi: permission denied"


# ---- command building: driver contract ----------------------------------------


def test_kimi_build_command_extra_args_precede_prompt() -> None:
    backend = KimiBackend()
    cmd = backend._build_command(
        "hi",
        session_id="s1",
        fresh_session=True,
        config=BackendConfig(extra_args=["--config", "x"]),
    )
    # Defaults: auto_approve → --yolo; thinking on → --thinking.
    assert "--yolo" in cmd and "--thinking" in cmd
    # extra_args land after backend-owned flags but before the trailing prompt.
    assert cmd[cmd.index("--config") + 1] == "x"
    assert cmd[cmd.index("--config") :][:2] == ["--config", "x"]
    assert cmd[-2:] == ["--prompt", "hi"]  # no system prompt → bare question


def test_kimi_build_command_blank_system_prompt_is_not_prefixed() -> None:
    backend = KimiBackend()
    cmd = backend._build_command(
        "hi",
        session_id="s1",
        fresh_session=True,
        config=BackendConfig(system_prompt="   "),
    )
    assert cmd[-1] == "hi"  # whitespace-only instruction adds no prefix block
    assert "\n\n" not in cmd[-1]


# ---- consult: mocked subprocess stream parsing ---------------------------------


@pytest.mark.asyncio
async def test_kimi_consult_streams_jsonl_and_ignores_images(monkeypatch) -> None:
    capture: dict = {}
    assistant_intro = json.dumps({"role": "assistant", "content": "Working on it."})
    assistant_final = json.dumps(
        {
            "role": "assistant",
            "content": [{"type": "think", "think": "plan"}, {"type": "text", "text": "Answer."}],
        }
    )
    _mock_stream(
        monkeypatch,
        [
            ("stderr", "kimi: loading config"),
            ("stderr", ""),  # blank stderr is noise — dropped
            ("stdout", "plain stdout line"),
            ("stdout", assistant_intro),
            ("stdout", assistant_final),
            ("exit", "0"),
        ],
        capture=capture,
    )
    events, on_event = _collector()
    result = await KimiBackend().consult("q", on_event=on_event, images=["/tmp/pic.png"])

    assert capture["cmd"][:4] == ["kimi", "--print", "--output-format", "stream-json"]
    assert "--session" in capture["cmd"]
    assert result.success is True
    assert result.error == ""
    assert result.final_text == "Answer."  # latest assistant text wins
    uuid.UUID(result.session_id)  # a well-formed, pre-minted session id
    kinds = [e.kind for e in events]
    assert kinds == ["log", "log", "text", "reasoning", "text"]
    assert events[0].raw == {"stream": "stderr"}
    assert events[1].raw == {"stream": "stdout"}
    assert result.event_count == 5


@pytest.mark.asyncio
async def test_kimi_consult_blank_and_nonobject_json_lines_become_logs(monkeypatch) -> None:
    _mock_stream(
        monkeypatch,
        [
            ("stdout", ""),  # blank stdout — dropped, not logged
            ("stdout", "[1, 2, 3]"),  # valid JSON but not an object → log fallback
            ("exit", "0"),
        ],
    )
    events, on_event = _collector()
    result = await KimiBackend().consult("q", on_event=on_event)
    assert result.success is True
    assert [e.kind for e in events] == ["log"]
    assert "[1, 2, 3]" in events[0].text


# ---- consult: failure and degradation branches ---------------------------------


@pytest.mark.asyncio
async def test_kimi_consult_nonzero_exit_marks_failure(monkeypatch) -> None:
    _mock_stream(monkeypatch, [("exit", "1")])
    events, on_event = _collector()
    result = await KimiBackend().consult("q", on_event=on_event)
    assert result.success is False
    assert result.error == "kimi exited with code 1"
    assert [e.kind for e in events] == ["error"]
    assert events[0].raw == {"returncode": "1"}
    assert "(transient" not in events[0].text


@pytest.mark.asyncio
async def test_kimi_consult_retryable_exit_notes_transient(monkeypatch) -> None:
    _mock_stream(monkeypatch, [("exit", "75")])
    events, on_event = _collector()
    result = await KimiBackend().consult("q", on_event=on_event)
    assert result.success is False
    assert result.error == "kimi exited with code 75 (transient provider error)"
    assert events[0].text.endswith("(transient provider error)")


@pytest.mark.asyncio
async def test_kimi_consult_nonzero_exit_after_final_text_stays_success(monkeypatch) -> None:
    answer = json.dumps({"role": "assistant", "content": "Delivered."})
    _mock_stream(monkeypatch, [("stdout", answer), ("exit", "3")])
    events, on_event = _collector()
    result = await KimiBackend().consult("q", on_event=on_event)
    # The answer landed before the crash — never rewrite a delivered success.
    assert result.success is True
    assert result.error == ""
    assert result.final_text == "Delivered."
    assert [e.kind for e in events] == ["text"]


@pytest.mark.asyncio
async def test_kimi_consult_clean_exit_with_no_output_is_success(monkeypatch) -> None:
    _mock_stream(monkeypatch, [("exit", "0")])
    events, on_event = _collector()
    result = await KimiBackend().consult("q", on_event=on_event)
    assert result.success is True
    assert result.final_text == ""
    assert events == []


@pytest.mark.asyncio
async def test_kimi_consult_stream_exception_is_caught(monkeypatch) -> None:
    async def broken_stream(cmd, *, cwd=None):
        raise RuntimeError("spawn boom")
        yield ("stdout", "unreachable")  # pragma: no cover

    monkeypatch.setattr(kimi_mod, "stream_process_lines", broken_stream)
    events, on_event = _collector()
    result = await KimiBackend().consult("q", on_event=on_event)
    assert result.success is False
    assert result.error == "spawn boom"
    assert [e.kind for e in events] == ["error"]
    assert events[0].text == "spawn boom"


@pytest.mark.asyncio
async def test_kimi_consult_exception_after_final_text_keeps_answer(monkeypatch) -> None:
    answer = json.dumps({"role": "assistant", "content": "Partial answer."})

    async def broken_stream(cmd, *, cwd=None):
        yield ("stdout", answer)
        raise RuntimeError("stream died mid-run")

    monkeypatch.setattr(kimi_mod, "stream_process_lines", broken_stream)
    events, on_event = _collector()
    result = await KimiBackend().consult("q", on_event=on_event)
    assert result.success is False
    assert result.error == "stream died mid-run"
    assert result.final_text == "Partial answer."  # already-streamed answer survives
    assert [e.kind for e in events] == ["text", "error"]


# ---- output parsing helpers ----------------------------------------------------


def test_kimi_parse_json_shapes() -> None:
    assert _parse_json('  {"a": 1}  ') == {"a": 1}  # surrounding whitespace tolerated
    assert _parse_json("[1, 2]") is None  # arrays are not events
    assert _parse_json('"hi"') is None  # JSON scalars are not events
    assert _parse_json("42") is None
    assert _parse_json("null") is None
    assert _parse_json('{"a": 1 trailing') is None
    assert _parse_json("") is None


def test_kimi_content_parts_polymorphic() -> None:
    assert _content_parts("hello") == [{"type": "text", "text": "hello"}]
    assert _content_parts("") == []
    assert _content_parts([{"type": "text", "text": "a"}, "junk", 5]) == [
        {"type": "text", "text": "a"}
    ]
    assert _content_parts(None) == []
    assert _content_parts(3.14) == []


def test_kimi_render_tool_call_argument_variants() -> None:
    # Missing function dict → generic "tool" name.
    assert _render_tool_call({}) == "tool"
    # Empty arguments → bare name.
    assert _render_tool_call({"function": {"name": "ls", "arguments": {}}}) == "ls"
    # Arguments already a dict → primary key is inlined.
    assert (
        _render_tool_call({"function": {"name": "read", "arguments": {"file_path": "/a/b.py"}}})
        == "read(/a/b.py)"
    )
    # Arguments arrive JSON-encoded → decoded before rendering.
    assert (
        _render_tool_call({"function": {"name": "shell", "arguments": '{"command": "pwd"}'}})
        == "shell(pwd)"
    )
    # Broken JSON-encoded arguments are kept raw — and not dict-like, so the
    # renderer falls back to the bare tool name.
    assert (
        _render_tool_call({"function": {"name": "shell", "arguments": '{"command": "pwd"'}})
        == "shell"
    )
    # No primary key → the compact JSON dump is inlined.
    assert _render_tool_call({"function": {"name": "note", "arguments": {"foo": "bar"}}}) == (
        'note({"foo": "bar"})'
    )


def test_kimi_render_tool_call_primary_key_priority_and_truncation() -> None:
    # Priority follows the primary-args tuple: command beats prompt.
    call = {"function": {"name": "run", "arguments": {"prompt": "p", "command": "c"}}}
    assert _render_tool_call(call) == "run(c)"
    # Long values collapse to one line and truncate at 160 chars.
    long_value = "x" * 200
    rendered = _render_tool_call({"function": {"name": "grep", "arguments": {"query": long_value}}})
    assert rendered == f"grep({'x' * 160} …)"


# ---- event handling: assistant / tool / service lines --------------------------


@pytest.mark.asyncio
async def test_kimi_assistant_blank_parts_and_non_dict_tool_calls_emit_nothing() -> None:
    result, emitted = await _handle(
        KimiBackend(),
        [
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "   "}, {"type": "think", "think": ""}],
                "tool_calls": ["junk", {"type": "function", "function": {"name": "ls"}}],
            }
        ],
    )
    assert [k for k, _ in emitted] == ["tool"]
    assert emitted == [("tool", "ls")]


@pytest.mark.asyncio
async def test_kimi_tool_result_joins_parts_and_placeholders_empty() -> None:
    result, emitted = await _handle(
        KimiBackend(),
        [
            {"role": "tool", "content": [{"text": "row1"}, "junk", {"text": "row2"}]},
            {"role": "tool", "content": ""},
            {"role": "tool", "content": "   "},
        ],
    )
    assert [text for _, text in emitted] == ["row1\nrow2", "(empty result)", "(empty result)"]


@pytest.mark.asyncio
async def test_kimi_roleless_service_lines_map_to_logs() -> None:
    result, emitted = await _handle(
        KimiBackend(),
        [
            {"category": "task", "title": "background", "body": "done"},
            {"severity": "info"},  # no title/body → nothing to say
            {"file_path": "/tmp/plan.md", "content": "# plan"},
            {"foo": 1},  # bare dict → compact JSON log
        ],
    )
    assert [text for _, text in emitted] == [
        "background · done",
        "plan · /tmp/plan.md",
        '{"foo": 1}',
    ]
