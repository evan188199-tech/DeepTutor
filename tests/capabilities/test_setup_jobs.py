"""Focused tests for the setup job runner in ``capabilities.setup.jobs``.

The module wraps the background install/download subprocess managers so the
chat surface can start a job and follow its log inside one tool call. Each
test pins one behaviour that fails silently when it breaks:

* **Lifecycle.** ``run_job`` must reach every terminal state the manager can
  report — ``done``, ``failed``, ``cancelled`` — and keep following when the
  budget runs out instead of killing a healthy multi-GB download.
* **Input shaping.** The model supplies free-text action and engine strings;
  normalization is the only thing standing between ``"Deep-Learning"`` and a
  lookup that never matches.
* **Duplicate triggers.** At most one job runs at a time. A second start while
  one is running must be refused with a message, never queued invisibly — and
  once a job finishes, starting it again must work.
* **Allow-lists.** Downloads resolve through the engine tables; a missing
  binary or an engine with no downloader is refused before anything launches.

Every subprocess is replaced: the real ``BackgroundJobManager`` runs against a
fake ``Popen`` so no package, download, or process is ever touched.
"""

from __future__ import annotations

import subprocess
import threading
from typing import Any

import pytest

from deeptutor.capabilities.setup import jobs as jobs_module
from deeptutor.capabilities.setup.jobs import JobOutcome, available_jobs, run_job
from deeptutor.services.parsing.engines import _install as install_module


def _fast_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs_module, "_POLL_INTERVAL_SECONDS", 0.01)


class _ScriptedManager:
    """Manager stand-in that replays canned ``status`` responses."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.status_calls = 0
        self.start_calls: list[dict[str, Any]] = []

    def status(self, cursor: int = 0) -> dict[str, Any]:
        self.status_calls += 1
        if self._responses:
            return self._responses.pop(0)
        return {"state": "running", "lines": [], "next_cursor": cursor, "message": ""}

    def start_model_download(self, **kwargs: Any) -> dict[str, Any]:
        self.start_calls.append(kwargs)
        return {"ok": True, "message": ""}

    def start(self, **kwargs: Any) -> dict[str, Any]:
        self.start_calls.append(kwargs)
        return {"ok": True, "message": ""}


class _FakeProcess:
    """A ``Popen`` double: stdout is a plain iterator, exit code is fixed."""

    def __init__(self, lines: list[str], returncode: int, release: threading.Event) -> None:
        self.stdout = iter(lines)
        self._returncode = returncode
        self._release = release

    def wait(self, timeout: float | None = None) -> int:
        self._release.wait(timeout=5)
        return self._returncode

    def poll(self) -> int | None:
        return None if not self._release.is_set() else self._returncode


def _use_real_manager(
    monkeypatch: pytest.MonkeyPatch,
    processes: list[_FakeProcess],
) -> install_module.BackgroundJobManager:
    """Route jobs through a real ``BackgroundJobManager`` over fake processes."""
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: processes.pop(0))
    monkeypatch.setattr(install_module, "_invalidate_import_caches", lambda: None)
    monkeypatch.setattr(install_module, "_LINE_MIN_INTERVAL", 0.0)
    manager = install_module.BackgroundJobManager()
    monkeypatch.setattr(install_module, "_manager", manager)
    return manager


def _wait_until_settled(manager: install_module.BackgroundJobManager, timeout: float = 2.0) -> str:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = str(manager.status()["state"])
        if state in {"done", "failed", "cancelled"}:
            return state
        time.sleep(0.01)
    return str(manager.status()["state"])


# ---------------------------------------------------------------------------
# Lifecycle — success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_job_follows_the_log_to_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A healthy install streams its lines and ends ``done``."""
    _fast_poll(monkeypatch)
    release = threading.Event()
    release.set()
    process = _FakeProcess(["Collecting docling", "Installing collected packages"], 0, release)
    _use_real_manager(monkeypatch, [process])

    relayed: list[str] = []

    async def _on_line(line: str) -> None:
        relayed.append(line)

    outcome = await run_job("install_engine", "docling", on_line=_on_line)

    assert outcome.ok
    assert outcome.state == "done"
    assert outcome.lines == ["Collecting docling", "Installing collected packages"]
    assert relayed == outcome.lines, "every log line must be relayed live, in order"
    assert outcome.message == "Finished."
    assert outcome.still_running is False


