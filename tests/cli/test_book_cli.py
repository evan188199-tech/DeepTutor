"""CLI tests for the ``deeptutor book`` command group (list/health/refresh-fingerprints).

All engine access is faked by monkeypatching ``deeptutor.book.get_book_engine``
—the lazy import inside each command resolves the attribute at call time—
so every test stays offline and fast.
"""

from __future__ import annotations

import json
from typing import Any

from typer.testing import CliRunner

from deeptutor.book.models import Book, BookStatus
from deeptutor_cli.main import app

runner = CliRunner()


class FakeBookEngine:
    """Offline stand-in for ``BookEngine`` covering the three CLI calls."""

    def __init__(
        self,
        books: list[Book] | None = None,
        drift_report: dict[str, Any] | None = None,
        log_report: dict[str, Any] | None = None,
        refresh_result: dict[str, Any] | None = None,
    ) -> None:
        self.books = books if books is not None else []
        self.drift_report = drift_report if drift_report is not None else {}
        self.log_report = log_report if log_report is not None else {}
        self.refresh_result = refresh_result
        self.calls: list[tuple[str, str | None]] = []

    def list_books(self) -> list[Book]:
        self.calls.append(("list_books", None))
        return self.books

    def kb_drift_report(self, book_id: str) -> dict[str, Any]:
        self.calls.append(("kb_drift_report", book_id))
        return self.drift_report

    def log_health(self, book_id: str) -> dict[str, Any]:
        self.calls.append(("log_health", book_id))
        return self.log_report

    def refresh_kb_fingerprints(self, book_id: str) -> dict[str, Any] | None:
        self.calls.append(("refresh_kb_fingerprints", book_id))
        return self.refresh_result


def _patch_engine(monkeypatch, engine: FakeBookEngine) -> None:
    monkeypatch.setattr("deeptutor.book.get_book_engine", lambda: engine)


def test_book_list_empty_library_prints_hint(monkeypatch) -> None:
    """An empty workspace prints the "No books yet." hint and exits cleanly."""
    engine = FakeBookEngine(books=[])
    _patch_engine(monkeypatch, engine)

    result = runner.invoke(app, ["book", "list"])

    assert result.exit_code == 0, result.output
    assert "No books yet." in result.output
    assert engine.calls == [("list_books", None)]


def test_book_list_renders_stale_annotation_and_untitled(monkeypatch) -> None:
    """Each book line shows title/id/status; stale counts and empty titles render."""
    stale_book = Book(
        id="bk-stale",
        title="Modern Algebra",
        status=BookStatus.READY,
        stale_page_ids=["pg-1", "pg-2"],
    )
    clean_book = Book(id="bk-clean", title="", status=BookStatus.DRAFT)
    engine = FakeBookEngine(books=[stale_book, clean_book])
    _patch_engine(monkeypatch, engine)

    result = runner.invoke(app, ["book", "list"])

    assert result.exit_code == 0, result.output
    lines = {line for line in result.output.splitlines() if line.strip()}
    stale_line = next(line for line in lines if "bk-stale" in line)
    clean_line = next(line for line in lines if "bk-clean" in line)
    assert "Modern Algebra" in stale_line
    assert "ready" in stale_line
    assert "(2 stale)" in stale_line
    assert "(untitled)" in clean_line
    assert "draft" in clean_line
    assert "stale" not in clean_line


def test_book_health_prints_drift_and_log_json(monkeypatch) -> None:
    """health prints a JSON object combining kb_drift and log_health reports."""
    engine = FakeBookEngine(
        drift_report={"drifted": False, "stale_pages": 0},
        log_report={"exists": True, "entries": 3},
    )
    _patch_engine(monkeypatch, engine)

    result = runner.invoke(app, ["book", "health", "bk-1"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {
        "kb_drift": {"drifted": False, "stale_pages": 0},
        "log_health": {"exists": True, "entries": 3},
    }
    assert engine.calls == [
        ("kb_drift_report", "bk-1"),
        ("log_health", "bk-1"),
    ]


def test_book_health_requires_book_id(monkeypatch) -> None:
    """health without a book id is a usage error, not an engine call."""
    engine = FakeBookEngine()
    _patch_engine(monkeypatch, engine)

    result = runner.invoke(app, ["book", "health"])

    assert result.exit_code == 2
    assert engine.calls == []


def test_book_refresh_fingerprints_missing_book_exits_1(monkeypatch) -> None:
    """A None refresh result means "book not found" and exits with code 1."""
    engine = FakeBookEngine(refresh_result=None)
    _patch_engine(monkeypatch, engine)

    result = runner.invoke(app, ["book", "refresh-fingerprints", "bk-missing"])

    assert result.exit_code == 1, result.output
    assert "not found" in result.output
    assert engine.calls == [("refresh_kb_fingerprints", "bk-missing")]


def test_book_refresh_fingerprints_prints_result_json(monkeypatch) -> None:
    """A successful refresh prints the engine result as JSON."""
    engine = FakeBookEngine(refresh_result={"book_id": "bk-1", "cleared": 2})
    _patch_engine(monkeypatch, engine)

    result = runner.invoke(app, ["book", "refresh-fingerprints", "bk-1"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {"book_id": "bk-1", "cleared": 2}
    assert engine.calls == [("refresh_kb_fingerprints", "bk-1")]
