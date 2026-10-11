"""OpenClaw backend transport behavior, fully offline.

``stream_process_lines`` is monkeypatched with a scripted async generator, so
``consult`` is driven end-to-end over ``("stdout" | "stderr" | "exit", line)``
tuples exactly as the real ``openclaw agent --json`` child would surface them
(stdout reserved for the one final Gateway JSON response, diagnostics on
stderr). Covers command assembly (explicit vs generated session keys, system
prompt only on fresh sessions, image path appendix, model/effort flags),
``detect`` probing, event mapping, and the failure branches (invalid JSON,
non-zero exits, explicit ``ok: false`` / failed statuses, empty replies, and a
raised process error) plus the response-parsing helpers.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.services.subagent import openclaw as openclaw_mod
from deeptutor.services.subagent.config import BackendConfig
from deeptutor.services.subagent.openclaw import OpenClawBackend
from deeptutor.services.subagent.types import (
    EVENT_ERROR,
    EVENT_LOG,
    EVENT_TEXT,
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

    monkeypatch.setattr(openclaw_mod, "stream_process_lines", stream)


def _gateway_json(payload: dict) -> list[tuple[str, str]]:
    return [("stdout", json.dumps(payload)), ("exit", "0")]


# ---- command assembly -----------------------------------------------------------


def test_build_command_resumed_session_keeps_key_and_omits_system_prompt() -> None:
    backend = OpenClawBackend()
    cmd = backend._build_command(
        "Follow-up question",
        session_id="deeptutor-resume",
        fresh_session=False,
        config=BackendConfig(system_prompt="Be concise", model="gpt-5", effort="high"),
    )
    assert cmd[:2] == ["openclaw", "agent"]
    assert cmd[cmd.index("--session-key") + 1] == "deeptutor-resume"
    assert cmd[cmd.index("--timeout") + 1] == "0"
    assert cmd[cmd.index("--model") + 1] == "gpt-5"
    assert cmd[cmd.index("--thinking") + 1] == "high"
    assert cmd[-2:] == ["--message", "Follow-up question"]
    assert "Be concise" not in cmd


def test_build_command_fresh_session_prepends_prompt_and_appends_images() -> None:
    backend = OpenClawBackend()
    cmd = backend._build_command(
        "inspect this",
        session_id="deeptutor-fresh",
        fresh_session=True,
        config=BackendConfig(system_prompt=" Delegate mode. ", extra_args=["--local"]),
        images=["/tmp/a.png", "/tmp/b.pdf"],
    )
    assert (
        cmd[-1]
        == "Delegate mode.\n\ninspect this\n\nAttached local files:\n- /tmp/a.png\n- /tmp/b.pdf"
    )
    assert "--local" in cmd
    # no model/effort configured → no such flags
    assert "--model" not in cmd
    assert "--thinking" not in cmd


# ---- detection ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_reports_version_when_probe_succeeds(monkeypatch) -> None:
    async def probe(cmd):
        assert cmd == ["openclaw", "--version"]
        return True, "OpenClaw 1.2.3"

    monkeypatch.setattr(openclaw_mod, "probe_version", probe)
    result = await OpenClawBackend().detect()
    assert result.available is True
    assert result.version == "OpenClaw 1.2.3"
    assert result.detail == ""


@pytest.mark.asyncio
async def test_detect_missing_cli_uses_fallback_detail(monkeypatch) -> None:
    async def probe(cmd):
        return False, "not installed"

    monkeypatch.setattr(openclaw_mod, "probe_version", probe)
    result = await OpenClawBackend().detect()
    assert result.available is False
    assert result.version == ""
    assert result.detail == "openclaw CLI not found on PATH"


@pytest.mark.asyncio
async def test_detect_surfaces_probe_output_as_detail(monkeypatch) -> None:
    async def probe(cmd):
        return False, "permission denied"

    monkeypatch.setattr(openclaw_mod, "probe_version", probe)
    result = await OpenClawBackend().detect()
    assert result.available is False
    assert result.detail == "permission denied"


# ---- consult success paths ------------------------------------------------------


@pytest.mark.asyncio
async def test_consult_threads_session_and_joins_nested_payload_texts(monkeypatch) -> None:
    captured: list[list[str]] = []
    _patch_stream(
        monkeypatch,
        [
            ("stderr", "Gateway connected"),
            ("stderr", "   "),  # blank stderr lines are silent
            (
                "stdout",
                json.dumps(
                    {
                        "status": "OK",
                        "result": {
                            "payloads": [
                                {"text": "First part."},
                                {"no_text": True},
                                {"text": "Second part."},
                            ]
                        },
                    }
                ),
            ),
            ("exit", "0"),
        ],
        captured,
    )
    events, on_event = _collector()
    result = await OpenClawBackend().consult("q", on_event=on_event, session_id="sess-7")

    assert result.success and result.session_id == "sess-7"
    assert result.final_text == "First part.\n\nSecond part."
    assert result.event_count == 2
    assert [e.kind for e in events] == [EVENT_LOG, EVENT_TEXT]
    assert events[0].raw == {"stream": "stderr"}
    assert events[1].raw == {
        "status": "OK",
        "result": {
            "payloads": [
                {"text": "First part."},
                {"no_text": True},
                {"text": "Second part."},
            ]
        },
    }
    assert captured[0][captured[0].index("--session-key") + 1] == "sess-7"


@pytest.mark.asyncio
async def test_consult_reads_top_level_fallback_keys_and_generated_session(monkeypatch) -> None:
    _patch_stream(monkeypatch, _gateway_json({"status": "success", "final": "  The answer.  "}))
    events, on_event = _collector()
    result = await OpenClawBackend().consult("q", on_event=on_event)

    assert result.success and result.final_text == "The answer."
    assert result.session_id is not None and result.session_id.startswith("deeptutor-")
    assert [e.kind for e in events] == [EVENT_TEXT]


@pytest.mark.asyncio
async def test_consult_non_dict_result_falls_back_to_top_level_keys(monkeypatch) -> None:
    _patch_stream(
        monkeypatch, _gateway_json({"result": "not a mapping", "output": "fallback text"})
    )
    events, on_event = _collector()
    result = await OpenClawBackend().consult("q", on_event=on_event)

    assert result.success and result.final_text == "fallback text"


# ---- consult failure branches ---------------------------------------------------


@pytest.mark.asyncio
async def test_consult_nonzero_exit_with_valid_payload_reports_error(monkeypatch) -> None:
    _patch_stream(
        monkeypatch,
        [("stdout", json.dumps({"result": {"payloads": [{"text": "partial"}]}})), ("exit", "1")],
    )
    events, on_event = _collector()
    result = await OpenClawBackend().consult("q", on_event=on_event)

    assert not result.success
    assert result.error == "openclaw exited with code 1"
    assert [e.kind for e in events] == [EVENT_ERROR]
    assert events[0].raw["result"]["payloads"] == [{"text": "partial"}]


@pytest.mark.asyncio
async def test_consult_explicit_ok_false_uses_payload_error_message(monkeypatch) -> None:
    _patch_stream(
        monkeypatch,
        _gateway_json({"ok": False, "error": {"message": "gateway unreachable", "code": 7}}),
    )
    events, on_event = _collector()
    result = await OpenClawBackend().consult("q", on_event=on_event)

    assert not result.success
    assert result.error == "gateway unreachable"
    assert [e.kind for e in events] == [EVENT_ERROR]
    assert events[0].raw["error"]["code"] == 7


@pytest.mark.asyncio
async def test_consult_failed_status_uses_summary_fallback(monkeypatch) -> None:
    _patch_stream(monkeypatch, _gateway_json({"status": "Failed", "summary": "boom"}))
    events, on_event = _collector()
    result = await OpenClawBackend().consult("q", on_event=on_event)

    assert not result.success
    assert result.error == "boom"


@pytest.mark.asyncio
async def test_consult_valid_json_but_empty_text_reports_no_reply(monkeypatch) -> None:
    _patch_stream(monkeypatch, _gateway_json({"status": "ok"}))
    events, on_event = _collector()
    result = await OpenClawBackend().consult("q", on_event=on_event)

    assert not result.success
    assert result.error == "openclaw returned no reply"
    assert [e.kind for e in events] == [EVENT_ERROR]


@pytest.mark.asyncio
async def test_consult_invalid_json_zero_exit_logs_stdout_and_reports_invalid_json(
    monkeypatch,
) -> None:
    _patch_stream(monkeypatch, [("stdout", "gateway said hi"), ("exit", "0")])
    events, on_event = _collector()
    result = await OpenClawBackend().consult("q", on_event=on_event)

    assert not result.success
    assert result.error == "openclaw did not return valid JSON"
    assert [e.kind for e in events] == [EVENT_LOG, EVENT_ERROR]
    assert events[0].text == "gateway said hi"
    assert events[0].raw == {"stream": "stdout"}
    assert events[1].raw == {"returncode": "0"}


@pytest.mark.asyncio
async def test_consult_invalid_json_nonzero_exit_reports_exit_code_only(monkeypatch) -> None:
    _patch_stream(monkeypatch, [("exit", "3")])
    events, on_event = _collector()
    result = await OpenClawBackend().consult("q", on_event=on_event)

    assert not result.success
    assert result.error == "openclaw exited with code 3"
    # empty stdout → no log event, just the error
    assert [e.kind for e in events] == [EVENT_ERROR]
    assert events[0].raw == {"returncode": "3"}


@pytest.mark.asyncio
async def test_consult_stream_exception_marks_error_result(monkeypatch) -> None:
    async def stream(cmd, *, cwd=None):
        raise RuntimeError("spawn failed")
        yield  # pragma: no cover

    monkeypatch.setattr(openclaw_mod, "stream_process_lines", stream)
    events, on_event = _collector()
    result = await OpenClawBackend().consult("q", on_event=on_event)

    assert not result.success
    assert result.error == "spawn failed"
    assert result.event_count == 1
    assert [e.kind for e in events] == [EVENT_ERROR]
    assert events[0].text == "spawn failed"
    assert events[0].raw == {}


# ---- parsing helpers ------------------------------------------------------------


def test_parse_json_accepts_only_objects() -> None:
    assert openclaw_mod._parse_json('{"a": 1}') == {"a": 1}
    assert openclaw_mod._parse_json("") is None
    assert openclaw_mod._parse_json("   ") is None
    assert openclaw_mod._parse_json("not json") is None
    assert openclaw_mod._parse_json("[1, 2]") is None  # arrays are not responses
    assert openclaw_mod._parse_json("3") is None
    assert openclaw_mod._parse_json('"quoted"') is None


def test_response_text_variants() -> None:
    # payloads preferred over plain keys, blank items skipped
    payload = {"result": {"payloads": [{"text": "a"}, {"text": ""}, "junk", {"text": "b"}]}}
    assert openclaw_mod._response_text(payload) == "a\n\nb"
    # payloads present but textless → fall through to plain keys
    payload = {"result": {"payloads": [{"text": ""}], "final": "plain final"}}
    assert openclaw_mod._response_text(payload) == "plain final"
    # non-dict payloads ignored
    payload = {"result": {"payloads": "nope", "response": "via response"}}
    assert openclaw_mod._response_text(payload) == "via response"
    # whitespace-only values are skipped
    assert openclaw_mod._response_text({"text": "   \n"}) == ""
    assert openclaw_mod._response_text({}) == ""


def test_response_error_variants() -> None:
    assert openclaw_mod._response_error({"error": {"message": "dict msg"}}) == "dict msg"
    assert openclaw_mod._response_error({"error": "  string msg  "}) == "string msg"
    # dict error without message falls through to summary
    assert openclaw_mod._response_error({"error": {}, "summary": "sum"}) == "sum"
    assert openclaw_mod._response_error({"summary": "just summary"}) == "just summary"
    # non-string summary → no error text
    assert openclaw_mod._response_error({"summary": 42}) == ""
    assert openclaw_mod._response_error({}) == ""
