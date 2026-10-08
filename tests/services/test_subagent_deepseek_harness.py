"""Focused coverage for the DeepSeek Harness backend's dual consult channels.

The Python SDK (``deepseek_harness``) is the preferred channel; the published
``dsh --profile headless`` CLI is the fallback when the SDK is absent. Both
surfaces are stubbed here — a fake SDK module in ``sys.modules`` and an async
generator standing in for ``stream_process_lines`` — so channel selection,
streaming-event normalisation, and failure propagation are exercised offline
without spawning any real process.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from deeptutor.services.subagent import deepseek_harness as dsh_mod
from deeptutor.services.subagent.config import BackendConfig
from deeptutor.services.subagent.types import (
    EVENT_ERROR,
    EVENT_LOG,
    EVENT_REASONING,
    EVENT_TEXT,
    EVENT_TOOL_RESULT,
    ConsultResult,
    SubagentEvent,
)


def _collector() -> tuple[list[SubagentEvent], object]:
    events: list[SubagentEvent] = []

    async def on_event(event: SubagentEvent) -> None:
        events.append(event)

    return events, on_event


def _stream(lines=None, exc: Exception | None = None):
    async def fake_stream(cmd, *, cwd=None, env=None):
        assert cmd[:3] == ["dsh", "--profile", "headless"]
        for item in lines or []:
            yield item
        if exc is not None:
            raise exc

    return fake_stream


def _harness_factory(calls: list[dict], run):
    class FakeHarness:
        def __init__(self, **kwargs):
            calls.append({"kwargs": kwargs})

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def run(self, prompt, *, session_id, on_notification):
            calls[-1]["prompt"] = prompt
            calls[-1]["session_id"] = session_id
            return run(prompt, session_id, on_notification)

    return FakeHarness


def _install_sdk(monkeypatch, harness_cls) -> None:
    module = ModuleType("deepseek_harness")
    module.DeepSeekHarness = harness_cls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepseek_harness", module)


def _notification(event) -> SimpleNamespace:
    return SimpleNamespace(method="session.event", payload={"event": event})


def _sdk_result(
    session_id: str = "sdk-sid",
    final_response: str = "",
    finish_reason: str = "completed",
):
    def run(prompt, session_id, on_notification):
        return SimpleNamespace(
            session_id=session_id or "sdk-sid",
            final_response=final_response,
            finish_reason=finish_reason,
        )

    return run


# ---- channel selection -------------------------------------------------------


@pytest.mark.asyncio
async def test_consult_prefers_sdk_channel_when_installed(monkeypatch) -> None:
    used: list[str] = []

    async def fake_sdk(self, question, **kwargs):
        used.append("sdk")
        return ConsultResult(final_text="from-sdk", session_id="sdk-1")

    async def fake_headless(self, question, **kwargs):
        used.append("headless")
        return ConsultResult(final_text="from-cli")

    monkeypatch.setattr(dsh_mod, "_sdk_available", lambda: True)
    monkeypatch.setattr(dsh_mod.DeepSeekHarnessBackend, "_consult_sdk", fake_sdk)
    monkeypatch.setattr(dsh_mod.DeepSeekHarnessBackend, "_consult_headless", fake_headless)

    events, on_event = _collector()
    result = await dsh_mod.DeepSeekHarnessBackend().consult("q", on_event=on_event)

    assert used == ["sdk"]
    assert result.success is True
    assert result.final_text == "from-sdk"
    assert result.session_id == "sdk-1"
    assert events == []


@pytest.mark.asyncio
async def test_consult_falls_back_to_headless_without_sdk(monkeypatch) -> None:
    used: list[str] = []

    async def fake_sdk(self, question, **kwargs):
        used.append("sdk")
        return ConsultResult(final_text="from-sdk")

    async def fake_headless(self, question, **kwargs):
        used.append("headless")
        assert kwargs["config"] is not None
        return ConsultResult(final_text="from-cli")

    monkeypatch.setattr(dsh_mod, "_sdk_available", lambda: False)
    monkeypatch.setattr(dsh_mod.DeepSeekHarnessBackend, "_consult_sdk", fake_sdk)
    monkeypatch.setattr(dsh_mod.DeepSeekHarnessBackend, "_consult_headless", fake_headless)

    events, on_event = _collector()
    result = await dsh_mod.DeepSeekHarnessBackend().consult("q", on_event=on_event)

    assert used == ["headless"]
    assert result.final_text == "from-cli"
    assert result.session_id is None
    assert events == []


# ---- headless CLI channel ----------------------------------------------------


def test_headless_command_composes_prompt_images_and_extra_args() -> None:
    backend = dsh_mod.DeepSeekHarnessBackend()
    bare = backend._build_headless_command("plain question", config=BackendConfig())
    assert bare == ["dsh", "--profile", "headless", "plain question"]

    composed = backend._build_headless_command(
        "review this",
        config=BackendConfig(system_prompt="Be terse", extra_args=["--flag"]),
        images=["/tmp/a.png", "/tmp/b.png"],
    )
    assert composed[:3] == ["dsh", "--profile", "headless"]
    assert "--flag" in composed
    assert composed[-1] == (
        "Be terse\n\nreview this\n\nAttached local files:\n- /tmp/a.png\n- /tmp/b.png"
    )


@pytest.mark.asyncio
async def test_headless_nonzero_exit_fails_consult_with_error_event(monkeypatch) -> None:
    monkeypatch.setattr(dsh_mod, "_sdk_available", lambda: False)
    monkeypatch.setattr(
        dsh_mod, "stream_process_lines", _stream([("stdout", "partial"), ("exit", "3")])
    )

    events, on_event = _collector()
    result = await dsh_mod.DeepSeekHarnessBackend().consult("q", on_event=on_event)

    assert result.success is False
    assert result.error == "dsh headless exited with code 3"
    assert result.final_text == "partial"
    assert result.session_id is None
    assert [event.kind for event in events] == [EVENT_TEXT, EVENT_ERROR]
    assert events[-1].raw == {"returncode": "3"}
    assert events[-1].meta == {}


@pytest.mark.asyncio
async def test_headless_blank_answer_fails_consult(monkeypatch) -> None:
    monkeypatch.setattr(dsh_mod, "_sdk_available", lambda: False)
    monkeypatch.setattr(
        dsh_mod, "stream_process_lines", _stream([("stdout", "   "), ("exit", "0")])
    )

    events, on_event = _collector()
    result = await dsh_mod.DeepSeekHarnessBackend().consult("q", on_event=on_event)

    assert result.success is False
    assert result.error == "dsh headless returned no answer"
    assert result.final_text == ""
    assert [event.kind for event in events] == [EVENT_ERROR]


@pytest.mark.asyncio
async def test_headless_stderr_log_closes_reasoning_and_skips_blank_lines(monkeypatch) -> None:
    monkeypatch.setattr(dsh_mod, "_sdk_available", lambda: False)
    monkeypatch.setattr(
        dsh_mod,
        "stream_process_lines",
        _stream(
            [
                ("stderr", "dsh: reasoning:"),
                ("stderr", "step one: read files"),
                ("stderr", "dsh: fetching context"),
                ("stderr", ""),
                ("stdout", "done"),
                ("exit", "0"),
            ]
        ),
    )

    events, on_event = _collector()
    result = await dsh_mod.DeepSeekHarnessBackend().consult("q", on_event=on_event)

    assert result.success is True
    assert result.final_text == "done"
    assert result.error == ""
    assert [event.kind for event in events] == [EVENT_REASONING, EVENT_LOG, EVENT_TEXT]
    assert events[0].text == "step one: read files"
    assert events[0].meta == {"merge_id": "deepseek:reasoning"}
    assert events[1].text == "dsh: fetching context"
    assert events[1].meta == {}


@pytest.mark.asyncio
async def test_consult_reports_error_when_sdk_missing_and_cli_stream_breaks(monkeypatch) -> None:
    monkeypatch.setattr(dsh_mod, "_sdk_available", lambda: False)
    monkeypatch.setattr(
        dsh_mod, "stream_process_lines", _stream(exc=RuntimeError("spawn boom"))
    )

    events, on_event = _collector()
    result = await dsh_mod.DeepSeekHarnessBackend().consult("q", on_event=on_event)

    assert result.success is False
    assert result.error == "spawn boom"
    assert result.final_text == ""
    assert [event.kind for event in events] == [EVENT_ERROR]


# ---- SDK channel -------------------------------------------------------------


@pytest.mark.asyncio
async def test_sdk_error_finish_reason_fails_consult(monkeypatch, tmp_path) -> None:
    calls: list[dict] = []
    _install_sdk(monkeypatch, _harness_factory(calls, _sdk_result(finish_reason="error")))
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "dsh"))

    events, on_event = _collector()
    result = await dsh_mod.DeepSeekHarnessBackend()._consult_sdk(
        "q",
        on_event=on_event,
        cwd=str(tmp_path),
        session_id=None,
        config=BackendConfig(),
        images=None,
    )

    assert len(calls) == 1
    assert result.success is False
    assert result.error == "DeepSeek Harness ended the turn with an error"
    assert result.final_text == ""
    assert [event.kind for event in events] == [EVENT_ERROR]


@pytest.mark.asyncio
async def test_sdk_publishes_final_response_when_no_text_streamed(
    monkeypatch, tmp_path
) -> None:
    _install_sdk(monkeypatch, _harness_factory([], _sdk_result(final_response="Final answer")))
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "dsh"))

    events, on_event = _collector()
    result = await dsh_mod.DeepSeekHarnessBackend()._consult_sdk(
        "q",
        on_event=on_event,
        cwd=str(tmp_path),
        session_id=None,
        config=BackendConfig(),
        images=None,
    )

    assert result.success is True
    assert result.final_text == "Final answer"
    assert result.session_id.startswith("deeptutor-")
    assert [event.kind for event in events] == [EVENT_TEXT]
    assert events[0].text == "Final answer"
    assert events[0].meta == {}


@pytest.mark.asyncio
async def test_sdk_blank_final_response_fails_consult(monkeypatch, tmp_path) -> None:
    _install_sdk(monkeypatch, _harness_factory([], _sdk_result(final_response="  ")))
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "dsh"))

    events, on_event = _collector()
    result = await dsh_mod.DeepSeekHarnessBackend()._consult_sdk(
        "q",
        on_event=on_event,
        cwd=str(tmp_path),
        session_id=None,
        config=BackendConfig(),
        images=None,
    )

    assert result.success is False
    assert result.error == "DeepSeek Harness returned no answer"
    assert [event.kind for event in events] == [EVENT_ERROR]


@pytest.mark.asyncio
async def test_sdk_run_exception_fails_consult_without_retry(monkeypatch, tmp_path) -> None:
    def run(prompt, session_id, on_notification):
        raise ValueError("quota exhausted")

    _install_sdk(monkeypatch, _harness_factory([], run))
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "dsh"))

    events, on_event = _collector()
    result = await dsh_mod.DeepSeekHarnessBackend()._consult_sdk(
        "q",
        on_event=on_event,
        cwd=str(tmp_path),
        session_id="sess-5",
        config=BackendConfig(),
        images=None,
    )

    assert result.success is False
    assert result.error == "quota exhausted"
    assert result.session_id == "sess-5"
    assert [event.kind for event in events] == [EVENT_ERROR]


@pytest.mark.asyncio
async def test_sdk_prompt_prepends_system_only_on_fresh_session(monkeypatch, tmp_path) -> None:
    calls: list[dict] = []
    _install_sdk(monkeypatch, _harness_factory(calls, _sdk_result(final_response="ok")))
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "dsh-home"))
    backend = dsh_mod.DeepSeekHarnessBackend()

    config = BackendConfig(model="deepseek-chat", effort="low", system_prompt="Be terse")
    events, on_event = _collector()
    await backend._consult_sdk(
        "q1",
        on_event=on_event,
        cwd=str(tmp_path),
        session_id=None,
        config=config,
        images=None,
    )
    await backend._consult_sdk(
        "q2",
        on_event=on_event,
        cwd=str(tmp_path),
        session_id="sess-9",
        config=config,
        images=None,
    )

    assert len(calls) == 2
    fresh, resumed = calls
    assert fresh["prompt"] == "Be terse\n\nq1"
    assert resumed["prompt"] == "q2"
    assert fresh["kwargs"]["profile"] == "sdk"
    assert fresh["kwargs"]["cwd"] == str(tmp_path)
    assert fresh["kwargs"]["dsh_home"] == str(tmp_path / "dsh-home")
    assert fresh["kwargs"]["model"] == "deepseek-chat"
    assert fresh["kwargs"]["reasoning_effort"] == "low"
    assert fresh["session_id"].startswith("deeptutor-")
    assert resumed["session_id"] == "sess-9"

    bare_calls: list[dict] = []
    _install_sdk(monkeypatch, _harness_factory(bare_calls, _sdk_result(final_response="ok")))
    await backend._consult_sdk(
        "q",
        on_event=on_event,
        cwd=str(tmp_path),
        session_id=None,
        config=BackendConfig(),
        images=None,
    )
    assert "model" not in bare_calls[0]["kwargs"]
    assert "reasoning_effort" not in bare_calls[0]["kwargs"]


def test_sdk_notification_normalisation_merges_and_maps() -> None:
    state: dict[str, dict[str, str]] = {"text": {}, "reasoning": {}}

    first = dsh_mod._sdk_notification_events(
        _notification(
            {"type": "assistant/chunk", "data": {"step": 2, "chunk": {"type": "text-delta", "text": "Hel"}}}
        ),
        state,
    )
    second = dsh_mod._sdk_notification_events(
        _notification(
            {"type": "assistant/chunk", "data": {"step": 2, "chunk": {"type": "text-delta", "text": "lo"}}}
        ),
        state,
    )
    assert first[0].kind == EVENT_TEXT
    assert first[0].meta == {"merge_id": "deepseek:text:2"}
    assert second[0].text == "Hello"

    duplicate = dsh_mod._sdk_notification_events(
        _notification(
            {
                "type": "assistant/message",
                "data": {"step": 2, "message": {"content": [{"type": "text", "text": "Hello"}]}},
            }
        ),
        state,
    )
    assert duplicate == []

    turn_error = dsh_mod._sdk_notification_events(
        _notification({"type": "turn/end", "data": {"reason": {"kind": "error", "message": "boom"}}}),
        state,
    )
    assert turn_error[0].kind == EVENT_ERROR
    assert turn_error[0].text == "boom"

    turn_ok = dsh_mod._sdk_notification_events(
        _notification({"type": "turn/end", "data": {"reason": {"kind": "complete"}}}),
        state,
    )
    assert turn_ok == []

    tool_result = dsh_mod._sdk_notification_events(
        _notification(
            {"type": "tool/result", "data": {"step": 1, "message": {"content": [{"type": "text", "text": "42"}]}}}
        ),
        state,
    )
    assert tool_result[0].kind == EVENT_TOOL_RESULT
    assert tool_result[0].text == "42"

    empty_result = dsh_mod._sdk_notification_events(
        _notification({"type": "tool/result", "data": {"message": {}}}),
        state,
    )
    assert empty_result[0].kind == EVENT_TOOL_RESULT
    assert empty_result[0].text == "(empty result)"

    assert dsh_mod._sdk_notification_events(SimpleNamespace(method="other", payload={}), state) == []
    assert dsh_mod._sdk_notification_events(SimpleNamespace(method="session.event", payload="nope"), state) == []
    assert (
        dsh_mod._sdk_notification_events(_notification({"event": "not-a-dict"}), state) == []
    )
    assert (
        dsh_mod._sdk_notification_events(
            _notification(
                {"type": "assistant/chunk", "data": {"step": 1, "chunk": {"type": "screenshot", "text": "x"}}}
            ),
            state,
        )
        == []
    )
    assert (
        dsh_mod._sdk_notification_events(
            _notification(
                {"type": "assistant/chunk", "data": {"step": 1, "chunk": {"type": "text-delta", "text": ""}}}
            ),
            state,
        )
        == []
    )


# ---- detection ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_reports_sdk_or_cli_and_details_when_both_missing(monkeypatch) -> None:
    backend = dsh_mod.DeepSeekHarnessBackend()

    async def probe_missing(cmd):
        return False, "not installed"

    monkeypatch.setattr(dsh_mod, "probe_version", probe_missing)
    monkeypatch.setattr(dsh_mod, "_sdk_available", lambda: True)
    sdk_only = await backend.detect()
    assert sdk_only.available is True
    assert sdk_only.version == "Python SDK"
    assert sdk_only.detail == ""

    async def probe_cli(cmd):
        return True, "dsh 2.3.1"

    monkeypatch.setattr(dsh_mod, "probe_version", probe_cli)
    monkeypatch.setattr(dsh_mod, "_sdk_available", lambda: False)
    cli_only = await backend.detect()
    assert cli_only.available is True
    assert cli_only.version == "dsh 2.3.1"
    assert cli_only.detail == ""

    monkeypatch.setattr(dsh_mod, "probe_version", probe_missing)
    monkeypatch.setattr(dsh_mod, "_sdk_available", lambda: False)
    neither = await backend.detect()
    assert neither.available is False
    assert neither.version == ""
    assert neither.detail == "dsh CLI / Python SDK not found"
