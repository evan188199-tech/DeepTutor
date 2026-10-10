"""SSE error contract for the Co-Writer react-edit stream.

Terminal ``event: error`` frames must carry only neutral i18n copy: exception
text (provider payloads, internal paths, request ids) belongs in the server
log, never in the stream. The two deliberate 400 rejections are localized
through the backend i18n catalog (``t()``) in both supported languages.
"""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

import deeptutor.services.config as _dt_config

_dt_config.load_config_with_main = lambda *_a, **_k: {
    "paths": {},
    "logging": {},
    "system": {"language": "en"},
}

from deeptutor.api.routers import co_writer as co_writer_router
from deeptutor.co_writer.storage import CoWriterStorage
from deeptutor.services.i18n import t
from tests.api.routers.test_co_writer_contract import _StubPathService

_INSTRUCTION_REQUIRED = {
    "en": "Provide an edit instruction, or choose shorten / expand / rewrite mode.",
    "zh": "请输入编辑要求，或选择 shorten / expand / rewrite 模式。",
}
_SELECTION_REQUIRED = {
    "en": "Please select a text passage first.",
    "zh": "请先选中一段文本。",
}


def _sse_events(text: str) -> dict[str, list[dict]]:
    events: dict[str, list[dict]] = {}
    for block in text.strip().split("\n\n"):
        name = None
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                assert name is not None, f"data line outside an event: {line!r}"
                events.setdefault(name, []).append(json.loads(line[len("data:") :].strip()))
    return events


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(
        co_writer_router,
        "get_co_writer_storage",
        lambda: CoWriterStorage(path_service=_StubPathService(tmp_path)),
    )
    app = FastAPI()
    app.include_router(co_writer_router.router)
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("language", ["en", "zh"])
def test_stream_error_event_is_neutral_on_unexpected_failure(client, monkeypatch, caplog, language):
    monkeypatch.setattr(co_writer_router, "_current_language", lambda: language)
    secret = "provider call to https://internal.example/v1 failed (request 7f3a)"

    async def _explode(*args, **kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(co_writer_router, "_run_react_edit", _explode)
    with caplog.at_level(logging.ERROR, logger="deeptutor.api.routers.co_writer"):
        response = client.post(
            "/documents/actions/edit-react/stream",
            json={"selected_text": "abc", "instruction": "polish", "mode": "rewrite"},
        )
    assert response.status_code == 200, response.text
    events = _sse_events(response.text)
    assert set(events) == {"error"}
    payload = events["error"][0]
    assert payload["detail"] == t("co_writer.edit_failed", language=language)
    assert payload["code"] == "co_writer_internal_error"
    assert secret not in response.text
    assert "internal.example" not in response.text
    assert secret in caplog.text


@pytest.mark.parametrize("language", ["en", "zh"])
def test_stream_error_event_is_neutral_for_http_exception_details(client, monkeypatch, language):
    monkeypatch.setattr(co_writer_router, "_current_language", lambda: language)
    rejected = "raw upstream rejection: api-key sk-live-abcdef"

    async def _rejected(*args, **kwargs):
        raise HTTPException(status_code=400, detail=rejected)

    monkeypatch.setattr(co_writer_router, "_run_react_edit", _rejected)
    response = client.post(
        "/documents/actions/edit-react/stream",
        json={"selected_text": "abc", "instruction": "polish", "mode": "rewrite"},
    )
    assert response.status_code == 200, response.text
    events = _sse_events(response.text)
    assert set(events) == {"error"}
    payload = events["error"][0]
    assert payload["detail"] == t("co_writer.edit_failed", language=language)
    assert payload["code"] == "co_writer_bad_request"
    assert rejected not in response.text
    assert "sk-live-abcdef" not in response.text


@pytest.mark.parametrize("language", ["en", "zh"])
def test_react_edit_bad_request_details_are_localized_via_i18n(client, monkeypatch, language):
    monkeypatch.setattr(co_writer_router, "_current_language", lambda: language)

    missing_instruction = client.post(
        "/documents/actions/edit-react",
        json={"selected_text": "abc", "mode": "none", "instruction": "   "},
    )
    assert missing_instruction.status_code == 400
    detail = missing_instruction.json()["detail"]
    assert detail == _INSTRUCTION_REQUIRED[language]
    assert detail == t("co_writer.edit_instruction_required", language=language)

    blank_selection = client.post(
        "/documents/actions/edit-react",
        json={"selected_text": "\n  \n", "instruction": "polish"},
    )
    assert blank_selection.status_code == 400
    detail = blank_selection.json()["detail"]
    assert detail == _SELECTION_REQUIRED[language]
    assert detail == t("co_writer.selection_required", language=language)


@pytest.mark.parametrize("language", ["en", "zh"])
def test_stream_endpoint_prevalidation_uses_the_same_localized_detail(
    client, monkeypatch, language
):
    monkeypatch.setattr(co_writer_router, "_current_language", lambda: language)
    response = client.post(
        "/documents/actions/edit-react/stream",
        json={"selected_text": "abc", "mode": "none", "instruction": ""},
    )
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/json")
    assert not response.text.startswith("event:")
    assert response.json()["detail"] == t("co_writer.edit_instruction_required", language=language)
