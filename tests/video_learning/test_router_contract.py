"""Contract tests for the video_learning router surface.

Covers the gaps ``tests/video_learning/test_router.py`` leaves open: the
settings router's admin gate and round-trip, the learning-surface guard on the
main router, payload-validation bounds (422), the router's exception-to-status
mapping (404/400/409/500), the invidious account/callback/browse contracts, and
the stream endpoint's format gating. All requests run through TestClient
against bare apps; no server is started and no network is contacted.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import video_learning
from deeptutor.api.routers.auth import (
    TokenPayload,
    require_admin,
    require_auth,
    require_learning_surface,
)
from deeptutor.services.notebook.service import NotebookCorruptedError, NotebookManager
from deeptutor.video_learning import notes as video_notes
from deeptutor.video_learning import service


class _Paths:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_workspace_feature_dir(self, feature: str) -> Path:
        assert feature == "timed_media"
        return self.root / feature


@pytest.fixture
def notebook_manager(tmp_path: Path) -> NotebookManager:
    return NotebookManager(base_dir=str(tmp_path / "notebooks"))


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    notebook_manager: NotebookManager,
) -> TestClient:
    monkeypatch.setattr(service, "get_current_path_service", lambda: _Paths(tmp_path))
    monkeypatch.setattr(
        service, "video_learning_settings_path", lambda: tmp_path / "video_learning.json"
    )
    monkeypatch.setattr(video_notes, "get_notebook_manager", lambda: notebook_manager)
    app = FastAPI()
    app.include_router(video_learning.router, prefix="/api/video-learning")
    return TestClient(app)


@pytest.fixture
def settings_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """The settings router mounted exactly as ``main.py`` mounts it."""
    monkeypatch.setattr(
        service, "video_learning_settings_path", lambda: tmp_path / "video_learning.json"
    )
    app = FastAPI()
    app.include_router(
        video_learning.settings_router,
        prefix="/api/settings/video-learning",
        dependencies=[Depends(require_admin)],
    )
    app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app)


def _material(*, duration: int = 100) -> dict[str, object]:
    material_id = service.material_id_for("dQw4w9WgXcQ")
    return {
        "version": 1,
        "type": "timed_media",
        "material_id": material_id,
        "source": {
            "provider": "youtube",
            "video_id": "dQw4w9WgXcQ",
            "url": "https://youtu.be/dQw4w9WgXcQ",
        },
        "metadata": {"duration_seconds": duration},
        "transcript": {"status": "ready", "cues": []},
        "learning": {"last_position": 0},
        "provider_cache": {
            "invidious_formats": [{"format_id": "18", "mime_type": "video/mp4"}],
        },
    }


# ---------------------------------------------------------------------------
# Auth gates
# ---------------------------------------------------------------------------


def test_settings_missing_token_is_unauthorized_when_auth_enabled(
    settings_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("deeptutor.api.routers.auth.AUTH_ENABLED", True)
    settings_client.app.dependency_overrides.pop(require_auth, None)
    response = settings_client.get("/api/settings/video-learning")
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"
    assert response.headers["www-authenticate"] == "Bearer"


def test_settings_non_admin_gets_403_admin_required(
    settings_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("deeptutor.api.routers.auth.AUTH_ENABLED", True)
    settings_client.app.dependency_overrides[require_auth] = lambda: TokenPayload(
        username="learner", role="user"
    )
    response = settings_client.get("/api/settings/video-learning")
    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required"


def test_main_router_learning_surface_denial_is_403(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(service, "get_current_path_service", lambda: _Paths(tmp_path))

    def _deny(_surface: str) -> None:
        raise PermissionError("denied by policy")

    monkeypatch.setattr("deeptutor.multi_user.learning_access.assert_learning_surface", _deny)
    app = FastAPI()
    app.include_router(
        video_learning.router,
        prefix="/api/video-learning",
        dependencies=[Depends(require_learning_surface)],
    )
    response = TestClient(app).get("/api/video-learning/materials/0123456789abcdef")
    assert response.status_code == 403
    assert "denied by policy" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Settings router contract
# ---------------------------------------------------------------------------


def test_settings_get_defaults_and_put_round_trip(settings_client: TestClient) -> None:
    defaults = settings_client.get("/api/settings/video-learning")
    assert defaults.status_code == 200
    assert defaults.json() == {
        "version": 1,
        "default_provider": "youtube",
        "youtube": {"transcript_provider": "youtube_transcript_api"},
        "invidious": {"api_base_url": "", "public_base_url": ""},
    }

    saved = settings_client.put(
        "/api/settings/video-learning",
        json={
            "default_provider": "youtube",
            "youtube": {"transcript_provider": "none"},
            "invidious": {"api_base_url": "http://invidious:3000/"},
            "unknown_key": "dropped-by-schema",
        },
    )
    assert saved.status_code == 200
    assert saved.json()["youtube"] == {"transcript_provider": "none"}
    assert saved.json()["invidious"]["api_base_url"] == "http://invidious:3000"
    assert "unknown_key" not in saved.json()

    reread = settings_client.get("/api/settings/video-learning")
    assert reread.json() == saved.json()


def test_settings_put_rejects_unknown_provider_and_baseless_invidious(
    settings_client: TestClient,
) -> None:
    bad_provider = settings_client.put(
        "/api/settings/video-learning", json={"default_provider": "vimeo"}
    )
    assert bad_provider.status_code == 400
    assert "must be 'youtube' or 'invidious'" in bad_provider.json()["detail"]

    baseless = settings_client.put(
        "/api/settings/video-learning", json={"default_provider": "invidious"}
    )
    assert baseless.status_code == 400
    assert "Configure the Invidious API base URL" in baseless.json()["detail"]


def test_settings_put_rejects_oversized_field_with_422(settings_client: TestClient) -> None:
    response = settings_client.put(
        "/api/settings/video-learning", json={"default_provider": "x" * 33}
    )
    assert response.status_code == 422


def test_test_invidious_reports_unconfigured_base(settings_client: TestClient) -> None:
    response = settings_client.post(
        "/api/settings/video-learning/test-invidious", json={"default_provider": "youtube"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "ok": False,
        "message": "Invidious API base URL is not configured.",
    }


# ---------------------------------------------------------------------------
# Resolve endpoint contract
# ---------------------------------------------------------------------------


def test_resolve_rejects_bad_provider_override_with_400(client: TestClient) -> None:
    response = client.post(
        "/api/video-learning/materials/resolve",
        json={"url": "https://youtu.be/dQw4w9WgXcQ", "provider_override": "vimeo"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported provider override."


def test_resolve_rejects_out_of_bounds_payload_with_422(client: TestClient) -> None:
    too_long = client.post(
        "/api/video-learning/materials/resolve",
        json={"url": "https://youtu.be/" + "a" * 2048},
    )
    assert too_long.status_code == 422

    bad_language = client.post(
        "/api/video-learning/materials/resolve",
        json={"url": "https://youtu.be/dQw4w9WgXcQ", "language": "x" * 33},
    )
    assert bad_language.status_code == 422


def test_resolve_error_mapping_not_found_bad_request_internal(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "/api/video-learning/materials/resolve"
    payload = {"url": "https://youtu.be/dQw4w9WgXcQ"}

    async def not_found(*_args, **_kwargs):
        raise service.TimedMediaNotFound("no such material")

    async def bad_request(*_args, **_kwargs):
        raise service.TimedMediaError("transcript unavailable")

    async def boom(*_args, **_kwargs):
        raise ValueError("unexpected internals")

    monkeypatch.setattr(video_learning, "resolve_material", not_found)
    missing = client.post(url, json=payload)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "no such material"

    monkeypatch.setattr(video_learning, "resolve_material", bad_request)
    rejected = client.post(url, json=payload)
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == "transcript unavailable"

    monkeypatch.setattr(video_learning, "resolve_material", boom)
    internal = client.post(url, json=payload)
    assert internal.status_code == 500
    assert internal.json()["detail"] == "Video learning could not complete the request."


# ---------------------------------------------------------------------------
# Payload bounds (422) on other write endpoints
# ---------------------------------------------------------------------------


def test_progress_rejects_out_of_bounds_payload_with_422(client: TestClient) -> None:
    url = "/api/video-learning/materials/0123456789abcdef/progress"
    assert client.put(url, json={"time_seconds": -1}).status_code == 422
    assert client.put(url, json={"time_seconds": 24 * 60 * 60 + 1}).status_code == 422
    assert client.put(url, json={"time_seconds": "not-a-number"}).status_code == 422


def test_mark_create_rejects_invalid_payload_with_422(client: TestClient) -> None:
    material = _material()
    service.get_timed_media_store().save(material)
    url = f"/api/video-learning/materials/{material['material_id']}/marks"

    assert (
        client.post(url, json={"kind": "", "start_seconds": 1, "end_seconds": 2}).status_code == 422
    )
    assert (
        client.post(
            url, json={"kind": "key_point", "start_seconds": -1, "end_seconds": 2}
        ).status_code
        == 422
    )
    assert (
        client.post(
            url,
            json={"kind": "key_point", "start_seconds": 1, "end_seconds": 2, "quote": "q" * 4001},
        ).status_code
        == 422
    )


# ---------------------------------------------------------------------------
# Marks CRUD contract
# ---------------------------------------------------------------------------


def test_marks_crud_round_trip_and_unknown_material_404(client: TestClient) -> None:
    material = _material()
    service.get_timed_media_store().save(material)
    base = f"/api/video-learning/materials/{material['material_id']}/marks"

    created = client.post(base, json={"kind": "key_point", "start_seconds": 5, "end_seconds": 10})
    assert created.status_code == 201
    mark = created.json()
    assert mark["kind"] == "key_point"
    assert mark["start_seconds"] == 5.0
    assert len(mark["mark_id"]) == 24

    listed = client.get(base)
    assert listed.status_code == 200
    assert [row["mark_id"] for row in listed.json()] == [mark["mark_id"]]

    single = client.get(f"{base}/{mark['mark_id']}")
    assert single.status_code == 200
    assert single.json() == mark

    patched = client.patch(f"{base}/{mark['mark_id']}", json={"reviewed": True})
    assert patched.status_code == 200
    assert patched.json()["reviewed_at"]

    deleted = client.delete(f"{base}/{mark['mark_id']}")
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}
    assert client.get(base).json() == []

    assert client.get(f"{base}/missing-mark").status_code == 404
    assert client.get("/api/video-learning/materials/0123456789abcdef/marks").status_code == 404


def test_mark_patch_with_no_fields_maps_to_400(client: TestClient) -> None:
    material = _material()
    service.get_timed_media_store().save(material)
    base = f"/api/video-learning/materials/{material['material_id']}/marks"
    mark = client.post(base, json={"kind": "question", "start_seconds": 1, "end_seconds": 2}).json()

    response = client.patch(f"{base}/{mark['mark_id']}", json={})
    assert response.status_code == 400
    assert response.json()["detail"] == "No mark fields to update."


def test_mark_suggestions_contract(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    material = _material()
    service.get_timed_media_store().save(material)

    async def suggestions(_material: dict, time_seconds: float) -> list[dict]:
        assert time_seconds == 42
        return [{"kind": "review", "start_seconds": 40}]

    monkeypatch.setattr(video_learning, "suggest_marks", suggestions)
    response = client.post(
        f"/api/video-learning/materials/{material['material_id']}/mark-suggestions",
        json={"time_seconds": 42},
    )
    assert response.status_code == 200
    assert response.json() == {"suggestions": [{"kind": "review", "start_seconds": 40}]}

    missing = client.post(
        "/api/video-learning/materials/0123456789abcdef/mark-suggestions",
        json={"time_seconds": 42},
    )
    assert missing.status_code == 404


# ---------------------------------------------------------------------------
# Notes error contract
# ---------------------------------------------------------------------------


def test_corrupted_notebook_maps_to_409_structured_body(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _corrupted(_manager, _material_id):
        raise NotebookCorruptedError("nb-1", tmp_path / "nb-1.json", ValueError("bad json"))

    monkeypatch.setattr(video_notes, "list_notes", _corrupted)
    response = client.get("/api/video-learning/materials/0123456789abcdef/notes")
    assert response.status_code == 409
    body = response.json()["detail"]
    assert body["code"] == "notebook_unreadable"
    assert body["notebook_id"] == "nb-1"
    assert "bad json" in body["message"]


# ---------------------------------------------------------------------------
# Stream endpoint format gating
# ---------------------------------------------------------------------------


def test_stream_rejects_non_numeric_or_overlong_format_with_404(client: TestClient) -> None:
    material_id = service.material_id_for("dQw4w9WgXcQ")
    assert client.get(f"/api/video-learning/materials/{material_id}/stream/abc").status_code == 404
    assert (
        client.get(f"/api/video-learning/materials/{material_id}/stream/1234567").status_code == 404
    )


def test_stream_requires_invidious_descriptor_with_400(client: TestClient) -> None:
    material = _material()
    service.get_timed_media_store().save(material)
    response = client.get(f"/api/video-learning/materials/{material['material_id']}/stream/18")
    assert response.status_code == 400
    assert "only for an Invidious descriptor" in response.json()["detail"]


def test_stream_head_returns_metadata_without_upstream(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    material = _material()
    service.get_timed_media_store().save(material)

    async def live_stream(_material_id: str, _format_id: str) -> tuple[str, str]:
        return "https://r1.googlevideo.com/videoplayback", "video/mp4"

    async def no_upstream(*_args):
        raise AssertionError("HEAD must not open the upstream stream")

    monkeypatch.setattr(video_learning, "_live_stream_url", live_stream)
    monkeypatch.setattr(video_learning, "_open_upstream", no_upstream)

    response = client.head(f"/api/video-learning/materials/{material['material_id']}/stream/18")
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["accept-ranges"] == "bytes"


# ---------------------------------------------------------------------------
# Invidious account endpoints
# ---------------------------------------------------------------------------


def test_invidious_callback_redirect_contract(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def connected(**_kwargs):
        return None

    async def scoped(**_kwargs):
        raise service.TimedMediaError("Invidious account token is missing a required scope.")

    monkeypatch.setattr(
        video_learning.invidious_account,
        "complete_invidious_account_authorization",
        connected,
    )
    ok = client.get(
        "/api/video-learning/invidious/account/callback?token=t&state=s",
        follow_redirects=False,
    )
    assert ok.status_code == 303
    assert ok.headers["location"] == "/watching?account=connected"
    assert ok.headers["cache-control"] == "no-store"
    assert ok.headers["referrer-policy"] == "no-referrer"

    monkeypatch.setattr(
        video_learning.invidious_account,
        "complete_invidious_account_authorization",
        scoped,
    )
    denied = client.get(
        "/api/video-learning/invidious/account/callback?token=t&state=s",
        follow_redirects=False,
    )
    assert denied.status_code == 303
    assert denied.headers["location"] == "/watching?account=authorization_scopes"

    cancelled = client.get("/api/video-learning/invidious/account/callback", follow_redirects=False)
    assert cancelled.status_code == 303
    assert cancelled.headers["location"] == "/watching?account=authorization_cancelled"


def test_invidious_authorize_status_and_disconnect_contract(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(video_learning, "current_owner_id", lambda: "owner-1")
    monkeypatch.setattr(
        video_learning.invidious_account,
        "invidious_redirect_uri",
        lambda: "http://test/api/video-learning/invidious/account/callback",
    )
    monkeypatch.setattr(
        video_learning.invidious_account,
        "begin_invidious_account_authorization",
        lambda *, owner_id, redirect_uri: f"{redirect_uri}?owner={owner_id}",
    )
    monkeypatch.setattr(
        video_learning.invidious_account,
        "invidious_account_status",
        lambda owner_id: {"connected": False, "owner_id": owner_id},
    )

    async def disconnect(*, owner_id):
        return {"connected": False, "owner_id": owner_id}

    monkeypatch.setattr(
        video_learning.invidious_account, "disconnect_invidious_account", disconnect
    )

    authorize = client.post("/api/video-learning/invidious/account/authorize")
    assert authorize.status_code == 200
    assert authorize.json()["authorize_url"] == (
        "http://test/api/video-learning/invidious/account/callback?owner=owner-1"
    )

    status = client.get("/api/video-learning/invidious/account/status")
    assert status.status_code == 200
    assert status.json() == {"connected": False, "owner_id": "owner-1"}

    off = client.post("/api/video-learning/invidious/account/disconnect")
    assert off.status_code == 200
    assert off.json() == {"connected": False, "owner_id": "owner-1"}


def test_browse_invidious_page_bounds_and_success_headers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (
        client.get("/api/video-learning/invidious/browse/search", params={"page": 0}).status_code
        == 422
    )
    assert (
        client.get("/api/video-learning/invidious/browse/search", params={"page": 1001}).status_code
        == 422
    )

    async def browse(*, owner_id, kind, query, page, playlist_id):
        return {"kind": kind, "query": query, "page": page, "owner_id": owner_id}

    monkeypatch.setattr(video_learning.invidious_account, "browse_invidious", browse)
    response = client.get(
        "/api/video-learning/invidious/browse/search",
        params={"q": "lesson", "page": 2},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["page"] == 2
