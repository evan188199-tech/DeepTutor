"""Contract tests for the chat attachment download router.

Covers ``GET /files/attachments/{session_id}/{attachment_id}/{filename}``:
success with preview headers, unknown attachment, filename mismatch, the
non-local-backend guard, and the auth gate applied by ``main.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import attachments as attachments_router
from deeptutor.api.routers import auth as auth_router
from deeptutor.services.auth import TokenPayload
from deeptutor.services.storage.attachment_store import LocalDiskAttachmentStore


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalDiskAttachmentStore:
    store = LocalDiskAttachmentStore(root=tmp_path / "attachments")
    session_dir = store.root / "sess-1"
    session_dir.mkdir(parents=True)
    (session_dir / "att-1_report.txt").write_text("attachment body", encoding="utf-8")
    monkeypatch.setattr(attachments_router, "get_attachment_store", lambda: store)
    return store


def _make_app(*, auth_enabled: bool = False, auth_guard: bool = False) -> TestClient:
    app = FastAPI()
    dependencies = [Depends(auth_router.require_learning_surface)] if auth_guard else None
    app.include_router(
        attachments_router.router, prefix="/files/attachments", dependencies=dependencies
    )
    return TestClient(app)


def test_download_serves_stored_file_with_preview_headers(
    env: LocalDiskAttachmentStore,
) -> None:
    client = _make_app()
    res = client.get("/files/attachments/sess-1/att-1/report.txt")
    assert res.status_code == 200
    assert res.text == "attachment body"
    assert res.headers["content-type"].startswith("text/plain")
    assert res.headers["cache-control"] == "private, max-age=0, must-revalidate"
    disposition = res.headers["content-disposition"]
    assert disposition.startswith("inline;")
    assert 'filename="att-1_report.txt"' in disposition
    assert "filename*=UTF-8''att-1_report.txt" in disposition


def test_download_unknown_attachment_returns_404(env: LocalDiskAttachmentStore) -> None:
    client = _make_app()
    res = client.get("/files/attachments/sess-1/att-missing/report.txt")
    assert res.status_code == 404


def test_download_filename_mismatch_returns_404(env: LocalDiskAttachmentStore) -> None:
    client = _make_app()
    res = client.get("/files/attachments/sess-1/att-1/other.txt")
    assert res.status_code == 404


def test_non_local_backend_answers_501(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(attachments_router, "get_attachment_store", lambda: object())
    client = _make_app()
    res = client.get("/files/attachments/sess-1/att-1/report.txt")
    assert res.status_code == 501


def test_auth_gate_blocks_anonymous_and_accepts_valid_token(
    env: LocalDiskAttachmentStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    tokens: dict[str, TokenPayload | None] = {
        "tok-ok": TokenPayload(username="alice", role="admin", user_id="u-1")
    }
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    client = _make_app(auth_guard=True)

    anonymous = client.get("/files/attachments/sess-1/att-1/report.txt")
    assert anonymous.status_code == 401

    rejected = client.get(
        "/files/attachments/sess-1/att-1/report.txt",
        headers={"Authorization": "Bearer tok-bad"},
    )
    assert rejected.status_code == 401

    ok = client.get(
        "/files/attachments/sess-1/att-1/report.txt",
        headers={"Authorization": "Bearer tok-ok"},
    )
    assert ok.status_code == 200
    assert ok.text == "attachment body"
