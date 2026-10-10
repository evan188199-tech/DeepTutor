"""CLI tests for ``deeptutor partner`` lifecycle commands (list/start/stop/create).

All service access is faked: ``get_partner_manager`` is monkeypatched and
``asyncio.run`` is driven synchronously, so no real partner runtime, event
loop, channel or filesystem state is touched.
"""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from rich.console import Console
from typer.testing import CliRunner

from deeptutor_cli.main import app

runner = CliRunner()


def _run_coro_sync(coro):
    """Drive a coroutine that never awaits anything, without an event loop."""
    try:
        coro.send(None)
    except StopIteration as stop:
        return stop.value
    raise AssertionError("coroutine did not complete synchronously")


class FakeInstance:
    def __init__(self, name: str) -> None:
        self.config = SimpleNamespace(name=name)


class FakePartnerManager:
    """Fake PartnerManager covering the surface the CLI commands use."""

    def __init__(self) -> None:
        self.partners: list[dict] = []
        self.saved: list[tuple[str, object, bool | None]] = []
        self.start_calls: list[tuple[str, object | None]] = []
        self.stop_calls: list[str] = []
        self.start_error: RuntimeError | None = None
        self.start_instance: FakeInstance = FakeInstance("Alpha Bot")
        self.stop_return = True

    def list_partners(self) -> list[dict]:
        return list(self.partners)

    def save_config(self, partner_id, config, *, auto_start=None) -> None:
        self.saved.append((partner_id, config, auto_start))

    async def start_partner(self, partner_id, config=None):
        self.start_calls.append((partner_id, config))
        if self.start_error is not None:
            raise self.start_error
        return self.start_instance

    async def stop_partner(self, partner_id, *, preserve_auto_start=False) -> bool:
        self.stop_calls.append(partner_id)
        return self.stop_return


@pytest.fixture()
def cli(monkeypatch):
    import deeptutor.services.partners as partners_service
    import deeptutor_cli.partner as partner_cli

    mgr = FakePartnerManager()
    output = io.StringIO()
    monkeypatch.setattr(partners_service, "get_partner_manager", lambda: mgr)
    monkeypatch.setattr(
        partner_cli,
        "console",
        Console(file=output, width=200, force_terminal=False),
    )
    monkeypatch.setattr(partner_cli.asyncio, "run", _run_coro_sync)
    return mgr, output


# ── list ─────────────────────────────────────────────────────────────


def test_partner_list_empty_prints_placeholder(cli) -> None:
    mgr, output = cli

    result = runner.invoke(app, ["partner", "list"])

    assert result.exit_code == 0, output.getvalue()
    rendered = output.getvalue()
    assert "No partners configured." in rendered
    assert "Partners" not in rendered  # no table is rendered


def test_partner_list_renders_table_rows(cli) -> None:
    mgr, output = cli
    mgr.partners = [
        {
            "partner_id": "alpha",
            "name": "Alpha Bot",
            "running": True,
            "llm_selection": {"model_id": "gpt-x"},
            "channels": ["telegram", "slack"],
        },
        {
            "partner_id": "beta",
            "name": "Beta",
            "running": False,
            "llm_selection": None,
            "model": "legacy-m",
            "channels": [],
        },
        {
            "partner_id": "gamma",
            "name": "",
            "running": False,
            "llm_selection": None,
            "channels": [],
        },
    ]

    result = runner.invoke(app, ["partner", "list"])

    assert result.exit_code == 0, output.getvalue()
    rendered = output.getvalue()
    assert "Partners" in rendered  # table title
    assert "alpha" in rendered and "Alpha Bot" in rendered
    assert "running" in rendered and "stopped" in rendered
    assert "gpt-x" in rendered  # llm_selection.model_id wins
    assert "legacy-m" in rendered  # legacy model fallback
    assert "(default)" in rendered  # no model anywhere
    assert "telegram, slack" in rendered  # channels joined
    assert rendered.count(" - ") >= 2  # empty channels render as "-"


# ── start ────────────────────────────────────────────────────────────


