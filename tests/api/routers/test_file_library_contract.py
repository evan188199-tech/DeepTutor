"""Endpoint-contract and failure-branch coverage for the file library API.

Complements ``tests/api/test_file_library_router.py`` (happy paths and
per-user isolation) with the request-validation, authentication, HEAD
download, and missing-on-disk branches of
``deeptutor/api/routers/file_library.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.services.auth import TokenPayload
from deeptutor.services.storage.file_library import reset_file_library_store

LibraryAppFactory = Callable[..., tuple[TestClient, Path]]

UPLOAD = {"filename": "note.txt", "mime_type": "text/plain"}
FILE_PART = {"file": ("note.txt", b"payload", "text/plain")}


@pytest.fixture
def library_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> LibraryAppFactory:
    """Build a standalone FastAPI app mounting only the file_library router.

    Mirrors the fixture in ``tests/api/test_file_library_router.py``: an
    isolated per-user workspace tree under ``tmp_path``, auth disabled by
    default (``auth_enabled=True`` plus a ``tokens`` map to exercise 401
    branches), and the store singleton cache reset on teardown.
    """
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import file_library
    from deeptutor.multi_user import paths as multi_user_paths

    admin_root = tmp_path / "data"
    monkeypatch.setattr(multi_user_paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(multi_user_paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(multi_user_paths, "_path_services", {})

    def make_app(
        auth_enabled: bool = False,
        tokens: dict[str, TokenPayload | None] | None = None,
    ) -> tuple[TestClient, Path]:
        monkeypatch.setattr(auth_router, "AUTH_ENABLED", auth_enabled)
        if tokens is not None:
            monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
        app = FastAPI()
        app.include_router(file_library.router, prefix="/files/library")
        return TestClient(app), admin_root

    yield make_app
    reset_file_library_store()


def _upload(client: TestClient, filename: str = "note.txt", content: bytes = b"payload") -> str:
    response = client.post(
        "/files/library/",
        data={"filename": filename, "mime_type": "text/plain"},
        files={"file": (filename, content, "text/plain")},
    )
    assert response.status_code == 200, response.json()
    return response.json()["id"]


def _unique_disk_file(admin_root: Path, content: bytes) -> Path:
    """Locate the single stored file holding ``content`` under the admin root."""
    matches = [
        path for path in admin_root.rglob("*") if path.is_file() and path.read_bytes() == content
    ]
    assert len(matches) == 1, f"expected exactly one stored file, found {len(matches)}"
    return matches[0]


# ── list validation bounds ────────────────────────────────────────────────


def test_list_rejects_limit_below_minimum(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    assert client.get("/files/library/?limit=0").status_code == 422


def test_list_rejects_limit_above_maximum(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    assert client.get("/files/library/?limit=201").status_code == 422


def test_list_rejects_negative_offset(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    assert client.get("/files/library/?offset=-1").status_code == 422


def test_list_rejects_non_integer_limit(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    assert client.get("/files/library/?limit=abc").status_code == 422


def test_list_accepts_boundary_limit_and_offset(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    _upload(client)
    response = client.get("/files/library/?limit=200&offset=1")
    assert response.status_code == 200
    assert response.json() == []


# ── search validation bounds ──────────────────────────────────────────────


def test_search_requires_query_param(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    assert client.get("/files/library/search").status_code == 422


def test_search_rejects_empty_query(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    assert client.get("/files/library/search?q=").status_code == 422


def test_search_rejects_over_long_query(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    response = client.get(f"/files/library/search?q={'x' * 201}")
    assert response.status_code == 422


def test_search_accepts_max_length_query(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    _upload(client, filename="needle.txt")
    response = client.get(f"/files/library/search?q={'n' * 199}x")
    assert response.status_code == 200
    assert response.json() == []


# ── upload validation branches ────────────────────────────────────────────


def test_add_without_file_part_returns_422(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    response = client.post("/files/library/", data={"filename": "lonely.txt"})
    assert response.status_code == 422


def test_add_without_filename_field_returns_422(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    response = client.post("/files/library/", files=FILE_PART)
    assert response.status_code == 422


# ── authentication branches ───────────────────────────────────────────────


def test_missing_token_is_unauthorized_when_auth_enabled(
    library_app: LibraryAppFactory,
) -> None:
    client, _ = library_app(auth_enabled=True)
    response = client.get("/files/library/")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_invalid_token_is_unauthorized_when_auth_enabled(
    library_app: LibraryAppFactory,
) -> None:
    client, _ = library_app(auth_enabled=True, tokens={})
    response = client.get("/files/library/", cookies={"dt_token": "bogus"})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_bearer_header_authorizes_when_auth_enabled(library_app: LibraryAppFactory) -> None:
    tokens = {"header-token": TokenPayload(username="alice", role="user", user_id="u1")}
    client, _ = library_app(auth_enabled=True, tokens=tokens)
    response = client.get(
        "/files/library/",
        headers={"Authorization": "Bearer header-token"},
    )
    assert response.status_code == 200
    assert response.json() == []


# ── HEAD /download endpoint ───────────────────────────────────────────────


def test_head_download_existing_file_returns_200(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    file_id = _upload(client)
    response = client.head(f"/files/library/{file_id}/download")
    assert response.status_code == 200
    assert response.content == b""


def test_head_download_deleted_file_returns_404(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    file_id = _upload(client)
    client.delete(f"/files/library/{file_id}")
    assert client.head(f"/files/library/{file_id}/download").status_code == 404


def test_head_download_nonexistent_file_returns_404(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    assert client.head("/files/library/missing-id/download").status_code == 404


def test_head_download_missing_on_disk_returns_404(library_app: LibraryAppFactory) -> None:
    client, admin_root = library_app()
    content = b"head-disk-missing-payload"
    file_id = _upload(client, content=content)
    _unique_disk_file(admin_root, content).unlink()
    assert client.head(f"/files/library/{file_id}/download").status_code == 404


# ── GET /download failure branch and response contract ────────────────────


def test_download_missing_on_disk_returns_404(library_app: LibraryAppFactory) -> None:
    client, admin_root = library_app()
    content = b"get-disk-missing-payload"
    file_id = _upload(client, content=content)
    _unique_disk_file(admin_root, content).unlink()
    assert client.get(f"/files/library/{file_id}/download").status_code == 404


def test_download_sets_guard_and_cache_headers(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    file_id = _upload(client)
    response = client.get(f"/files/library/{file_id}/download")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, max-age=31536000, immutable"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert 'filename="note.txt"' in response.headers["Content-Disposition"]


def test_download_uses_guessed_mime_for_known_extension(
    library_app: LibraryAppFactory,
) -> None:
    client, _ = library_app()
    file_id = _upload(client)
    response = client.get(f"/files/library/{file_id}/download")
    assert response.headers["Content-Type"].startswith("text/plain")


def test_download_falls_back_to_octet_stream_for_unknown_extension(
    library_app: LibraryAppFactory,
) -> None:
    client, _ = library_app()
    file_id = _upload(client, filename="blob.unknownext")
    response = client.get(f"/files/library/{file_id}/download")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/octet-stream"
