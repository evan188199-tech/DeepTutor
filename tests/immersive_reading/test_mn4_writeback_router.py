"""HTTP contract tests for MarginNote 4 writeback review."""

from __future__ import annotations

import pytest

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient


@pytest.fixture
def client(reading_service, monkeypatch) -> TestClient:
    import deeptutor.api.routers.immersive_reading as router_module

    router_module._search_jobs.clear()
    monkeypatch.setattr(router_module, "get_immersive_reading_service", lambda: reading_service)
    monkeypatch.setattr(reading_service, "fast_index_needs_build", lambda _document_id: False)
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1/immersive-reading")
    return TestClient(app)


@pytest.mark.asyncio
async def test_translate_queues_mn4_writeback(client, reading_service, monkeypatch) -> None:
    async def translate(text: str, target_language: str) -> str:
        return "translated"

    monkeypatch.setattr(reading_service, "translate", translate)

    response = client.post(
        "/api/v1/immersive-reading/translate",
        json={
            "text": "The bright harbour slept.",
            "target_language": "Chinese",
            "document_id": "mn4-document",
            "source_object_id": "section-1",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"translation": "translated"}
    items = reading_service.list_mn4_writebacks()
    assert len(items) == 1
    assert items[0].source_type == "translation"
    assert items[0].source_object_id == "section-1"


def test_mn4_writeback_routes_review_and_apply(client, reading_service) -> None:
    item = reading_service.create_mn4_writeback(
        source_type="word",
        source_object_id="word-1",
        content_hash="a" * 64,
        idempotency_key="word:word-1:" + "a" * 64,
        model="test-model",
    )

    listed = client.get("/api/v1/immersive-reading/mn4/writebacks")
    assert listed.status_code == 200, listed.text
    assert listed.json()["writebacks"][0]["id"] == item.id

    approved = client.post(
        "/api/v1/immersive-reading/mn4/writebacks/approve",
        json={"writeback_ids": [item.id]},
    )
    rejected = client.post(
        "/api/v1/immersive-reading/mn4/writebacks/reject",
        json={"writeback_ids": [item.id]},
    )
    pulled = client.post("/api/v1/immersive-reading/mn4/writebacks/pull")

    assert approved.status_code == 200, approved.text
    assert approved.json() == {"approved_count": 1}
    assert rejected.status_code == 200, rejected.text
    assert rejected.json() == {"rejected_count": 0}
    assert pulled.status_code == 200, pulled.text
    assert [entry["id"] for entry in pulled.json()["pending_items"]] == [item.id]

    receipt = {
        "writeback_id": item.id,
        "remote_object_id": "remote-object",
        "content_hash": item.content_hash,
        "written_at": 123.0,
    }
    submitted = client.post(
        "/api/v1/immersive-reading/mn4/writebacks/receipt",
        json={"receipts": [receipt]},
    )

    assert submitted.status_code == 200, submitted.text
    assert submitted.json() == {"processed_count": 1}
    assert reading_service.list_mn4_writebacks()[0].status == "applied"


def test_mn4_receipt_body_is_validated(client) -> None:
    response = client.post(
        "/api/v1/immersive-reading/mn4/writebacks/receipt",
        json={"receipts": [{"writeback_id": "missing"}]},
    )

    assert response.status_code == 422