@pytest.mark.asyncio
async def test_run_job_reports_a_failed_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-zero exit is a failed job, but the log still reaches the caller."""
    _fast_poll(monkeypatch)
    release = threading.Event()
    release.set()
    process = _FakeProcess(["Resolving dependencies", "ERROR: conflict"], 1, release)
    _use_real_manager(monkeypatch, [process])

    outcome = await run_job("install_engine", "docling")

    assert not outcome.ok
    assert outcome.state == "failed"
    assert "Exited with code 1." in outcome.message
    assert "ERROR: conflict" in outcome.lines


@pytest.mark.asyncio
async def test_run_job_reports_a_cancelled_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``cancelled`` is terminal, and it is not a success."""
    _fast_poll(monkeypatch)
    manager = _ScriptedManager(
        [
            {
                "state": "cancelled",
                "lines": ["Cancel requested"],
                "next_cursor": 1,
                "message": "Cancelled.",
            }
        ]
    )
    monkeypatch.setattr(jobs_module, "_start_install", lambda engine: (True, "", manager))

    seen: list[str] = []

    async def _on_line(line: str) -> None:
        seen.append(line)

    outcome = await run_job("install_engine", "docling", on_line=_on_line)

    assert not outcome.ok
    assert outcome.state == "cancelled"
    assert outcome.message == "Cancelled."
    assert seen == ["Cancel requested"]


@pytest.mark.asyncio
async def test_run_job_reports_still_running_when_the_budget_runs_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hitting the follow cap must not kill the job — it keeps running."""
    monkeypatch.setattr(jobs_module, "_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(jobs_module, "_MAX_FOLLOW_SECONDS", 0.04)
    manager = _ScriptedManager([])
    monkeypatch.setattr(jobs_module, "_start_install", lambda engine: (True, "", manager))

    outcome = await run_job("install_engine", "docling")

    assert outcome.ok
    assert outcome.state == "running"
    assert outcome.still_running is True
    assert "Still running" in outcome.message
    assert "inspect_setup" in outcome.message


# ---------------------------------------------------------------------------
# Input shaping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_job_normalizes_action_and_engine_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Model-supplied text is trimmed, lowercased, and dash-normalized."""
    _fast_poll(monkeypatch)
    seen: dict[str, str] = {}

    def _capture(engine: str) -> tuple[bool, str, Any]:
        seen["engine"] = engine
        return False, "stop here", None

    monkeypatch.setattr(jobs_module, "_start_install", _capture)

    outcome = await run_job("  Install_Engine ", " Deep-Learning ")

    assert seen["engine"] == "deep_learning"
    assert not outcome.ok
    assert outcome.message == "stop here"
    assert outcome.engine == "deep_learning"


@pytest.mark.asyncio
async def test_run_job_refuses_an_empty_or_unknown_action() -> None:
    """Nothing starts for a blank or unrecognized action."""
    for action in ("", "   ", None, "rm_rf"):
        outcome = await run_job(action, "docling")  # type: ignore[arg-type]

        assert not outcome.ok
        assert "Unknown setup job" in outcome.message
        assert outcome.lines == []


