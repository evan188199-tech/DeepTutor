"""Router contract coverage for the Immersive Reading extensions transport.

The extension action pipeline itself is covered by ``tests/reading/``; this
suite pins the HTTP contract around it: the extension listing, the
material/extension authorization gates, unknown-resource 404s, payload
validation 4xx responses, and the visibility of downstream failures (a failed
unit read or a failed assessment write must surface as a response, never as a
silent success).
"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient

reading_extensions = importlib.import_module("deeptutor.api.routers.reading_extensions")

from deeptutor.reading.extensions import (
    ReadingAction,
    ReadingExtensionManifest,
    ReadingExtensionRegistry,
    ReadingExtensionResult,
)
from deeptutor.services.path_service import PathService
from deeptutor.services.session.sqlite_store import SQLiteSessionStore

MATERIAL_ID = "m-atlas"
LOCATOR = 4

UNASSIGNED_MATERIAL_MESSAGE = "This reading material is not assigned to this learning account."
NOT_ALLOWED_MESSAGE = "This reading extension is not allowed."


class _StubManifest:
    title = "Test Material"


class _StubReadingStore:
    def __init__(self, *, unit_error: Exception | None = None) -> None:
        self._unit_error = unit_error

    def manifest(self, material_id: str) -> Any:
        return _StubManifest()

    def unit_text(self, material_id: str, locator: int) -> str:
        if self._unit_error is not None:
            raise self._unit_error
        return "Visible passage."

    def position(self, material_id: str) -> Any:
        return SimpleNamespace(locator=LOCATOR, source_anchor="")


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home"))
    PathService.reset_instance()
    yield
    PathService.reset_instance()


def _extension(
    run_action=None,
    *,
    extension_id: str = "sample",
    actions: tuple[str, ...] = ("open",),
    result_types: tuple[str, ...] = ("card",),
) -> SimpleNamespace:
    return SimpleNamespace(
        manifest=ReadingExtensionManifest(
            id=extension_id,
            version="1.0.0",
            name="Sample",
            actions=[
                ReadingAction(
                    id=action_id,
                    label=action_id.title(),
                    requires=[],
                )
                for action_id in actions
            ],
            result_types=list(result_types),
        ),
        run_action=run_action or (lambda *_: ReadingExtensionResult(type="card")),
    )


def _registry(*extensions: SimpleNamespace) -> ReadingExtensionRegistry:
    return ReadingExtensionRegistry(list(extensions))


def _client(monkeypatch: pytest.MonkeyPatch, registry: ReadingExtensionRegistry) -> TestClient:
    monkeypatch.setattr(reading_extensions, "get_reading_extension_registry", lambda: registry)
    app = FastAPI()
    app.include_router(reading_extensions.router, prefix="/api/reading")
    return TestClient(app)


def _store_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SQLiteSessionStore:
    instance = SQLiteSessionStore(db_path=tmp_path / "reading-extensions-contract.db")
    monkeypatch.setattr(
        "deeptutor.services.session.get_sqlite_session_store",
        lambda: instance,
    )
    monkeypatch.setattr(
        reading_extensions,
        "assert_learning_material",
        lambda material_id: None,
    )
    monkeypatch.setattr(
        reading_extensions,
        "ReadingStore",
        _StubReadingStore,
    )
    return instance


def _quiz_questions() -> list[dict]:
    return [
        {
            "id": "q_1",
            "prompt": "Which ocean?",
            "choices": ["Pacific", "Atlantic"],
            "correct_choice_index": 1,
        },
    ]


def _answers(*pairs: tuple[str, int]) -> list[dict]:
    return [{"question_id": qid, "selected_index": index} for qid, index in pairs]


# ---------------------------------------------------------------------------
# GET /extensions — listing contract
# ---------------------------------------------------------------------------


def test_list_extensions_returns_every_manifest_without_policy(monkeypatch):
    registry = _registry(
        _extension(extension_id="quiz"),
        _extension(extension_id="vocabulary"),
    )
    monkeypatch.setattr(reading_extensions, "allowed_reading_extensions", lambda: None)

    response = _client(monkeypatch, registry).get("/api/reading/extensions")

    assert response.status_code == 200, response.text
    ids = [row["id"] for row in response.json()]
    assert ids == ["quiz", "vocabulary"]
    assert all(row["version"] == "1.0.0" for row in response.json())


def test_list_extensions_filters_to_learner_allowlist(monkeypatch):
    registry = _registry(
        _extension(extension_id="quiz"),
        _extension(extension_id="vocabulary"),
    )
    monkeypatch.setattr(reading_extensions, "allowed_reading_extensions", lambda: {"quiz"})

    response = _client(monkeypatch, registry).get("/api/reading/extensions")

    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()] == ["quiz"]


# ---------------------------------------------------------------------------
# Material authorization gates (403)
# ---------------------------------------------------------------------------


def _deny_material(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        reading_extensions,
        "assert_learning_material",
        lambda material_id: (_ for _ in ()).throw(PermissionError(UNASSIGNED_MATERIAL_MESSAGE)),
    )


def test_action_rejects_unassigned_material(monkeypatch):
    def run(*_args):
        raise AssertionError("unassigned material must not reach the extension")

    registry = _registry(_extension(run))
    _deny_material(monkeypatch)

    response = _client(monkeypatch, registry).post(
        f"/api/reading/materials/{MATERIAL_ID}/extensions/sample/actions/open",
        json={"locator": LOCATOR},
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == UNASSIGNED_MATERIAL_MESSAGE


def test_read_aloud_rejects_unassigned_material(monkeypatch):
    async def synthesize(*_args):
        raise AssertionError("unassigned material must not reach the speech provider")

    monkeypatch.setattr(reading_extensions, "synthesize_speech", synthesize)
    registry = _registry(_extension(extension_id="read_aloud"))
    _deny_material(monkeypatch)

    response = _client(monkeypatch, registry).post(
        f"/api/reading/materials/{MATERIAL_ID}/read-aloud",
        json={"locator": LOCATOR},
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == UNASSIGNED_MATERIAL_MESSAGE


def test_quiz_answers_reject_unassigned_material(monkeypatch, tmp_path):
    _store_fixture(tmp_path, monkeypatch)
    _deny_material(monkeypatch)

    app = FastAPI()
    app.include_router(reading_extensions.router, prefix="/api/reading")
    response = TestClient(app).post(
        f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers",
        json={
            "locator": LOCATOR,
            "answers": _answers(("q_1", 1)),
        },
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == UNASSIGNED_MATERIAL_MESSAGE


def test_action_rejects_extension_outside_allowlist(monkeypatch):
    registry = _registry(_extension())
    monkeypatch.setattr(reading_extensions, "allowed_reading_extensions", lambda: {"quiz"})

    response = _client(monkeypatch, registry).post(
        f"/api/reading/materials/{MATERIAL_ID}/extensions/sample/actions/open",
        json={"locator": LOCATOR},
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == NOT_ALLOWED_MESSAGE


def test_quiz_answers_reject_quiz_outside_allowlist(monkeypatch, tmp_path):
    _store_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(reading_extensions, "allowed_reading_extensions", lambda: {"read_aloud"})

    app = FastAPI()
    app.include_router(reading_extensions.router, prefix="/api/reading")
    response = TestClient(app).post(
        f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers",
        json={"locator": LOCATOR, "answers": _answers(("q_1", 1))},
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == NOT_ALLOWED_MESSAGE


# ---------------------------------------------------------------------------
# Unknown resources (404)
# ---------------------------------------------------------------------------


def test_action_unknown_extension_is_404(monkeypatch):
    response = _client(monkeypatch, _registry()).post(
        f"/api/reading/materials/{MATERIAL_ID}/extensions/ghost/actions/open",
        json={"locator": LOCATOR},
    )

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Reading extension not found."


def test_action_unknown_action_is_404(monkeypatch):
    response = _client(monkeypatch, _registry(_extension())).post(
        f"/api/reading/materials/{MATERIAL_ID}/extensions/sample/actions/ghost",
        json={"locator": LOCATOR},
    )

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Reading extension action not found."


def test_read_aloud_without_registered_extension_is_404(monkeypatch):
    async def synthesize(*_args):
        raise AssertionError("a missing extension must not reach the speech provider")

    monkeypatch.setattr(reading_extensions, "synthesize_speech", synthesize)

    response = _client(monkeypatch, _registry()).post(
        f"/api/reading/materials/{MATERIAL_ID}/read-aloud",
        json={"locator": LOCATOR},
    )

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Reading extension not found."


# ---------------------------------------------------------------------------
# Downstream failure visibility (400 on unreadable units)
# ---------------------------------------------------------------------------


def test_read_aloud_unit_failure_is_reported(monkeypatch):
    async def synthesize(*_args):
        raise AssertionError("a failed unit read must not reach the speech provider")

    monkeypatch.setattr(reading_extensions, "synthesize_speech", synthesize)
    monkeypatch.setattr(
        reading_extensions,
        "ReadingStore",
        lambda: _StubReadingStore(unit_error=OSError("unit unavailable")),
    )
    registry = _registry(_extension(extension_id="read_aloud"))

    response = _client(monkeypatch, registry).post(
        f"/api/reading/materials/{MATERIAL_ID}/read-aloud",
        json={"locator": LOCATOR},
    )

    assert response.status_code == 400, response.text
    assert isinstance(response.json()["detail"], str)
    assert response.json()["detail"].strip()


def test_action_unit_failure_is_reported(monkeypatch):
    def run(*_args):
        raise AssertionError("a failed unit read must not reach the extension")

    monkeypatch.setattr(
        reading_extensions,
        "ReadingStore",
        lambda: _StubReadingStore(unit_error=OSError("unit unavailable")),
    )

    response = _client(monkeypatch, _registry(_extension(run))).post(
        f"/api/reading/materials/{MATERIAL_ID}/extensions/sample/actions/open",
        json={"locator": LOCATOR},
    )

    assert response.status_code == 400, response.text
    assert isinstance(response.json()["detail"], str)
    assert response.json()["detail"].strip()


# ---------------------------------------------------------------------------
# Quiz answers payload and session contract
# ---------------------------------------------------------------------------


def test_quiz_answers_reject_empty_submission(monkeypatch, tmp_path):
    store = _store_fixture(tmp_path, monkeypatch)
    asyncio.run(store.put_reading_quiz_pending(MATERIAL_ID, LOCATOR, _quiz_questions()))

    app = FastAPI()
    app.include_router(reading_extensions.router, prefix="/api/reading")
    response = TestClient(app).post(
        f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers",
        json={"locator": LOCATOR, "answers": []},
    )

    assert response.status_code == 422, response.text
    assert asyncio.run(store.list_notebook_entries())["total"] == 0


def test_quiz_answers_reject_blank_question_id(monkeypatch, tmp_path):
    store = _store_fixture(tmp_path, monkeypatch)

    app = FastAPI()
    app.include_router(reading_extensions.router, prefix="/api/reading")
    response = TestClient(app).post(
        f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers",
        json={"locator": LOCATOR, "answers": _answers(("", 1))},
    )

    assert response.status_code == 422, response.text
    assert asyncio.run(store.list_notebook_entries())["total"] == 0


def test_quiz_answers_reject_invalid_locator(monkeypatch, tmp_path):
    store = _store_fixture(tmp_path, monkeypatch)

    app = FastAPI()
    app.include_router(reading_extensions.router, prefix="/api/reading")
    response = TestClient(app).post(
        f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers",
        json={"locator": 0, "answers": _answers(("q_1", 1))},
    )

    assert response.status_code == 422, response.text


def test_quiz_answers_unknown_session_is_404_with_message(monkeypatch, tmp_path):
    store = _store_fixture(tmp_path, monkeypatch)
    asyncio.run(store.put_reading_quiz_pending(MATERIAL_ID, LOCATOR, _quiz_questions()))

    app = FastAPI()
    app.include_router(reading_extensions.router, prefix="/api/reading")
    response = TestClient(app).post(
        f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers",
        json={
            "locator": LOCATOR,
            "session_id": "ghost-session",
            "answers": _answers(("q_1", 1)),
        },
    )

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Reading session not found."
    assert asyncio.run(store.list_notebook_entries())["total"] == 0


def test_quiz_assessment_write_failure_is_reported(monkeypatch, tmp_path):
    store = _store_fixture(tmp_path, monkeypatch)
    asyncio.run(store.put_reading_quiz_pending(MATERIAL_ID, LOCATOR, _quiz_questions()))

    from deeptutor.learning.assessment import RecordAssessmentError

    def fail_record(record):
        raise RecordAssessmentError("notebook write failed")

    monkeypatch.setattr("deeptutor.learning.assessment.record_assessment", fail_record)

    app = FastAPI()
    app.include_router(reading_extensions.router, prefix="/api/reading")
    response = TestClient(app).post(
        f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers",
        json={"locator": LOCATOR, "answers": _answers(("q_1", 1))},
    )

    assert response.status_code == 500, response.text
    assert isinstance(response.json()["detail"], str)
    assert response.json()["detail"].strip()


# ---------------------------------------------------------------------------
# Action payload validation (422)
# ---------------------------------------------------------------------------


def test_action_rejects_invalid_locator(monkeypatch):
    response = _client(monkeypatch, _registry(_extension())).post(
        f"/api/reading/materials/{MATERIAL_ID}/extensions/sample/actions/open",
        json={"locator": 0},
    )

    assert response.status_code == 422, response.text
