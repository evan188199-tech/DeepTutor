"""Router tests for the shared bilingual EPUB pair session."""

from __future__ import annotations

import io
from pathlib import Path
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import reading
from deeptutor.services.path_service import PathService

EN_TWO = [
    ("Water", ["Water flows downhill.", "Rivers carve the valley."]),
    ("Stone", ["Stone remembers nothing.", "Quarries keep their silence."]),
]
ZH_TWO = [
    ("水", ["水往低处流。", "河流刻出山谷。"]),
    ("石", ["石头什么都不记得。", "采石场保持沉默。"]),
]


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    app = FastAPI()
    app.include_router(reading.router, prefix="/api/reading")
    with TestClient(app) as test_client:
        yield test_client
    PathService.reset_instance()


def _epub_bytes(*, language: str, chapters: list[tuple[str, list[str]]]) -> bytes:
    items = "".join(
        f"<item id='c{index}' href='c{index}.xhtml' media-type='application/xhtml+xml'/>"
        for index in range(1, len(chapters) + 1)
    )
    spine = "".join(f"<itemref idref='c{index}'/>" for index in range(1, len(chapters) + 1))
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            "<container><rootfiles><rootfile full-path='OPS/book.opf'/></rootfiles></container>",
        )
        archive.writestr(
            "OPS/book.opf",
            "<package xmlns:dc='http://purl.org/dc/elements/1.1/'>"
            "<metadata><dc:identifier>urn:uuid:pair-session-router</dc:identifier>"
            "<dc:title>Router pair book</dc:title>"
            f"<dc:language>{language}</dc:language></metadata>"
            f"<manifest>{items}</manifest><spine>{spine}</spine></package>",
        )
        for index, (title, paragraphs) in enumerate(chapters, start=1):
            body = "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)
            archive.writestr(
                f"OPS/c{index}.xhtml",
                f"<html><head><title>{title}</title></head><body><h1>{title}</h1>{body}</body></html>",
            )
    return stream.getvalue()


def _upload_epub(client: TestClient, name: str, *, language: str, chapters) -> dict:
    response = client.post(
        "/api/reading/materials",
        files={
            "file": (
                name,
                io.BytesIO(_epub_bytes(language=language, chapters=chapters)),
                "application/epub+zip",
            )
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _pair(client: TestClient) -> tuple[str, str]:
    english = _upload_epub(client, "en.epub", language="en", chapters=EN_TWO)
    chinese = _upload_epub(client, "zh.epub", language="zh", chapters=ZH_TWO)
    response = client.post(
        "/api/reading/epub-pairings",
        json={
            "english_material_id": english["material_id"],
            "chinese_material_id": chinese["material_id"],
        },
    )
    assert response.status_code == 200, response.text
    return english["material_id"], chinese["material_id"]


def test_saving_a_position_shares_it_with_the_opposite_edition(client: TestClient) -> None:
    english_id, chinese_id = _pair(client)

    response = client.put(
        f"/api/reading/materials/{english_id}/position",
        json={"locator": 2, "source_anchor": "", "percentage": 0.42},
    )
    assert response.status_code == 200, response.text

    mirrored = client.get(f"/api/reading/materials/{chinese_id}/position")
    assert mirrored.status_code == 200, mirrored.text
    body = mirrored.json()
    assert body["locator"] == 2
    assert body["percentage"] == pytest.approx(0.42)


def test_position_save_without_a_pairing_stays_private(client: TestClient) -> None:
    english_id, _chinese_id = _pair(client)
    lone = _upload_epub(
        client,
        "lone.epub",
        language="en",
        chapters=[("Sand", ["Sand shifts overnight."]), ("Wind", ["Wind forgets everything."])],
    )

    response = client.put(
        f"/api/reading/materials/{lone['material_id']}/position", json={"locator": 1}
    )
    assert response.status_code == 200, response.text
    # The paired Chinese edition keeps its default viewport.
    mirrored = client.get(f"/api/reading/materials/{_chinese_id}/position").json()
    assert mirrored["locator"] == 1
    assert english_id


def test_pair_session_reports_the_opposite_edition(client: TestClient) -> None:
    english_id, chinese_id = _pair(client)

    response = client.get(f"/api/reading/materials/{english_id}/epub-pair-session")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["opposite_material_id"] == chinese_id
    assert body["opposite_language"] == "zh"

    reverse = client.get(f"/api/reading/materials/{chinese_id}/epub-pair-session").json()
    assert reverse["opposite_material_id"] == english_id
    assert reverse["opposite_language"] == "en"

    lone = _upload_epub(
        client, "lone.epub", language="en", chapters=[("Sand", ["Sand shifts overnight."])]
    )
    assert (
        client.get(f"/api/reading/materials/{lone['material_id']}/epub-pair-session").json() is None
    )


def test_pair_alignment_returns_opposite_text_without_a_model(client: TestClient) -> None:
    english_id, _chinese_id = _pair(client)

    response = client.post(
        f"/api/reading/materials/{english_id}/epub-pair-alignment",
        json={"locator": 2, "quote": "Quarries keep their silence."},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "aligned"
    assert body["excerpt"] == "采石场保持沉默。"
    assert body["opposite_locator"] == 2

    degraded = client.post(
        f"/api/reading/materials/{english_id}/epub-pair-alignment",
        json={"locator": 1, "quote": "flows downhill"},
    ).json()
    assert degraded["status"] == "aligned"
    assert degraded["degraded"] is True
    assert degraded["excerpt"] == "水往低处流。"

    missing = client.post(
        f"/api/reading/materials/{english_id}/epub-pair-alignment",
        json={"locator": 1, "quote": "Nothing matches this sentence."},
    ).json()
    assert missing["status"] == "quote_not_found"
    assert missing["excerpt"] == ""
