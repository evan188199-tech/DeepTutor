from __future__ import annotations

import json
from pathlib import Path
import plistlib
import subprocess
from typing import Any

from typer.testing import CliRunner

from deeptutor_cli import mn4_bridge
from deeptutor_cli.main import app

runner = CliRunner()


def _config(tmp_path: Path, **extra: Any) -> Path:
    path = tmp_path / "bridge.json"
    path.write_text(
        json.dumps(
            {
                "server_url": "http://127.0.0.1:8001",
                "notebook_path": str(tmp_path / "exports"),
                "device_id": "dev1",
                "journal_path": str(tmp_path / "bridge.sqlite"),
                "token_storage": "file",
                **extra,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_install_writes_and_bootstraps_launch_agent(tmp_path: Path, monkeypatch) -> None:
    agent = tmp_path / "LaunchAgents" / "bridge.plist"
    agent.parent.mkdir(parents=True)
    config = _config(tmp_path)
    commands: list[list[str]] = []

    def fake_launchctl(args: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(mn4_bridge, "LAUNCH_AGENT", agent)
    monkeypatch.setattr(mn4_bridge, "_run_launchctl", fake_launchctl)
    monkeypatch.setattr(mn4_bridge.shutil, "which", lambda name: f"/usr/bin/{name}")

    result = runner.invoke(app, ["mn4", "bridge", "install", "--config", str(config)])
    assert result.exit_code == 0, result.output
    payload = plistlib.loads(agent.read_bytes())
    assert payload["Label"] == "com.deeptutor.marginnote4.bridge"
    assert payload["ProgramArguments"][-1] == str(config)
    assert commands[1][:3] == [
        "/usr/bin/launchctl",
        "bootstrap",
        f"gui/{commands[1][2].split('/')[-1]}",
    ]
    assert commands[1][-1] == str(agent)


def test_url_scheme_verification_requires_external_id_confirmation(
    tmp_path: Path, monkeypatch
) -> None:
    from deeptutor.capabilities.marginnote4 import bridge as bridge_module

    config = _config(
        tmp_path,
        automation_provider="url_scheme",
        url_action_template="marginnote4://note?title={title}",
    )
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, server_url: str) -> None:
            self.server_url = server_url

        def verify_automation(
            self, device_id: str, token: str, payload: dict[str, Any]
        ) -> dict[str, Any]:
            captured.update({"device_id": device_id, "token": token, "payload": payload})
            return {"status": "verified"}

    monkeypatch.setattr(bridge_module, "BridgeClient", FakeClient)
    monkeypatch.setattr(bridge_module, "load_token", lambda _config: "secret")

    denied = runner.invoke(
        app, ["mn4", "bridge", "verify", "--config", str(config), "--provider", "url_scheme"]
    )
    assert denied.exit_code == 1
    assert "manually confirmed" in denied.output

    accepted = runner.invoke(
        app,
        [
            "mn4",
            "bridge",
            "verify",
            "--config",
            str(config),
            "--provider",
            "url_scheme",
            "--confirm-external-id",
            "note-123",
        ],
    )
    assert accepted.exit_code == 0, accepted.output
    assert captured["device_id"] == "dev1"
    assert captured["token"] == "secret"
    assert captured["payload"]["provider"] == "url_scheme"
    assert captured["payload"]["test_external_id"] == "note-123"
    assert captured["payload"]["verified"] is True
