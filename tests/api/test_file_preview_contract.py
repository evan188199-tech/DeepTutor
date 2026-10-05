"""Contract tests for the file-preview router boundary cases.

Covers the router-level behaviors not exercised by
``tests/api/test_file_preview.py``: the Office type whitelist (415),
missing/oversized source files (404/422), converter failure to HTTP status
mapping (422/504/502), non-servable attachment backends (501), source query
whitelist (400), upload validation (422), and the success-path response
headers with a non-printable filename.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import file_preview
from deeptutor.services import office_preview


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(file_preview.router, prefix="/api/file-preview")
    return TestClient(app)


def _stub_resolution(monkeypatch, target: Path, filename: str) -> None:
    monkeypatch.setattr(
        file_preview, "_resolve_authorized_file", lambda _path, _query: (target, filename)
    )
    monkeypatch.setattr(file_preview, "_cache_dir", lambda: target.parent / "cache")


def test_post_upload_rejects_non_office_suffix(tmp_path: Path) -> None:
    response = _client().post(
        "/api/file-preview/pdf",
        files={"file": ("notes.txt", b"plain text", "text/plain")},
    )
    assert response.status_code == 415
    assert response.json()["detail"] == "Unsupported Office file type"


def test_get_source_with_non_office_suffix_returns_415(monkeypatch, tmp_path: Path) -> None:
    plain = tmp_path / "notes.txt"
    plain.write_bytes(b"plain text")
    _stub_resolution(monkeypatch, plain, plain.name)

    response = _client().get("/api/file-preview/pdf", params={"source": "/files/outputs/notes.txt"})
    assert response.status_code == 415
    assert response.json()["detail"] == "Unsupported Office file type"


def test_get_missing_source_file_returns_404(monkeypatch, tmp_path: Path) -> None:
    missing = tmp_path / "gone.docx"
    _stub_resolution(monkeypatch, missing, missing.name)

    response = _client().get("/api/file-preview/pdf", params={"source": "/files/outputs/gone.docx"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Preview source not found"


def test_get_oversized_source_returns_422(monkeypatch, tmp_path: Path) -> None:
    oversized = tmp_path / "huge.docx"
    oversized.write_bytes(b"x" * (office_preview.MAX_OFFICE_BYTES + 1))
    _stub_resolution(monkeypatch, oversized, oversized.name)

    response = _client().get("/api/file-preview/pdf", params={"source": "/files/outputs/huge.docx"})
    assert response.status_code == 422
    assert response.json()["detail"] == "Office file is empty or too large to preview"


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [
        (file_preview.OfficePreviewInvalid("bad input"), 422),
        (file_preview.OfficePreviewTimeout("too slow"), 504),
        (file_preview.OfficePreviewConversionFailed("soffice failed"), 502),
    ],
)
def test_converter_failure_maps_to_http_status(
    monkeypatch, tmp_path: Path, failure: Exception, expected_status: int
) -> None:
    source = tmp_path / "report.docx"
    source.write_bytes(b"office")
    _stub_resolution(monkeypatch, source, source.name)

    async def render(_data: bytes, _filename: str, _cache_dir: Path) -> bytes:
        raise failure

    monkeypatch.setattr(file_preview, "render_office_pdf", render)

    response = _client().get(
        "/api/file-preview/pdf", params={"source": "/files/outputs/report.docx"}
    )
    assert response.status_code == expected_status
    assert response.json()["detail"] == str(failure)


def test_attachment_backend_not_servable_returns_501(monkeypatch, tmp_path: Path) -> None:
    from deeptutor.services import storage

    monkeypatch.setattr(storage, "get_attachment_store", lambda: object())

    response = _client().get(
        "/api/file-preview/pdf",
        params={"source": "/files/attachments/session/attachment/report.docx"},
    )
    assert response.status_code == 501
    assert response.json()["detail"] == "Attachment backend not servable"


@pytest.mark.parametrize(
    "source",
    [
        "/files/outputs/report.docx?bogus=1",
        "/files/outputs/report.docx?resource_library=maybe",
        "/files/outputs/report.docx?resource_library=true",
    ],
)
def test_source_query_whitelist_rejects_unknown_or_misplaced_params(source: str) -> None:
    response = _client().get("/api/file-preview/pdf", params={"source": source})
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid preview source query"


def test_post_without_file_field_returns_validation_error() -> None:
    response = _client().post("/api/file-preview/pdf")
    assert response.status_code == 422


def test_get_success_sanitizes_pdf_name_and_sets_security_headers(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "re\x07port 中文名.docx"
    source.write_bytes(b"office")
    _stub_resolution(monkeypatch, source, source.name)

    async def render(_data: bytes, _filename: str, _cache_dir: Path) -> bytes:
        return b"%PDF-1.7\npreview"

    monkeypatch.setattr(file_preview, "render_office_pdf", render)

    response = _client().get(
        "/api/file-preview/pdf", params={"source": "/files/outputs/report.docx"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    disposition = response.headers["content-disposition"]
    expected_star = f"filename*=UTF-8''{quote('re_port 中文名.pdf', safe='')}"
    assert expected_star in disposition
    assert "\x07" not in disposition
