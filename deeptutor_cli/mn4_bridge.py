"""CLI for the local MarginNote 4 bridge."""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
from typing import Any

import typer

from deeptutor.capabilities.marginnote4.automation import (
    AppleScriptProvider,
    AutomationProvider,
    ProbeResult,
    ShortcutProvider,
    URLSchemeProvider,
    config_hash,
)
from deeptutor.capabilities.marginnote4.bridge import (
    BridgeConfig,
    BridgeError,
    BridgeRunner,
    pair_bridge,
)

bridge_app = typer.Typer(help="Manage the local MarginNote 4 bridge.")
mn4_app = typer.Typer(help="Manage MarginNote 4 integration.")
mn4_app.add_typer(bridge_app, name="bridge")

LAUNCH_AGENT = Path.home() / "Library" / "LaunchAgents" / "com.deeptutor.marginnote4.bridge.plist"


def _echo(value: Any) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def _run_launchctl(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, capture_output=True, text=True)


def _load_launch_agent(plist_path: Path) -> None:
    launchctl = shutil.which("launchctl")
    if not launchctl:
        raise typer.BadParameter("launchctl is required on macOS")
    gui_domain = f"gui/{os.getuid()}"
    _run_launchctl([launchctl, "bootout", gui_domain, str(plist_path)])
    bootstrapped = _run_launchctl([launchctl, "bootstrap", gui_domain, str(plist_path)])
    if bootstrapped.returncode:
        loaded = _run_launchctl([launchctl, "load", str(plist_path)])
        if loaded.returncode:
            message = bootstrapped.stderr.strip() or loaded.stderr.strip()
            raise typer.BadParameter(f"Could not load LaunchAgent: {message}")


@bridge_app.command()
def pair(
    server: str = typer.Option(..., help="DeepTutor server base URL."),
    code: str = typer.Option(..., help="One-time pairing code."),
    notebook: Path = typer.Option(..., help="MN4 Markdown/OPML export folder."),
    config: Path = typer.Option(
        Path.home() / ".deeptutor" / "mn4-bridge.json", help="Bridge config path."
    ),
    device_name: str = typer.Option("", help="Device label shown in DeepTutor."),
    token_storage: str = typer.Option(
        "", help="keychain (macOS default) or file.", metavar="[keychain|file]"
    ),
) -> None:
    """Pair this Mac with a DeepTutor MarginNote 4 KB."""
    try:
        _echo(
            pair_bridge(
                server_url=server,
                code=code,
                notebook_path=str(notebook),
                config_path=config,
                device_name=device_name,
                token_storage=token_storage,
            )
        )
    except BridgeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@bridge_app.command()
def status(
    config: Path = typer.Option(
        Path.home() / ".deeptutor" / "mn4-bridge.json", help="Bridge config path."
    ),
) -> None:
    """Show local pairing, journal, and LaunchAgent status."""
    try:
        data = BridgeConfig(config).load()
    except BridgeError as exc:
        _echo({"configured": False, "error": str(exc)})
        return
    journal = Path(data.get("journal_path", str(config.with_suffix(".sqlite"))))
    _echo(
        {
            "configured": True,
            "server_url": data["server_url"],
            "notebook_path": data["notebook_path"],
            "device_id": data.get("device_id"),
            "journal_exists": journal.exists(),
            "launch_agent_installed": LAUNCH_AGENT.exists(),
        }
    )


@bridge_app.command()
def run(
    config: Path = typer.Option(
        Path.home() / ".deeptutor" / "mn4-bridge.json", help="Bridge config path."
    ),
    once: bool = typer.Option(False, "--once", help="Run one sync/writeback cycle."),
    interval: float = typer.Option(1.5, help="Polling interval in seconds."),
    confirm_bulk_delete: bool = typer.Option(
        False, help="Allow a deliberately confirmed bulk deletion."
    ),
) -> None:
    """Sync exports upstream and deliver approved writebacks downstream."""
    try:
        runner = BridgeRunner(config)
        if once:
            _echo(runner.run_once(confirm_bulk_delete=confirm_bulk_delete))
        else:
            runner.run_forever(interval=interval)
    except BridgeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@bridge_app.command()
