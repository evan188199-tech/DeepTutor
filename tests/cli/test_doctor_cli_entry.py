"""Entry-point behavior gaps for the ``deeptutor doctor`` CLI command."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from deeptutor.services.doctor import DoctorCheck, DoctorReport
from deeptutor_cli.main import app

runner = CliRunner()


def _report(*checks: DoctorCheck, online: bool = False) -> DoctorReport:
    return DoctorReport(online=online, checks=list(checks))


def _pass(key: str = "llm_config") -> DoctorCheck:
    return DoctorCheck(key=key, label=key.replace("_", " ").title(), status="pass", detail="ok")


def test_doctor_rejects_unknown_output_format() -> None:
    result = runner.invoke(app, ["doctor", "--format", "yaml"])

    assert result.exit_code == 2
    assert "rich" in result.output and "json" in result.output


def test_doctor_rejects_unknown_target() -> None:
    result = runner.invoke(app, ["doctor", "elsewhere"])

    assert result.exit_code == 2
    assert "runtime" in result.output


def test_doctor_runtime_target_uses_runtime_diagnostics(monkeypatch) -> None:
    async def unexpected_setup_diagnostics(*, online: bool):
        raise AssertionError("setup diagnostics must not run for the runtime target")

    async def fake_runtime_diagnostics():
        return _report(
            DoctorCheck(
                key="turn_coordination",
                label="Turn coordination",
                status="pass",
                detail="ready",
            )
        )

    monkeypatch.setattr("deeptutor_cli.doctor.run_diagnostics", unexpected_setup_diagnostics)
    monkeypatch.setattr("deeptutor_cli.doctor.run_runtime_diagnostics", fake_runtime_diagnostics)

    result = runner.invoke(app, ["doctor", "runtime", "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["checks"][0]["key"] == "turn_coordination"


def test_doctor_rich_output_warns_for_optional_failure(monkeypatch) -> None:
    async def fake_run_diagnostics(*, online: bool):
        return _report(
            _pass(),
            DoctorCheck(
                key="rag",
                label="RAG prerequisites",
                status="fail",
                detail="advisory only",
                required=False,
            ),
        )

    monkeypatch.setattr("deeptutor_cli.doctor.run_diagnostics", fake_run_diagnostics)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "WARN" in result.output
    assert "advisory only" in result.output
    assert "Required checks passed." in result.output


def test_doctor_rich_output_marks_skipped_checks(monkeypatch) -> None:
    async def fake_run_diagnostics(*, online: bool):
        return _report(
            _pass(),
            DoctorCheck(
                key="online",
                label="Provider response",
                status="skip",
                detail="Not requested.",
                required=False,
            ),
        )

    monkeypatch.setattr("deeptutor_cli.doctor.run_diagnostics", fake_run_diagnostics)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "SKIP" in result.output


def test_doctor_rich_output_fails_on_required_failure(monkeypatch) -> None:
    async def fake_run_diagnostics(*, online: bool):
        return _report(
            _pass(),
            DoctorCheck(
                key="storage",
                label="Runtime storage",
                status="fail",
                detail="Cannot write to /data",
            ),
        )

    monkeypatch.setattr("deeptutor_cli.doctor.run_diagnostics", fake_run_diagnostics)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "FAIL" in result.output
    assert "One or more required checks failed." in result.output


def test_doctor_json_output_success_exits_zero(monkeypatch) -> None:
    async def fake_run_diagnostics(*, online: bool):
        return _report(_pass("storage"), online=False)

    monkeypatch.setattr("deeptutor_cli.doctor.run_diagnostics", fake_run_diagnostics)

    result = runner.invoke(app, ["doctor", "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["checks"][0]["key"] == "storage"
