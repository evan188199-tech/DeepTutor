"""The not-found clusters answer with the structured error envelope.

The C003/C007/C008 not-found clusters of the detail-code inventory
(``evidence/scan-detail-code-envelope-20261011``) raised plain-string 404
details the frontend could only match as a whole string. They now speak the
``{"code", "message"}`` envelope ``book.py`` already used for
``book_paused``: the message text stays byte-identical (string matching keeps
working) and ``code`` is the machine-readable key. The inventory's
sessions.py rows are excluded (``excluded_subset=AGEN-1364``) and the
partners.py rows are covered by the partners full-router envelope branch, so
both stay out of this file's scope.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient

book_router = importlib.import_module("deeptutor.api.routers.book")
courses_router = importlib.import_module("deeptutor.api.routers.courses")
mastery_router = importlib.import_module("deeptutor.api.routers.mastery_path")
question_notebook_router = importlib.import_module("deeptutor.api.routers.question_notebook")

BOOK_NOT_FOUND = {"code": "book_not_found", "message": "Book not found"}
COURSE_NOT_FOUND = {"code": "course_not_found", "message": "Course not found"}
MASTERY_SESSION_NOT_FOUND = {
    "code": "mastery_session_not_found",
    "message": "Session not found",
}


def test_no_cluster_raise_site_still_answers_with_a_bare_string() -> None:
    """Every raise site of the three clusters carries the envelope."""
    cluster_messages = {
        book_router: "Book not found",
        courses_router: "Course not found",
        mastery_router: "Session not found",
        question_notebook_router: "Course not found",
    }
    for module, message in cluster_messages.items():
        tree = ast.parse(Path(module.__file__).read_text())
        bare = [
            kw.value.value
            for call in ast.walk(tree)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "HTTPException"
            for kw in call.keywords
            if kw.arg == "detail"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value == message
        ]
        assert not bare, f"{module.__name__} still raises a bare {message!r} detail"


def _book_client(tmp_path, monkeypatch) -> TestClient:
    import deeptutor.book.storage as storage_module
    from deeptutor.services.path_service import PathService

    class _StubBookEngine:
        def __init__(self, storage) -> None:
            self.storage = storage

        def load_book(self, book_id: str):
            return self.storage.load_book(book_id)

        def load_page(self, book_id: str, page_id: str):
            return self.storage.load_page(book_id, page_id)

        def load_spine(self, book_id: str):
            return self.storage.load_spine(book_id)

    service = PathService(workspace_root=tmp_path / "data")
    monkeypatch.setattr(storage_module, "get_path_service", lambda: service)
    storage_module._storages.clear()
    storage = storage_module.get_book_storage()
    monkeypatch.setattr(book_router, "get_book_engine", lambda: _StubBookEngine(storage))

    app = FastAPI()
    app.include_router(book_router.router, prefix="/api")
    return TestClient(app)


def test_book_cluster_unknown_id_answers_with_code_and_404(tmp_path, monkeypatch) -> None:
    client = _book_client(tmp_path, monkeypatch)

    missing = client.get("/api/books/bk_missing_cluster")

    assert missing.status_code == 404
    assert missing.json()["detail"] == BOOK_NOT_FOUND


def test_book_cluster_delete_unknown_id_answers_with_code_and_404(
    tmp_path, monkeypatch
) -> None:
    client = _book_client(tmp_path, monkeypatch)

    deleted = client.delete("/api/books/bk_missing_cluster")

    assert deleted.status_code == 404
    assert deleted.json()["detail"] == BOOK_NOT_FOUND


def _courses_client(tmp_path, monkeypatch) -> TestClient:
    from deeptutor.services.courses import CourseService

    service = CourseService(root=tmp_path / "courses")
    monkeypatch.setattr(courses_router, "get_course_service", lambda: service)

    app = FastAPI()
    app.include_router(courses_router.router, prefix="/api/courses")
    return TestClient(app)


def test_course_cluster_patch_unknown_course_answers_with_code_and_404(
    tmp_path, monkeypatch
) -> None:
    client = _courses_client(tmp_path, monkeypatch)

    patched = client.patch("/api/courses/course-missing", json={"name": "Renamed"})

    assert patched.status_code == 404
    assert patched.json()["detail"] == COURSE_NOT_FOUND


def test_course_cluster_delete_unknown_course_answers_with_code_and_404(
    tmp_path, monkeypatch
) -> None:
    client = _courses_client(tmp_path, monkeypatch)

    deleted = client.delete("/api/courses/course-missing")

    assert deleted.status_code == 404
    assert deleted.json()["detail"] == COURSE_NOT_FOUND


def test_mastery_cluster_unknown_session_answers_with_code_and_404(
    tmp_path, monkeypatch
) -> None:
    from deeptutor.services import session as session_service
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore

    class _EmptyProgressStore:
        def load(self, path_id):
            return None

    monkeypatch.setattr(mastery_router, "LearningStore", lambda: _EmptyProgressStore())
    store = SQLiteSessionStore(tmp_path / "history.db")
    monkeypatch.setattr(session_service, "get_session_store", lambda: store)

    app = FastAPI()
    app.include_router(mastery_router.router, prefix="/api/mastery-paths")
    client = TestClient(app)

    response = client.put(
        "/api/mastery-paths/topics/path-1/sessions/missing/mode",
        json={"mode": "outline"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == MASTERY_SESSION_NOT_FOUND
