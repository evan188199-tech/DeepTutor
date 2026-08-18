from __future__ import annotations

import plistlib
import subprocess
from typing import Any

from deeptutor.capabilities.marginnote4.automation import (
    AppleScriptProvider,
    URLSchemeProvider,
    WriteRequest,
)


class Runner:
    def __init__(self, output: str = "") -> None:
        self.output = output
        self.commands: list[list[str]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.commands.append(args[0])
        return subprocess.CompletedProcess(args[0], 0, self.output, "")


def test_applescript_requires_title_body_command(tmp_path, monkeypatch) -> None:
    app = tmp_path / "MarginNote 4.app"
    (app / "Contents").mkdir(parents=True)
    with (app / "Contents" / "Info.plist").open("wb") as handle:
        plistlib.dump(
            {
                "CFBundleIdentifier": "com.marginnote.MarginNote4",
                "CFBundleShortVersionString": "4.2",
            },
            handle,
        )
    sdef = """<dictionary><command name="make note" code="abcd">
      <parameter name="title"/><parameter name="body"/>
    </command></dictionary>"""
    runner = Runner(sdef)
    provider = AppleScriptProvider(str(app), 'tell app "MarginNote 4" to make note', runner)
    result = provider.probe()
    assert result.can_write is True
    assert result.bundle_id == "com.marginnote.MarginNote4"
    assert result.app_version == "4.2"


def test_url_scheme_never_verifies_without_human_confirmation() -> None:
    provider = URLSchemeProvider("marginnote4://note?title={title}")
    result = provider.verify(test_note_title="test")
    assert result.can_write is False
    assert "confirm" in result.reason


def test_applescript_and_url_templates_escape_payloads(tmp_path) -> None:
    commands: list[list[str]] = []

    def runner(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "note-id", "")

    apple = AppleScriptProvider(
        str(tmp_path / "MarginNote 4.app"), "make note with properties {title}", runner
    )
    assert (
        apple.apply(WriteRequest(title='Quote " and \\ newline', markdown="line one\nline two"))
        == "note-id"
    )

    url = URLSchemeProvider("marginnote4://note?title={title}&body={markdown}", "open", runner)
    url.apply(WriteRequest(title="笔记 title", markdown="a & b"))
    assert commands[-1][-1] == (
        "marginnote4://note?title=%E7%AC%94%E8%AE%B0%20title&body=a%20%26%20b"
    )