# ---------------------------------------------------------------------------
# Duplicate triggers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_job_surfaces_an_already_running_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second start while one job runs is refused, not silently queued."""
    monkeypatch.setattr(jobs_module, "_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(jobs_module, "_MAX_FOLLOW_SECONDS", 0.03)
    hold = threading.Event()
    held = _FakeProcess([], 0, hold)  # blocks in wait() until released
    _use_real_manager(monkeypatch, [held])
    try:
        first = await run_job("install_engine", "docling")
        assert first.still_running is True, "precondition: the first job holds the slot"

        second = await run_job("install_engine", "docling")

        assert not second.ok
        assert "already running" in second.message
        assert second.lines == [] and second.state == ""
    finally:
        hold.set()
        assert _wait_until_settled(install_module.get_background_job_manager()) in {
            "done",
            "failed",
            "cancelled",
        }


@pytest.mark.asyncio
async def test_a_completed_job_can_be_started_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry semantics: a finished job releases the slot for a fresh start."""
    _fast_poll(monkeypatch)
    releases = [threading.Event(), threading.Event()]
    for event in releases:
        event.set()
    processes = [
        _FakeProcess(["first run"], 0, releases[0]),
        _FakeProcess(["second run"], 0, releases[1]),
    ]
    _use_real_manager(monkeypatch, list(processes))

    first = await run_job("install_engine", "docling")
    second = await run_job("install_engine", "docling")

    assert first.ok and first.state == "done"
    assert second.ok and second.state == "done"
    assert second.lines == ["second run"], "the retry runs a fresh process, not the old log"


# ---------------------------------------------------------------------------
# Download allow-lists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_job_refuses_a_download_for_an_engine_without_a_downloader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fast_poll(monkeypatch)
    monkeypatch.setattr(install_module, "model_downloadable_engines", lambda: frozenset())

    outcome = await run_job("download_models", "docling")

    assert not outcome.ok
    assert "no model download step" in outcome.message


@pytest.mark.asyncio
async def test_run_job_reports_a_missing_downloader_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fast_poll(monkeypatch)
    monkeypatch.setattr(
        install_module, "model_downloadable_engines", lambda: frozenset({"docling"})
    )
    monkeypatch.setattr(install_module, "resolve_model_downloader", lambda engine: None)

    outcome = await run_job("download_models", "docling")

    assert not outcome.ok
    assert "was not found" in outcome.message


@pytest.mark.asyncio
async def test_run_job_starts_the_resolved_model_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fast_poll(monkeypatch)
    monkeypatch.setattr(
        install_module, "model_downloadable_engines", lambda: frozenset({"docling"})
    )
    monkeypatch.setattr(
        install_module, "resolve_model_downloader", lambda engine: ["docling-tools", "models"]
    )
    manager = _ScriptedManager(
        [{"state": "done", "lines": [], "next_cursor": 0, "message": "Finished."}]
    )
    monkeypatch.setattr(install_module, "_manager", manager)

    outcome = await run_job("download_models", "docling")

    assert outcome.ok and outcome.state == "done"
    assert manager.start_calls == [{"engine": "docling", "cmd": ["docling-tools", "models"]}]


# ---------------------------------------------------------------------------
# MinerU downloads
# ---------------------------------------------------------------------------


def _patch_mineru_settings(monkeypatch: pytest.MonkeyPatch, engines: dict[str, Any]) -> None:
    from deeptutor.services.config import runtime_settings

    class _SettingsService:
        def load_document_parsing(self) -> dict[str, Any]:
            return {"engines": engines}

    monkeypatch.setattr(
        runtime_settings, "get_runtime_settings_service", lambda: _SettingsService()
    )


@pytest.mark.asyncio
async def test_run_job_reports_a_missing_mineru_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.parsing.engines.mineru import models as mineru_models

    _fast_poll(monkeypatch)
    _patch_mineru_settings(monkeypatch, {"mineru": {}})
    monkeypatch.setattr(mineru_models, "resolve_models_downloader", lambda path: {"found": False})

    outcome = await run_job("download_models", "mineru")

    assert not outcome.ok
    assert "MinerU model downloader was not found" in outcome.message


@pytest.mark.asyncio
async def test_run_job_mineru_download_falls_back_to_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.parsing.engines.mineru import models as mineru_models

    _fast_poll(monkeypatch)
    _patch_mineru_settings(monkeypatch, {"mineru": {"local_cli_path": "/opt/mineru"}})
    monkeypatch.setattr(
        mineru_models,
        "resolve_models_downloader",
        lambda path: {"found": True, "path": "/opt/mineru/bin/downloader"},
    )
    manager = _ScriptedManager(
        [{"state": "done", "lines": [], "next_cursor": 0, "message": "Finished."}]
    )
    monkeypatch.setattr(mineru_models, "get_model_download_manager", lambda: manager)

    outcome = await run_job("download_models", "mineru")

    assert outcome.ok and outcome.state == "done"
    assert manager.start_calls == [
        {
            "downloader": "/opt/mineru/bin/downloader",
            "model_type": "pipeline",
            "source": "huggingface",
            "endpoint": "",
        }
    ]


# ---------------------------------------------------------------------------
# available_jobs
# ---------------------------------------------------------------------------


def _patch_registry(
    monkeypatch: pytest.MonkeyPatch,
    *,
    engines: list[dict[str, Any]],
    available: set[str],
    installable: set[str],
    downloadable: set[str],
) -> None:
    from deeptutor.services.parsing.engines import factory

    monkeypatch.setattr(factory, "list_engines", lambda: engines)
    monkeypatch.setattr(factory, "is_engine_available", lambda name: name in available)
    monkeypatch.setattr(install_module, "installable_engines", lambda: frozenset(installable))
    monkeypatch.setattr(
        install_module, "model_downloadable_engines", lambda: frozenset(downloadable)
    )


def test_available_jobs_offer_install_only_for_missing_installable_engines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_registry(
        monkeypatch,
        engines=[{"id": "docling", "name": "Docling", "description": "pdf"}],
        available=set(),
        installable={"docling"},
        downloadable=set(),
    )

    listed = available_jobs()

    assert [(job["action"], job["engine"]) for job in listed] == [("install_engine", "docling")]
    assert listed[0]["label"] == "Install Docling"


def test_available_jobs_offer_model_download_only_for_installed_engines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_registry(
        monkeypatch,
        engines=[
            {"id": "docling", "name": "Docling", "description": "pdf"},
            {"id": "markitdown", "name": "MarkItDown", "description": "office"},
        ],
        available={"docling"},
        installable={"docling"},
        downloadable={"docling"},
    )

    listed = available_jobs()

    assert [(job["action"], job["engine"]) for job in listed] == [("download_models", "docling")]


def test_available_jobs_lists_the_mineru_download_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MinerU uses its own CLI, so it is appended — but never duplicated."""
    _patch_registry(
        monkeypatch,
        engines=[{"id": "mineru", "name": "MinerU", "description": "pdf"}],
        available={"mineru"},
        installable=set(),
        downloadable=set(),
    )

    listed = available_jobs()
    mineru_entries = [job for job in listed if job["engine"] == "mineru"]

    assert len(mineru_entries) == 1
    assert mineru_entries[0]["action"] == "download_models"


def test_available_jobs_skip_an_engine_without_an_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_registry(
        monkeypatch,
        engines=[{"id": "", "name": "Ghost"}, {"name": "NoIdHere"}],
        available=set(),
        installable={"docling"},
        downloadable=set(),
    )

    assert available_jobs() == []


# ---------------------------------------------------------------------------
# Result payload
# ---------------------------------------------------------------------------


def test_job_outcome_to_dict_keeps_only_the_log_tail() -> None:
    outcome = JobOutcome(
        ok=True,
        action="install_engine",
        engine="docling",
        lines=[f"l{i}" for i in range(25)],
    )

    payload = outcome.to_dict()

    assert len(payload["log_tail"]) == 20
    assert payload["log_tail"][0] == "l5"
    assert payload["log_tail"][-1] == "l24"


def test_job_outcome_to_dict_reports_still_running() -> None:
    outcome = JobOutcome(ok=True, action="install_engine", engine="docling", still_running=True)

    assert outcome.to_dict()["still_running"] is True
