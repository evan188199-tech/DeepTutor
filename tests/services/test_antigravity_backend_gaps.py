"""Supplementary coverage for the Antigravity CLI backend (weak-top100 #74).

Complements ``tests/services/test_antigravity_backend.py`` with the branches it
does not reach: ``detect``, a failing stream, stderr and non-dict-JSON noise,
field clipping, tool completion, and exit-code interaction with an already
delivered answer. The subprocess is always canned — no real ``agy`` runs.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from deeptutor.services.subagent.antigravity import AntigravityBackend
from deeptutor.services.subagent.config import BackendConfig
from deeptutor.services.subagent.types import (
    EVENT_ERROR,
    EVENT_LOG,
    EVENT_TOOL,
    EVENT_TOOL_RESULT,
)

MODULE = "deeptutor.services.subagent.antigravity"


def _canned_stream(records: list[dict[str, Any]], *lines: tuple[str, str], exit_code: str = "0"):
    """Replay canned (channel, text) lines in stream_process_lines' shape."""

    async def _fake(cmd, cwd=None, **kwargs):  # noqa: ARG001
        records.append({"cmd": list(cmd), "cwd": cwd})
        for channel, text in lines:
            yield channel, text
        yield "exit", exit_code

    return _fake


async def _consult(
    monkeypatch: pytest.MonkeyPatch,
    *lines: tuple[str, str],
    exit_code: str = "0",
    backend: AntigravityBackend | None = None,
    **consult_kwargs: Any,
):
    records: list[dict[str, Any]] = []
    monkeypatch.setattr(
        f"{MODULE}.stream_process_lines",
        _canned_stream(records, *lines, exit_code=exit_code),
    )
    seen: list[Any] = []

    async def on_event(event):
        seen.append(event)

    result = await (backend or AntigravityBackend()).consult(
        "q", on_event=on_event, **consult_kwargs
    )
    return result, seen, records


def _stdout_event(event: dict[str, Any]) -> tuple[str, str]:
    return "stdout", json.dumps(event)


# ---- detect ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_reports_the_probed_version(monkeypatch) -> None:
    async def _probe(cmd, **kwargs):  # noqa: ARG001
        assert cmd == ["agy", "--version"]
        return True, "agy 1.2.3"

    monkeypatch.setattr(f"{MODULE}.probe_version", _probe)

    detected = await AntigravityBackend().detect()

    assert detected.available is True
    assert detected.version == "agy 1.2.3"
    assert detected.detail == ""


@pytest.mark.asyncio
async def test_detect_points_at_the_install_guide_when_the_cli_is_missing(monkeypatch) -> None:
    async def _probe(cmd, **kwargs):  # noqa: ARG001
        return False, "not installed"

    monkeypatch.setattr(f"{MODULE}.probe_version", _probe)

    detected = await AntigravityBackend().detect()

    assert detected.available is False
    assert detected.version == ""
    assert "not found on PATH" in detected.detail
    assert "https://antigravity.google/docs/cli" in detected.detail


# ---- stream failure and exit-code interaction --------------------------------


@pytest.mark.asyncio
async def test_a_failing_stream_becomes_a_consult_error_not_a_crash(monkeypatch) -> None:
    async def _broken(cmd, cwd=None, **kwargs):  # noqa: ARG001
        raise RuntimeError("spawn blew up")
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(f"{MODULE}.stream_process_lines", _broken)
    seen: list[Any] = []

    async def on_event(event):
        seen.append(event)

    result = await AntigravityBackend().consult("q", on_event=on_event)

    assert result.success is False
    assert "spawn blew up" in result.error
    assert any(e.kind == EVENT_ERROR for e in seen)


@pytest.mark.asyncio
async def test_nonzero_exit_after_a_delivered_answer_keeps_the_consult_successful(
    monkeypatch,
) -> None:
    """The CLI already handed back its answer; a trailing exit code cannot void it."""
    result, seen, _ = await _consult(
        monkeypatch,
        _stdout_event({"event": "result", "result": {"status": "SUCCESS", "response": "done"}}),
        exit_code="1",
    )

    assert result.success is True
    assert result.final_text == "done"
    assert not any(e.kind == EVENT_ERROR for e in seen)