def test_partner_start_success(cli) -> None:
    mgr, output = cli
    mgr.start_instance = FakeInstance("Alpha Bot")

    result = runner.invoke(app, ["partner", "start", "alpha"])

    assert result.exit_code == 0, output.getvalue()
    assert "Started partner 'Alpha Bot' (alpha)" in output.getvalue()
    assert mgr.start_calls == [("alpha", None)]


def test_partner_start_runtime_error_exits_1(cli) -> None:
    mgr, output = cli
    mgr.start_error = RuntimeError("channel token missing")

    result = runner.invoke(app, ["partner", "start", "alpha"])

    assert result.exit_code == 1
    assert "Failed to start: channel token missing" in output.getvalue()
    assert "Started partner" not in output.getvalue()


# ── stop ─────────────────────────────────────────────────────────────


def test_partner_stop_running(cli) -> None:
    mgr, output = cli
    mgr.stop_return = True

    result = runner.invoke(app, ["partner", "stop", "alpha"])

    assert result.exit_code == 0, output.getvalue()
    assert "Stopped partner 'alpha'" in output.getvalue()
    assert mgr.stop_calls == ["alpha"]


def test_partner_stop_not_running(cli) -> None:
    mgr, output = cli
    mgr.stop_return = False

    result = runner.invoke(app, ["partner", "stop", "alpha"])

    assert result.exit_code == 0, output.getvalue()
    assert "Partner 'alpha' not found or not running." in output.getvalue()


# ── create ───────────────────────────────────────────────────────────


@pytest.fixture()
def soul_writes(monkeypatch):
    import deeptutor.services.partners.workspace as workspace

    writes: list[tuple[str, str]] = []
    monkeypatch.setattr(
        workspace, "write_soul", lambda partner_id, content: writes.append((partner_id, content))
    )
    return writes


def test_partner_create_writes_soul_and_auto_starts(cli, soul_writes) -> None:
    mgr, output = cli
    mgr.start_instance = FakeInstance("Alpha Bot")

    result = runner.invoke(
        app,
        [
            "partner",
            "create",
            "alpha",
            "--name",
            "Alpha Bot",
            "--soul",
            "You are kind.",
            "--model",
            "gpt-x",
        ],
    )

    assert result.exit_code == 0, output.getvalue()
    # Config persisted with auto_start before starting.
    assert len(mgr.saved) == 1
    partner_id, config, auto_start = mgr.saved[0]
    assert partner_id == "alpha"
    assert config.name == "Alpha Bot"
    assert config.model == "gpt-x"
    assert auto_start is True
    # Soul written with the raw markdown.
    assert soul_writes == [("alpha", "You are kind.")]
    # The saved config is what gets started.
    assert mgr.start_calls == [("alpha", config)]
    assert "Created and started partner 'Alpha Bot' (alpha)" in output.getvalue()


def test_partner_create_defaults_and_skips_soul(cli, soul_writes) -> None:
    mgr, output = cli
    mgr.start_instance = FakeInstance("solo")

    result = runner.invoke(app, ["partner", "create", "solo"])

    assert result.exit_code == 0, output.getvalue()
    partner_id, config, auto_start = mgr.saved[0]
    assert partner_id == "solo"
    assert config.name == "solo"  # display name falls back to the partner id
    assert config.model is None
    assert auto_start is True
    assert soul_writes == []  # no --soul, no write
    assert "Created and started partner 'solo' (solo)" in output.getvalue()


def test_partner_create_auto_start_failure_exits_1(cli, soul_writes) -> None:
    mgr, output = cli
    mgr.start_error = RuntimeError("port busy")

    result = runner.invoke(app, ["partner", "create", "alpha", "--soul", "You are kind."])

    assert result.exit_code == 1
    rendered = output.getvalue()
    assert "Failed: port busy" in rendered
    assert "Created and started" not in rendered
    # Config was saved and soul written before the auto-start attempt failed.
    assert len(mgr.saved) == 1 and mgr.saved[0][0] == "alpha"
    assert soul_writes == [("alpha", "You are kind.")]
    assert len(mgr.start_calls) == 1
