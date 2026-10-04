"""Boundary tests for the KB upload entry (AGEN-495).

``POST /api/knowledge-bases/{kb}/upload`` is the single write entry for
knowledge-base files. These tests lock the current behavior of its input
boundaries so refactors cannot silently change them:

1. unsupported extensions are rejected up front with a readable error;
2. empty files are accepted at the entry (content checks belong to the
   parsing stage), while an empty ``.zip`` cannot pass archive expansion;
3. oversize uploads are rejected before anything is written;
4. corrupted content with an accepted suffix (fake PDF, junk archive) is
   deferred to parsing at the entry, but a fake/truncated ``.zip`` fails
   archive expansion with a readable error;
5. truncated files are written verbatim when their suffix is accepted.

Every 4xx assertion also checks that the error names the offending file and
states the problem, so failures stay readable for users. No product code is
changed by this file.
"""

from __future__ import annotations

import importlib
import io
import json
from pathlib import Path
import zipfile

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.utils.document_validator import DocumentValidator

try:
    knowledge_router_module = importlib.import_module("deeptutor.api.routers.knowledge")
    router = knowledge_router_module.router
except Exception:  # pragma: no cover - optional heavy imports in lightweight envs
    knowledge_router_module = None
    router = None

pytestmark = pytest.mark.skipif(
    router is None, reason="deeptutor.api.routers.knowledge could not be imported"
)


@pytest.fixture(autouse=True)
def _disable_pocketbase(monkeypatch):
    monkeypatch.setattr("deeptutor.services.pocketbase_client.is_pocketbase_enabled", lambda: False)


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def _real_manager(monkeypatch, tmp_path: Path):
    """A real ``KnowledgeBaseManager`` on a throwaway base dir.

    The upload route keeps its legacy ``get_kb_manager`` seam (see
    ``_overridden_kb_manager``), so patching it routes the entry through the
    real manager against ``tmp_path`` with no multi-user access control.
    """
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    return manager


def _seed_kb(manager, name: str = "kb") -> Path:
    """Create a ready llamaindex KB whose raw/ directory starts empty."""
    kb_dir = manager.base_dir / name
    (kb_dir / "raw").mkdir(parents=True, exist_ok=True)
    manager.config.setdefault("knowledge_bases", {})[name] = {
        "path": name,
        "rag_provider": "llamaindex",
        "status": "ready",
    }
    manager._save_config()
    return kb_dir


def _upload(filename: str, payload: bytes) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", (filename, payload, "application/octet-stream"))]


def _staged_files(raw_dir: Path) -> list[Path]:
    """Files left under ``raw/`` after a request (an empty raw dir is fine)."""
    if not raw_dir.exists():
        return []
    return [path for path in raw_dir.rglob("*") if path.is_file()]


def _kb_entry(manager, name: str = "kb") -> dict:
    config = json.loads((manager.base_dir / "kb_config.json").read_text(encoding="utf-8"))
    return config["knowledge_bases"][name]