# ---- stdout/stderr noise -----------------------------------------------------


@pytest.mark.asyncio
async def test_stderr_lines_are_logged_and_blank_ones_are_dropped(monkeypatch) -> None:
    result, seen, _ = await _consult(
        monkeypatch,
        ("stderr", "agy: warming up"),
        ("stderr", "   "),
        _stdout_event({"event": "result", "result": {"status": "SUCCESS", "response": "ok"}}),
    )

    logs = [e for e in seen if e.kind == EVENT_LOG]
    assert [e.text for e in logs] == ["agy: warming up"]
    assert logs[0].raw == {"stream": "stderr"}
    assert result.success is True


@pytest.mark.asyncio
async def test_non_dict_json_stdout_is_logged_not_parsed(monkeypatch) -> None:
    """JSON scalars/arrays are not events; they read as incidental CLI output."""
    result, seen, _ = await _consult(
        monkeypatch,
        ("stdout", "[1, 2]"),
        ("stdout", '"just a string"'),
        ("stdout", "null"),
        _stdout_event({"event": "result", "result": {"status": "SUCCESS", "response": "ok"}}),
    )

    assert [e.text for e in seen if e.kind == EVENT_LOG] == ["[1, 2]", '"just a string"', "null"]
    assert result.final_text == "ok"
    assert result.success is True


@pytest.mark.asyncio
async def test_plain_stdout_noise_alone_still_counts_as_silence(monkeypatch) -> None:
    """Unparseable lines do not satisfy the antigravity-cli#76 empty-stream guard."""
    result, seen, _ = await _consult(
        monkeypatch,
        ("stdout", "warning: something plain"),
    )

    assert result.success is False
    assert "#76" in result.error
    assert any(e.kind == EVENT_ERROR for e in seen)


# ---- events: session bookkeeping ---------------------------------------------


@pytest.mark.asyncio
async def test_conversation_id_is_taken_from_the_event_body_when_top_level_is_absent(
    monkeypatch,
) -> None:
    result, _, _ = await _consult(
        monkeypatch,
        _stdout_event({"event": "init", "init": {"conversation_id": "body-conv"}}),
        _stdout_event(
            {"event": "step_update", "step_update": {"step_index": 0, "text_delta": "hi"}}
        ),
    )

    assert result.session_id == "body-conv"


@pytest.mark.asyncio
async def test_an_unknown_named_event_only_updates_the_session(monkeypatch) -> None:
    """Forward compatibility: an unseen event name must not crash or emit noise."""
    result, seen, _ = await _consult(
        monkeypatch,
        _stdout_event({"event": "mystery", "conversation_id": "c9"}),
    )

    assert result.session_id == "c9"
    assert seen == []
    assert result.event_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "expected"),
    [("", "Session started"), ("gemini-3-pro", "Session started · gemini-3-pro")],
)
async def test_init_log_announces_the_active_model(monkeypatch, model: str, expected: str) -> None:
    _, seen, _ = await _consult(
        monkeypatch,
        _stdout_event({"event": "init", "conversation_id": "c1", "init": {"model": model}}),
    )

    assert [e.text for e in seen if e.kind == EVENT_LOG] == [expected]


# ---- events: result interaction ----------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_result_keeps_its_partial_answer_text(monkeypatch) -> None:
    result, _, _ = await _consult(
        monkeypatch,
        _stdout_event(
            {
                "event": "result",
                "result": {"status": "ERROR", "response": "partial", "error": "boom"},
            }
        ),
    )

    assert result.success is False
    assert result.error == "boom"
    assert result.final_text == "partial"


@pytest.mark.asyncio
async def test_a_success_result_without_a_response_falls_back_to_the_deltas(monkeypatch) -> None:
    result, _, _ = await _consult(
        monkeypatch,
        _stdout_event(
            {"event": "step_update", "step_update": {"step_index": 0, "text_delta": "chunk"}}
        ),
        _stdout_event({"event": "result", "result": {"status": "SUCCESS", "response": ""}}),
    )

    assert result.success is True
    assert result.final_text == "chunk"


