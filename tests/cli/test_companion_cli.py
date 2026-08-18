"""Companion CLI contract tests."""

from __future__ import annotations

from typer.testing import CliRunner

from deeptutor_cli import companion
from deeptutor_cli.main import app


def test_companion_setup_reports_missing_tailscale(monkeypatch) -> None:
    monkeypatch.setattr(companion.shutil, "which", lambda _name: None)

    result = CliRunner().invoke(app, ["companion", "setup"])

    assert result.exit_code == 1
    assert "Tailscale not found" in result.output
