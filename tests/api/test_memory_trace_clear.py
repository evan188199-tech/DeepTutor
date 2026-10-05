"""DELETE /api/memory/trace/{surface} — bulk trace clear failure visibility.

``clear_trace`` unlinks each ``trace/<surface>/*.jsonl`` and keeps going when
one file cannot be removed (narrow ``OSError`` semantics, truthful
``removed_files``). The failure must be logged so a partial cleanup — disk
residue that no longer matches the trace browser's view — is visible.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient

memory_router = importlib.import_module("deeptutor.api.routers.memory").router
paths_mod = importlib.import_module("deeptutor.services.memory.paths")

LOGGER_NAME = "deeptutor.api.routers.memory"


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(paths_mod, "memory_root", lambda: tmp_path)
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memory")
    return TestClient(app)


def _seed_trace_files(tmp_path: Path, surface: str, *names: str) -> None:
    trace_dir = tmp_path / "trace" / surface
    trace_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (trace_dir / name).write_text("{}\n", encoding="utf-8")


def test_clear_trace_removes_all_files_and_reports_count(
    client: TestClient, tmp_path: Path
) -> None:
    _seed_trace_files(tmp_path, "chat", "2026-10-01.jsonl", "2026-10-02.jsonl")

    res = client.delete("/api/memory/trace/chat")

    assert res.status_code == 200
    assert res.json() == {"surface": "chat", "removed_files": 2}
    assert not list((tmp_path / "trace" / "chat").glob("*.jsonl"))


def test_clear_trace_404_on_unknown_surface(client: TestClient) -> None:
    res = client.delete("/api/memory/trace/not-a-surface")

    assert res.status_code == 404


def test_clear_trace_warns_and_continues_when_one_unlink_fails(
    client: TestClient, tmp_path: Path, monkeypatch, caplog
) -> None:
    _seed_trace_files(
        tmp_path,
        "chat",
        "2026-10-01.jsonl",
        "2026-10-02.jsonl",
        "2026-10-03.jsonl",
    )
    real_unlink = Path.unlink

    def flaky_unlink(self: Path, *, missing_ok: bool = False) -> None:
        if self.name == "2026-10-02.jsonl":
            raise OSError("simulated removal failure")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        res = client.delete("/api/memory/trace/chat")

    assert res.status_code == 200
    assert res.json() == {"surface": "chat", "removed_files": 2}

    trace_dir = tmp_path / "trace" / "chat"
    assert (trace_dir / "2026-10-02.jsonl").exists()
    assert not (trace_dir / "2026-10-01.jsonl").exists()
    assert not (trace_dir / "2026-10-03.jsonl").exists()

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "2026-10-02.jsonl" in message
    assert "chat" in message