# ---- events: tool steps ------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["DONE", "done"])
async def test_a_completed_tool_step_emits_its_result(monkeypatch, state: str) -> None:
    _, seen, _ = await _consult(
        monkeypatch,
        _stdout_event(
            {
                "event": "step_update",
                "step_update": {
                    "step_index": 1,
                    "state": state,
                    "tool_name": "Shell",
                    "tool_info": {"result": "file list"},
                },
            }
        ),
    )

    tool_results = [e for e in seen if e.kind == EVENT_TOOL_RESULT]
    assert len(tool_results) == 1
    assert tool_results[0].text == "file list"
    assert tool_results[0].meta == {"tool": "Shell"}


@pytest.mark.asyncio
async def test_a_completed_tool_step_prefers_output_and_clips_long_results(monkeypatch) -> None:
    _, seen, _ = await _consult(
        monkeypatch,
        _stdout_event(
            {
                "event": "step_update",
                "step_update": {
                    "step_index": 1,
                    "state": "DONE",
                    "tool_name": "Shell",
                    "tool_info": {"output": "x" * 4500},
                },
            }
        ),
    )

    tool_results = [e for e in seen if e.kind == EVENT_TOOL_RESULT]
    assert len(tool_results[0].text) == 4001
    assert tool_results[0].text.endswith("…")


@pytest.mark.asyncio
async def test_a_completed_tool_step_without_info_yields_an_empty_result(monkeypatch) -> None:
    _, seen, _ = await _consult(
        monkeypatch,
        _stdout_event(
            {
                "event": "step_update",
                "step_update": {"step_index": 1, "state": "DONE", "tool_name": "Read"},
            }
        ),
    )

    tool_results = [e for e in seen if e.kind == EVENT_TOOL_RESULT]
    assert tool_results[0].text == ""


# ---- tool headers ------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool_info", "expected"),
    [
        ("raw string info", "Shell"),
        ({"args": {"command": "ls -la", "pattern": "p"}}, "Shell(ls -la)"),
        ({"command": "git status"}, "Shell(git status)"),
        ({"args": {"pattern": "p" * 200}}, "Shell(" + "p" * 160 + "…)"),
        ({"args": {"unrelated": "value"}}, "Shell"),
    ],
)
def test_tool_header_picks_the_salient_arg_and_clips_it(tool_info: Any, expected: str) -> None:
    from deeptutor.services.subagent.antigravity import _tool_header

    assert _tool_header("Shell", tool_info) == expected


# ---- command plumbing --------------------------------------------------------


def test_extra_args_are_appended_verbatim() -> None:
    cmd = AntigravityBackend()._build_command(
        "hi", session_id=None, config=BackendConfig(extra_args=["--flag", "value"])
    )

    assert cmd[-2:] == ["--flag", "value"]


def test_resume_still_lists_images_after_the_prompt() -> None:
    cmd = AntigravityBackend()._build_command(
        "again",
        session_id="c1",
        config=BackendConfig(system_prompt="be brief"),
        images=["/tmp/a.png", "/tmp/b.png"],
    )

    assert cmd[2] == "again\n\nAttached image files (read them from disk):\n/tmp/a.png\n/tmp/b.png"


@pytest.mark.asyncio
async def test_cwd_and_command_are_forwarded_to_the_stream(monkeypatch) -> None:
    result, _, records = await _consult(
        monkeypatch,
        _stdout_event({"event": "result", "result": {"status": "SUCCESS", "response": "ok"}}),
        cwd="/tmp/workdir",
    )

    assert result.success is True
    assert len(records) == 1
    assert records[0]["cwd"] == "/tmp/workdir"
    assert records[0]["cmd"][:2] == ["agy", "-p"]
    assert "--output-format" in records[0]["cmd"]


@pytest.mark.asyncio
async def test_partner_id_is_accepted_and_ignored(monkeypatch) -> None:
    result, _, _ = await _consult(
        monkeypatch,
        _stdout_event({"event": "result", "result": {"status": "SUCCESS", "response": "ok"}}),
        partner_id="partner-1",
    )

    assert result.success is True
    assert result.final_text == "ok"