def install(
    config: Path = typer.Option(
        Path.home() / ".deeptutor" / "mn4-bridge.json", help="Bridge config path."
    ),
) -> None:
    """Install a per-user LaunchAgent that keeps the bridge running."""
    BridgeConfig(config).load()
    agent = LAUNCH_AGENT
    agent.parent.mkdir(parents=True, exist_ok=True)
    bin_deeptutor = Path(sys.executable).parent / "deeptutor"
    if shutil.which("deeptutor"):
        args = [shutil.which("deeptutor")]
    elif bin_deeptutor.exists():
        args = [str(bin_deeptutor)]
    else:
        args = [sys.executable, "-m", "deeptutor_cli.main"]
    args.extend(["mn4", "bridge", "run", "--config", str(config.expanduser())])
    plist = plistlib.dumps(
        {
            "Label": "com.deeptutor.marginnote4.bridge",
            "ProgramArguments": args,
            "WorkingDirectory": "/Users/Shared/DeepTutor",
            "EnvironmentVariables": {"DEEPTUTOR_HOME": "/Users/Shared/DeepTutor"},
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},
            "StandardOutPath": str(config.with_suffix(".log").expanduser()),
            "StandardErrorPath": str(config.with_suffix(".log").expanduser()),
        }
    )
    agent.write_bytes(plist)
    agent.chmod(0o600)
    try:
        _load_launch_agent(agent)
    except typer.BadParameter as exc:
        agent.unlink(missing_ok=True)
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    _echo({"installed": True, "path": str(agent)})


@bridge_app.command()
def uninstall() -> None:
    """Remove the bridge LaunchAgent definition."""
    if LAUNCH_AGENT.exists():
        if launchctl := shutil.which("launchctl"):
            _run_launchctl([launchctl, "bootout", f"gui/{os.getuid()}", str(LAUNCH_AGENT)])
        LAUNCH_AGENT.unlink()
    _echo({"installed": False, "path": str(LAUNCH_AGENT)})


@bridge_app.command()
def verify(
    config: Path = typer.Option(
        Path.home() / ".deeptutor" / "mn4-bridge.json", help="Bridge config path."
    ),
    provider: str = typer.Option(..., help="applescript, shortcut, or url_scheme."),
    test_note_title: str = typer.Option(
        "DeepTutor MN4 Bridge Verification", help="Title used for the test note."
    ),
    confirm_external_id: str = typer.Option(
        "",
        help="Confirm a URL Scheme test note by its MarginNote note/id evidence.",
    ),
) -> None:
    """Run a provider verification and record it against this device."""
    from deeptutor.capabilities.marginnote4.bridge import BridgeClient, load_token

    cfg = BridgeConfig(config)
    data = cfg.load()
    providers: dict[str, AutomationProvider] = {
        "applescript": AppleScriptProvider(
            app_path=data.get("app_path", "/Applications/MarginNote 4.app"),
            script_template=data.get("applescript_template", ""),
        ),
        "shortcut": ShortcutProvider(str(data.get("shortcut_name") or "")),
        "url_scheme": URLSchemeProvider(str(data.get("url_action_template") or "")),
    }
    selected = providers.get(provider.lower())
    if selected is None:
        typer.echo(f"Unknown provider: {provider}", err=True)
        raise typer.Exit(code=1)
    result: ProbeResult = selected.verify(test_note_title=test_note_title)
    manually_confirmed = selected.name == "url_scheme" and bool(confirm_external_id.strip())
    if not result.can_write and not manually_confirmed:
        _echo({"verified": False, **asdict(result)})
        raise typer.Exit(code=1)
    client = BridgeClient(data["server_url"])
    token = load_token(cfg)
    client.verify_automation(
        data["device_id"],
        token,
        {
            "provider": selected.name,
            "bundle_id": result.bundle_id or "unknown",
            "app_version": result.app_version or "unknown",
            "config_hash": config_hash(selected),
            "test_external_id": confirm_external_id.strip()
            or (result.evidence[-1] if result.evidence else ""),
            "verified": True,
        },
    )
    _echo({"verified": True, **asdict(result)})


def register(app: typer.Typer) -> None:
    app.add_typer(mn4_app, name="mn4")


__all__ = ["bridge_app", "mn4_app", "register"]