class _DispatchRecorder:
    """Async stand-in for the background upload-processing task."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, *args, **kwargs):
        self.calls.append(kwargs)


def _install_dispatch_recorder(monkeypatch) -> _DispatchRecorder:
    recorder = _DispatchRecorder()
    monkeypatch.setattr(knowledge_router_module, "run_upload_processing_task", recorder)
    return recorder


# ---------------------------------------------------------------------------
# 1. Unsupported extension
# ---------------------------------------------------------------------------


def test_upload_rejects_unsupported_extension_with_readable_error(
    monkeypatch, tmp_path: Path
) -> None:
    manager = _real_manager(monkeypatch, tmp_path)
    kb_dir = _seed_kb(manager)
    recorder = _install_dispatch_recorder(monkeypatch)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/kb/upload", files=_upload("script.bat", b"@echo off")
        )

    assert response.status_code == 400
    detail = response.json()["detail"]
    # Readable: names the file, the offending type, and what is allowed.
    assert "script.bat" in detail
    assert ".bat" in detail
    assert "Unsupported file type" in detail
    assert "Allowed types" in detail
    # Nothing staged, nothing dispatched, no status flip.
    assert _staged_files(kb_dir / "raw") == []
    assert recorder.calls == []
    entry = _kb_entry(manager)
    assert entry["status"] == "ready"
    assert not entry.get("progress")


# ---------------------------------------------------------------------------
# 2. Empty files
# ---------------------------------------------------------------------------


def test_upload_entry_accepts_empty_text_file(monkeypatch, tmp_path: Path) -> None:
    """A 0-byte file passes the entry; emptiness is a parsing-stage concern.

    Locks the current contract: the entry bounds type and size, it does not
    inspect content.
    """
    manager = _real_manager(monkeypatch, tmp_path)
    kb_dir = _seed_kb(manager)
    recorder = _install_dispatch_recorder(monkeypatch)

    with TestClient(_build_app()) as client:
        response = client.post("/api/knowledge-bases/kb/upload", files=_upload("empty.txt", b""))

    assert response.status_code == 200
    body = response.json()
    assert body["files"] == ["empty.txt"]
    staged = _staged_files(kb_dir / "raw")
    assert [path.name for path in staged] == ["empty.txt"]
    assert staged[0].stat().st_size == 0
    assert len(recorder.calls) == 1
    assert recorder.calls[0]["uploaded_file_paths"] == [str(kb_dir / "raw" / "empty.txt")]


def test_upload_rejects_empty_zip_archive_with_readable_error(monkeypatch, tmp_path: Path) -> None:
    manager = _real_manager(monkeypatch, tmp_path)
    kb_dir = _seed_kb(manager)
    recorder = _install_dispatch_recorder(monkeypatch)

    with TestClient(_build_app()) as client:
        response = client.post("/api/knowledge-bases/kb/upload", files=_upload("empty.zip", b""))

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "empty.zip" in detail
    assert "not a valid zip archive" in detail
    assert _staged_files(kb_dir / "raw") == []
    assert recorder.calls == []


# ---------------------------------------------------------------------------
# 3. Oversize files
# ---------------------------------------------------------------------------


def test_upload_rejects_oversize_file_before_writing(monkeypatch, tmp_path: Path) -> None:
    manager = _real_manager(monkeypatch, tmp_path)
    kb_dir = _seed_kb(manager)
    recorder = _install_dispatch_recorder(monkeypatch)
    monkeypatch.setattr(DocumentValidator, "MAX_FILE_SIZE", 32)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/kb/upload", files=_upload("big.txt", b"x" * 100)
        )

    assert response.status_code == 400
    detail = response.json()["detail"]
    # Readable: names the original file and states the concrete limit.
    assert "big.txt" in detail
    assert "too large" in detail.lower()
    assert "32" in detail
    assert _staged_files(kb_dir / "raw") == []
    assert recorder.calls == []
    entry = _kb_entry(manager)
    assert entry["status"] == "ready"
    assert not entry.get("progress")


# ---------------------------------------------------------------------------
# 4. Corrupted content: fake suffix
# ---------------------------------------------------------------------------


def test_upload_entry_defers_content_checks_for_fake_pdf(monkeypatch, tmp_path: Path) -> None:
    """A ``.pdf`` whose bytes are plain text is accepted at the entry.

    Locks the current contract: the entry validates the suffix, not the
    content; a payload that no PDF parser can open is rejected later, by the
    parsing stage.
    """
    manager = _real_manager(monkeypatch, tmp_path)
    kb_dir = _seed_kb(manager)
    recorder = _install_dispatch_recorder(monkeypatch)
    payload = b"plain text pretending to be a pdf, not a pdf at all"

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/kb/upload", files=_upload("report.pdf", payload)
        )

    assert response.status_code == 200
    assert response.json()["files"] == ["report.pdf"]
    staged = _staged_files(kb_dir / "raw")
    assert [path.name for path in staged] == ["report.pdf"]
    assert staged[0].read_bytes() == payload
    assert len(recorder.calls) == 1


def test_upload_rejects_fake_zip_content_with_readable_error(monkeypatch, tmp_path: Path) -> None:
    manager = _real_manager(monkeypatch, tmp_path)
    kb_dir = _seed_kb(manager)
    recorder = _install_dispatch_recorder(monkeypatch)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/kb/upload", files=_upload("bundle.zip", b"definitely not a zip")
        )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "bundle.zip" in detail
    assert "not a valid zip archive" in detail
    assert _staged_files(kb_dir / "raw") == []
    assert recorder.calls == []


# ---------------------------------------------------------------------------
# 5. Corrupted content: truncated files
# ---------------------------------------------------------------------------

_MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
    b"xref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n9\n%%EOF\n"
)


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("notes.txt", "hello")
    return buf.getvalue()


def test_upload_entry_defers_content_checks_for_truncated_pdf(monkeypatch, tmp_path: Path) -> None:
    """A truncated PDF is written verbatim; the entry does not sniff content."""
    manager = _real_manager(monkeypatch, tmp_path)
    kb_dir = _seed_kb(manager)
    recorder = _install_dispatch_recorder(monkeypatch)
    payload = _MINIMAL_PDF[: len(_MINIMAL_PDF) // 2]

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/kb/upload", files=_upload("truncated.pdf", payload)
        )

    assert response.status_code == 200
    assert response.json()["files"] == ["truncated.pdf"]
    staged = _staged_files(kb_dir / "raw")
    assert [path.name for path in staged] == ["truncated.pdf"]
    assert staged[0].read_bytes() == payload
    assert len(recorder.calls) == 1


def test_upload_rejects_truncated_zip_with_readable_error(monkeypatch, tmp_path: Path) -> None:
    """A zip cut before its central directory cannot pass archive expansion."""
    manager = _real_manager(monkeypatch, tmp_path)
    kb_dir = _seed_kb(manager)
    recorder = _install_dispatch_recorder(monkeypatch)
    payload = _zip_bytes()[: len(_zip_bytes()) // 2]

    with TestClient(_build_app()) as client:
        response = client.post("/api/knowledge-bases/kb/upload", files=_upload("cut.zip", payload))

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "cut.zip" in detail
    assert "not a valid zip archive" in detail
    assert _staged_files(kb_dir / "raw") == []
    assert recorder.calls == []
