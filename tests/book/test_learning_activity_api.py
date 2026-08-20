from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import book as book_router
from deeptutor.book.models import Progress


class _FakeEngine:
    def __init__(self, result: Progress | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.kwargs = None

    def record_learning_activity(self, **kwargs) -> Progress | None:
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return self.result


def _client(monkeypatch, engine: _FakeEngine) -> TestClient:
    monkeypatch.setattr(book_router, "get_book_engine", lambda: engine)
    app = FastAPI()
    app.include_router(book_router.router)
    return TestClient(app)


def _payload(**overrides):
    body = {
        "book_id": "bk",
        "page_id": "pg",
        "block_id": "blk",
        "schema_version": 1,
        "event_id": "event",
        "objective_ids": [],
        "activity_type": "parameter_change",
        "result": "completed",
        "payload": {"parameter": "slope"},
        "occurred_at": 1,
    }
    body.update(overrides)
    return body


def test_learning_activity_api_returns_progress(monkeypatch):
    progress = Progress(book_id="bk")
    engine = _FakeEngine(progress)
    client = _client(monkeypatch, engine)

    response = client.post("/books/learning-activity", json=_payload(occurred_at=0))

    assert response.status_code == 200
    assert response.json()["progress"]["book_id"] == "bk"
    assert engine.kwargs["occurred_at"] == 0


def test_learning_activity_api_maps_domain_errors_to_400(monkeypatch):
    client = _client(monkeypatch, _FakeEngine(error=ValueError("unknown objective id")))

    response = client.post("/books/learning-activity", json=_payload())

    assert response.status_code == 400
    assert response.json()["detail"] == "unknown objective id"


def test_learning_activity_api_maps_missing_blocks_to_404(monkeypatch):
    client = _client(monkeypatch, _FakeEngine(None))

    response = client.post("/books/learning-activity", json=_payload())

    assert response.status_code == 404


def test_learning_activity_api_rejects_oversized_payloads(monkeypatch):
    client = _client(monkeypatch, _FakeEngine(Progress(book_id="bk")))
    body = _payload(payload={"blob": "x" * 9000})

    response = client.post("/books/learning-activity", json=body)

    assert response.status_code == 400
    assert response.json()["detail"] == "Learning activity payload is too large"


def test_learning_activity_api_measures_payloads_in_utf8_bytes(monkeypatch):
    client = _client(monkeypatch, _FakeEngine(Progress(book_id="bk")))
    body = _payload(payload={"blob": "课" * 3000})

    response = client.post("/books/learning-activity", json=body)

    assert response.status_code == 400
    assert response.json()["detail"] == "Learning activity payload is too large"
