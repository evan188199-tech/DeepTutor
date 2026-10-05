"""Route-level contract tests for the mastery_path router's non-stream branches.

Complements ``deeptutor/learning/tests/test_api_endpoints.py`` (success-flow
coverage) with 4xx contracts, malformed payloads, learning-surface access
control, and the session-mode endpoint the package tests do not reach.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import mastery_path as mastery_router
from deeptutor.api.routers.auth import require_auth, require_learning_surface
from deeptutor.learning.storage import LearningStore


def _build_app(tmp_path, monkeypatch):
    def _make_store_with_tmp(root=None):
        return LearningStore(root=tmp_path)

    monkeypatch.setattr(
        "deeptutor.api.routers.mastery_path.LearningStore",
        _make_store_with_tmp,
    )
    return FastAPI(), tmp_path


@pytest.fixture
def app(tmp_path, monkeypatch):
    app, root = _build_app(tmp_path, monkeypatch)
    app.state.learning_root = root
    app.include_router(mastery_router.router, prefix="/api/mastery-paths")
    return app


@pytest.fixture
def guarded_client(tmp_path, monkeypatch):
    """A minimal app mounted with the same learning-surface guard as api/main.py."""
    app, _root = _build_app(tmp_path, monkeypatch)
    app.include_router(
        mastery_router.router,
        prefix="/api/mastery-paths",
        dependencies=[Depends(require_learning_surface)],
    )
    app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app)


@pytest.fixture
def client(app):
    return TestClient(app)


def _module_payload(module_id: str = "m1", kp_id: str = "kp1") -> dict:
    return {
        "id": module_id,
        "name": module_id.upper(),
        "order": 0,
        "knowledge_points": [
            {"id": kp_id, "name": kp_id.upper(), "type": "concept", "module_id": module_id}
        ],
    }


def _create_topic(client, **overrides) -> dict:
    body = {
        "name": "Linear Algebra",
        "goal": "Understand transformations visually",
        "sources": [],
        "modules": [_module_payload()],
    }
    body.update(overrides)
    response = client.post("/api/mastery-paths/topics", json=body)
    assert response.status_code == 200, response.text
    return response.json()


# -- GET /topics/index and GET /topics/{path_id} ----------------------------


class TestTopicReads:
    def test_topic_index_returns_label_shape(self, client):
        created = _create_topic(client, name="Indexed", emoji="📐")

        response = client.get("/api/mastery-paths/topics/index")

        assert response.status_code == 200
        assert response.json()["topics"] == [
            {
                "path_id": created["path_id"],
                "name": "Indexed",
                "emoji": "📐",
            }
        ]

    def test_get_topic_by_id_returns_full_payload(self, client):
        created = _create_topic(client, goal="A specific goal")

        response = client.get(f"/api/mastery-paths/topics/{created['path_id']}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["path_id"] == created["path_id"]
        assert payload["metadata"]["goal"] == "A specific goal"
        assert payload["map"]["counts"]["total"] == 1
        assert payload["path_revision"] == created["path_revision"]

    def test_get_topic_missing_returns_404(self, client):
        response = client.get("/api/mastery-paths/topics/no-such-topic")

        assert response.status_code == 404
        assert response.json()["detail"] == "Mastery topic not found"

    def test_get_topic_invalid_book_id_returns_400(self, client):
        assert client.get("/api/mastery-paths/topics/a\\b").status_code == 400


# -- POST /topics/draft and POST /topics ------------------------------------


class TestTopicWrites:
    def test_draft_generation_failure_returns_502(self, client):
        from deeptutor.learning.topic_generation import TopicGenerationError

        with patch(
            "deeptutor.learning.topic_generation.generate_topic_draft",
            new=AsyncMock(side_effect=TopicGenerationError("model unavailable")),
        ):
            response = client.post(
                "/api/mastery-paths/topics/draft",
                json={"name": "Algebra", "goal": "Master linear maps"},
            )

        assert response.status_code == 502
        assert response.json()["detail"] == "model unavailable"

    def test_create_topic_requires_goal_returns_422(self, client):
        response = client.post("/api/mastery-paths/topics", json={"name": "No goal"})

        assert response.status_code == 422

    def test_create_topic_unknown_prerequisite_ref_returns_422(self, client):
        response = client.post(
            "/api/mastery-paths/topics",
            json={
                "name": "Broken prereq",
                "goal": "Reference a waypoint that does not exist",
                "sources": [],
                "modules": [
                    {
                        "name": "Region",
                        "knowledge_points": [
                            {"client_ref": "a", "name": "Objective A", "type": "concept"},
                            {
                                "client_ref": "b",
                                "name": "Objective B",
                                "type": "concept",
                                "prerequisite_refs": ["ghost"],
                            },
                        ],
                    }
                ],
            },
        )

        assert response.status_code == 422
        assert "prerequisite" in response.json()["detail"]

    def test_create_topic_unknown_topic_source_ref_returns_422(self, client):
        response = client.post(
            "/api/mastery-paths/topics",
            json={
                "name": "Broken source ref",
                "goal": "Reference a source that does not exist",
                "sources": [],
                "modules": [
                    {
                        "name": "Region",
                        "knowledge_points": [
                            {
                                "client_ref": "a",
                                "name": "Objective A",
                                "type": "concept",
                                "topic_source_refs": ["ghost"],
                            }
                        ],
                    }
                ],
            },
        )

        assert response.status_code == 422
        assert "topic source" in response.json()["detail"]

    def test_create_topic_region_without_objectives_returns_422(self, client):
        response = client.post(
            "/api/mastery-paths/topics",
            json={
                "name": "Empty region",
                "goal": "Reject an outline with nothing to learn",
                "sources": [],
                "modules": [{"name": "Empty", "knowledge_points": []}],
            },
        )

        assert response.status_code == 422

    def test_edit_topic_map_invalid_book_id_returns_400(self, client):
        response = client.put(
            "/api/mastery-paths/topics/a\\b/map",
            json={"modules": [_module_payload()]},
        )

        assert response.status_code == 400

    def test_override_unknown_objective_returns_404(self, client):
        created = _create_topic(client)
        kp_id = created["map"]["modules"][0]["knowledge_points"][0]["id"]
        assert kp_id != "ghost"

        response = client.post(
            f"/api/mastery-paths/topics/{created['path_id']}/objectives/ghost/override",
            json={"mastered": True},
        )

        assert response.status_code == 404

    def test_topic_sessions_missing_topic_returns_404(self, client):
        response = client.get("/api/mastery-paths/topics/ghost/sessions")

        assert response.status_code == 404


# -- PUT /topics/{path_id}/sessions/{session_id}/mode -----------------------


class TestSetSessionMode:
    def _session_store(self, monkeypatch, session):
        session_store = AsyncMock()
        session_store.get_session.return_value = session
        monkeypatch.setattr(
            "deeptutor.services.session.get_session_store",
            lambda: session_store,
        )
        return session_store

    def test_unknown_mode_returns_422(self, client, monkeypatch):
        created = _create_topic(client)
        self._session_store(monkeypatch, {"session_id": "s1"})

        response = client.put(
            f"/api/mastery-paths/topics/{created['path_id']}/sessions/s1/mode",
            json={"mode": "bogus"},
        )

        assert response.status_code == 422
        assert "outline" in response.json()["detail"]

    def test_study_without_outline_returns_409(self, client, monkeypatch):
        created = _create_topic(client, modules=[])
        self._session_store(monkeypatch, {"session_id": "s1"})

        response = client.put(
            f"/api/mastery-paths/topics/{created['path_id']}/sessions/s1/mode",
            json={"mode": "study"},
        )

        assert response.status_code == 409
        assert "no outline to study" in response.json()["detail"].lower()

    def test_missing_session_returns_404(self, client, monkeypatch):
        created = _create_topic(client)
        self._session_store(monkeypatch, None)

        response = client.put(
            f"/api/mastery-paths/topics/{created['path_id']}/sessions/s1/mode",
            json={"mode": "outline"},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Session not found"

    def test_mode_is_normalized_and_preference_persisted(self, client, monkeypatch):
        created = _create_topic(client)
        session_store = self._session_store(monkeypatch, {"session_id": "s1"})

        response = client.put(
            f"/api/mastery-paths/topics/{created['path_id']}/sessions/s1/mode",
            json={"mode": "OUTLINE"},
        )

        assert response.status_code == 200
        assert response.json() == {"session_id": "s1", "mode": "outline"}
        session_store.update_session_preferences.assert_awaited_once_with(
            "s1",
            {"mastery_session_mode": "outline"},
        )


# -- PUT /topics/{path_id}/review-settings ----------------------------------


class TestReviewSettingsGuard:
    def test_invalid_book_id_returns_400(self, client):
        response = client.put(
            "/api/mastery-paths/topics/a\\b/review-settings",
            json={"desired_retention": 0.9},
        )

        assert response.status_code == 400


# -- GET /progress/{book_id}/map and /sessions -------------------------------


class TestProgressReads:
    def test_map_auto_provisions_new_book_with_derived_name(self, client, app):
        response = client.get("/api/mastery-paths/progress/freshmap/map")

        assert response.status_code == 200
        payload = response.json()
        assert payload["book_id"] == "freshmap"
        assert payload["name"] == "freshmap"
        assert LearningStore(root=app.state.learning_root).exists("freshmap") is True

    def test_progress_sessions_lists_bound_sessions(self, client, app):
        client.post(
            "/api/mastery-paths/progress/bound/init-modules",
            json={"modules": [_module_payload()]},
        )
        LearningStore(root=app.state.learning_root).bind_session("bound", "session-7")

        response = client.get("/api/mastery-paths/progress/bound/sessions")

        assert response.status_code == 200
        assert response.json() == {"book_id": "bound", "session_ids": ["session-7"]}

    def test_progress_sessions_missing_topic_returns_404(self, client):
        response = client.get("/api/mastery-paths/progress/ghost/sessions")

        assert response.status_code == 404

    def test_progress_sessions_invalid_book_id_returns_400(self, client):
        response = client.get("/api/mastery-paths/progress/a\\b/sessions")

        assert response.status_code == 400


# -- POST /progress/{book_id}/init-modules and /import-from-book -------------


class TestProgressWrites:
    def test_init_modules_kp_without_identity_returns_422(self, client):
        response = client.post(
            "/api/mastery-paths/progress/badkp/init-modules",
            json={
                "modules": [
                    {
                        "id": "m1",
                        "order": 0,
                        "name": "M1",
                        "knowledge_points": [{"name": "KP1", "type": "concept"}],
                    }
                ]
            },
        )

        assert response.status_code == 422
        assert "Invalid knowledge_point data" in response.json()["detail"]

    def test_init_modules_module_without_identity_returns_422(self, client):
        response = client.post(
            "/api/mastery-paths/progress/badmodule/init-modules",
            json={"modules": [{"name": "M1", "knowledge_points": []}]},
        )

        assert response.status_code == 422
        assert "Invalid module data" in response.json()["detail"]

    def test_import_from_book_missing_chapter_title_returns_422(self, client):
        response = client.post(
            "/api/mastery-paths/progress/untitled/import-from-book",
            json={"chapters": [{"knowledge_points": ["A"]}]},
        )

        assert response.status_code == 422

    def test_import_from_book_blank_title_falls_back_to_chapter_name(self, client):
        response = client.post(
            "/api/mastery-paths/progress/blanktitle/import-from-book",
            json={"chapters": [{"title": "", "knowledge_points": ["A"]}]},
        )

        assert response.status_code == 200
        progress = client.get("/api/mastery-paths/progress/blanktitle").json()
        assert progress["modules"][0]["name"] == "Chapter 1"


# -- POST /progress/{book_id}/generate-from-notebook and -from-reading -------


class TestGenerateFromSources:
    def test_unparseable_llm_json_returns_502(self, client):
        with patch("deeptutor.services.llm.complete", new=AsyncMock(return_value="garbage")):
            response = client.post(
                "/api/mastery-paths/progress/badjson/generate-from-notebook",
                json={
                    "notebook_id": "nb",
                    "records": [{"id": "r1", "type": "note", "title": "T", "output": "O"}],
                },
            )

        assert response.status_code == 502
        assert response.json()["detail"] == "LLM returned invalid JSON"

    def test_non_list_modules_from_llm_returns_502(self, client):
        import json as _json

        with patch(
            "deeptutor.services.llm.complete",
            new=AsyncMock(return_value=_json.dumps({"modules": "not-a-list"})),
        ):
            response = client.post(
                "/api/mastery-paths/progress/badshape/generate-from-notebook",
                json={
                    "notebook_id": "nb",
                    "records": [{"id": "r1", "type": "note", "title": "T", "output": "O"}],
                },
            )

        assert response.status_code == 502
        assert "modules is not a list" in response.json()["detail"]

    def test_reading_error_returns_400(self, client):
        from deeptutor.reading import ReadingError

        with patch(
            "deeptutor.reading.knowledge_capture.mastery_source_records",
            side_effect=ReadingError("workspace missing"),
        ):
            response = client.post(
                "/api/mastery-paths/progress/readgen/generate-from-reading",
                json={"workspace_id": "gone"},
            )

        assert response.status_code == 400
        assert response.json()["detail"] == "workspace missing"


# -- Learning-surface access control (mounted as in api/main.py) -------------


class TestLearningSurfaceAccess:
    def _set_current_policy(self, monkeypatch, policy):
        import deeptutor.multi_user.learning_access as learning_access

        monkeypatch.setattr(
            learning_access,
            "current_learning_policy",
            lambda: policy,
        )

    def test_restricted_account_without_chat_surface_is_403(self, guarded_client, monkeypatch):
        self._set_current_policy(monkeypatch, {"allowed_surfaces": ["reading"]})

        response = guarded_client.get("/api/mastery-paths/topics")

        assert response.status_code == 403
        assert "chat surface" in response.json()["detail"]

    def test_account_with_chat_surface_passes(self, guarded_client, monkeypatch):
        self._set_current_policy(monkeypatch, {"allowed_surfaces": ["chat", "reading"]})

        response = guarded_client.get("/api/mastery-paths/topics")

        assert response.status_code == 200
        assert response.json() == {"topics": []}

    def test_account_without_policy_is_allowed(self, guarded_client, monkeypatch):
        self._set_current_policy(monkeypatch, None)

        response = guarded_client.get("/api/mastery-paths/topics")

        assert response.status_code == 200
