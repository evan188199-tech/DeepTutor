"""Contract tests for the chat attachment download endpoint.

Covers ``deeptutor.api.routers.attachments.get_attachment``: serving a
previously uploaded attachment with inline preview headers, the 404 branch
for unknown files, and the 501 guard against non-local backends.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import unquote, urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import attachments
from deeptutor.services.storage import LocalDiskAttachmentStore

PREFIX = "/files/attachments"


def _store(tmp_path: Path) -> LocalDiskAttachmentStore:
    return LocalDiskAttachmentStore(root=tmp_path / "attachments")


def _put(store: LocalDiskAttachmentStore, **kwargs) -> str:
    return asyncio.run(store.put(**kwargs))


def _client(monkeypatch, store) -> TestClient:
    monkeypatch.setattr(attachments, "get_attachment_store", lambda: store)
    app = FastAPI()
    app.include_router(attachments.router, prefix=PREFIX)
    return TestClient(app)


def test_serves_stored_attachment_with_inline_preview_headers(monkeypatch, tmp_path: Path) -> None:
    store = _store(tmp_path)
    url = _put(
        store,
        session_id="sess-1",
        attachment_id="att-1",
        filename="report.pdf",
        data=b"%PDF-1.7\nattachment",
        mime_type="application/pdf",
    )
    client = _client(monkeypatch, store)

    response = client.get(urlsplit(url).path)

    assert response.status_code == 200
    assert response.content == b"%PDF-1.7\nattachment"
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")
    # The header echoes the stored name ({attachment_id}_{filename}).
    assert 'filename="att-1_report.pdf"' in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "private, max-age=0, must-revalidate"


def test_unicode_filename_survives_url_round_trip(monkeypatch, tmp_path: Path) -> None:
    store = _store(tmp_path)
    url = _put(
        store,
        session_id="sess-1",
        attachment_id="att-2",
        filename="报告.pdf",
        data=b"%PDF-1.7\nunicode",
    )
    client = _client(monkeypatch, store)

    response = client.get(urlsplit(url).path)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    disposition = response.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition
    encoded = disposition.split("filename*=UTF-8''", 1)[1]
    assert unquote(encoded) == "att-2_报告.pdf"


def test_unknown_attachment_returns_404(monkeypatch, tmp_path: Path) -> None:
    store = _store(tmp_path)
    client = _client(monkeypatch, store)

    response = client.get(f"{PREFIX}/sess-1/att-1/missing.pdf")

    assert response.status_code == 404
    assert response.json()["detail"] == "Attachment not found"


def test_mismatched_attachment_id_returns_404(monkeypatch, tmp_path: Path) -> None:
    store = _store(tmp_path)
    _put(store, session_id="sess-1", attachment_id="att-1", filename="a.pdf", data=b"a")
    client = _client(monkeypatch, store)

    response = client.get(f"{PREFIX}/sess-1/att-other/a.pdf")

    assert response.status_code == 404
    assert response.json()["detail"] == "Attachment not found"


def test_non_local_backend_returns_501(monkeypatch) -> None:
    class RemoteStubStore:
        async def put(self, **_kwargs) -> str:  # pragma: no cover - must not be reached
            raise AssertionError("router must not write via a non-local backend")

        async def delete_session(self, _session_id: str) -> None:  # pragma: no cover
            raise AssertionError("not used")

        async def delete_attachment(  # pragma: no cover
            self, _session_id: str, _attachment_id: str
        ) -> None:
            raise AssertionError("not used")

        def resolve_path(self, **_kwargs):
            return None

    client = _client(monkeypatch, RemoteStubStore())

    response = client.get(f"{PREFIX}/sess-1/att-1/report.pdf")

    assert response.status_code == 501
    assert response.json()["detail"] == "Attachment backend not servable"


def test_unknown_extension_falls_back_to_octet_stream(monkeypatch, tmp_path: Path) -> None:
    store = _store(tmp_path)
    url = _put(
        store,
        session_id="sess-1",
        attachment_id="att-3",
        filename="blob.unknownext",
        data=b"raw-bytes",
    )
    client = _client(monkeypatch, store)

    response = client.get(urlsplit(url).path)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
