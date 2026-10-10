"""Contract tests for the dedicated Watching workspace binding API.

These pin the per-session video binding that /watching and
/watching/{sessionId} restore from: a conversation owns exactly one video,
never a browser-global recent one. The suite drives the real ASGI routes
against real per-user stores under an isolated home:

1. creating a Watching conversation binds the requested video with progress;
2. each conversation restores its own video, not another conversation's;
3. rebinding and unbinding are validated and persist cleanly;
4. malformed ids and unknown sessions/materials are rejected without
   partially persisting anything;
5. a binding whose material disappeared degrades without losing the
   conversation;
6. another account cannot read or write a binding it does not own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

pytest.importorskip("fastapi")

from deeptutor.api.routers import video_learning as watching_router
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.path_service import PathService
from deeptutor.services.session import get_session_store
from deeptutor.video_learning.service import DEFAULT_VIDEO_LEARNING_SETTINGS, TimedMediaStore

MATERIAL_A = "a" * 32
MATERIAL_B = "b" * 32
UNKNOWN_MATERIAL = "c" * 32
POSITION_A = 120.0
POSITION_B = 45.0


def _material(material_id: str, *, video_id: str, title: str, position: float) -> dict[str, Any]:
    return {
        "version": 1,
        "type": "timed_media",
        "material_id": material_id,
        "source": {
            "provider": "youtube",
            "video_id": video_id,
            "url": f"https://youtu.be/{video_id}",
        },
        "metadata": {"title": title, "duration_seconds": 600},
        "transcript": {
            "status": "ready",
            "language": "en",
            "source": "youtube",
            "cues": [{"start": 0, "end": 10, "text": "Opening idea."}],
        },
        "learning": {"last_position": position},
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    monkeypatch.setattr(
        "deeptutor.video_learning.service.load_video_learning_settings",
        lambda: dict(DEFAULT_VIDEO_LEARNING_SETTINGS),
    )
    store = TimedMediaStore()
    store.save(
        _material(MATERIAL_A, video_id="aaaa11112222", title="Lecture A", position=POSITION_A)
    )
    store.save(
        _material(MATERIAL_B, video_id="bbbb33334444", title="Lecture B", position=POSITION_B)
    )
    app = FastAPI()
    app.include_router(watching_router.router, prefix="/api/video-learning")
    with TestClient(app) as test_client:
        yield test_client
    PathService.reset_instance()


def _start(client: TestClient, material_id: str) -> dict[str, Any]:
    response = client.post("/api/video-learning/watching", json={"material_id": material_id})
    assert response.status_code == 201, response.text
    return response.json()


def test_starting_a_conversation_binds_the_video_with_saved_progress(
    client: TestClient,
) -> None:
    body = _start(client, MATERIAL_A)

    assert body["material_id"] == MATERIAL_A
    assert body["session_id"]
    assert body["material"]["playback"]["start_seconds"] == POSITION_A

    restored = client.get(f"/api/video-learning/watching/{body['session_id']}").json()
    assert restored["material_id"] == MATERIAL_A
    assert restored["material"]["material_id"] == MATERIAL_A
    assert restored["material"]["playback"]["start_seconds"] == POSITION_A


def test_each_conversation_restores_its_own_video(client: TestClient) -> None:
    first = _start(client, MATERIAL_A)
    second = _start(client, MATERIAL_B)

    assert first["session_id"] != second["session_id"]

    first_binding = client.get(f"/api/video-learning/watching/{first['session_id']}").json()
    second_binding = client.get(f"/api/video-learning/watching/{second['session_id']}").json()

    assert first_binding["material_id"] == MATERIAL_A
    assert first_binding["material"]["source"]["video_id"] == "aaaa11112222"
    assert first_binding["material"]["playback"]["start_seconds"] == POSITION_A
    assert second_binding["material_id"] == MATERIAL_B
    assert second_binding["material"]["source"]["video_id"] == "bbbb33334444"
    assert second_binding["material"]["playback"]["start_seconds"] == POSITION_B


def test_preferences_persist_the_binding_beyond_the_http_roundtrip(
    client: TestClient,
) -> None:
    body = _start(client, MATERIAL_A)

    preferences = _stored_preferences(body["session_id"])

    assert preferences["watching_material_id"] == MATERIAL_A
    assert preferences["watching_bound_at"]


def _stored_preferences(session_id: str) -> dict[str, Any]:
    import asyncio

    async def load() -> dict[str, Any]:
        session = await get_session_store().get_session(session_id)
        assert session is not None
        return session.get("preferences") or {}

    return asyncio.run(load())


def test_rebinding_switches_the_video_for_that_conversation_only(
    client: TestClient,
) -> None:
    first = _start(client, MATERIAL_A)
    second = _start(client, MATERIAL_B)

    rebound_second = client.put(
        f"/api/video-learning/watching/{second['session_id']}",
        json={"material_id": MATERIAL_A},
    )
    rebound_first = client.put(
        f"/api/video-learning/watching/{first['session_id']}",
        json={"material_id": MATERIAL_B},
    )

    assert rebound_second.status_code == rebound_first.status_code == 200

    second_binding = client.get(f"/api/video-learning/watching/{second['session_id']}").json()
    first_binding = client.get(f"/api/video-learning/watching/{first['session_id']}").json()
    assert second_binding["material_id"] == MATERIAL_A
    assert second_binding["material"]["playback"]["start_seconds"] == POSITION_A
    assert first_binding["material_id"] == MATERIAL_B
    assert first_binding["material"]["playback"]["start_seconds"] == POSITION_B


def test_unbinding_clears_the_restore_target(client: TestClient) -> None:
    body = _start(client, MATERIAL_A)

    cleared = client.put(
        f"/api/video-learning/watching/{body['session_id']}", json={"material_id": ""}
    )

    assert cleared.status_code == 200
    assert cleared.json()["material_id"] == ""

    restored = client.get(f"/api/video-learning/watching/{body['session_id']}").json()
    assert restored["material_id"] == ""
    assert restored["material"] is None
    assert _stored_preferences(body["session_id"])["watching_material_id"] == ""


def test_malformed_material_ids_are_rejected_without_creating_sessions(
    client: TestClient,
) -> None:
    before = client.get("/api/video-learning/watching/unified_1_abcd1234")

    assert before.status_code == 404

    for bad_id in ("not-an-id", "ABC", "z" * 32, "../escape", "a" * 8, "a" * 65):
        created = client.post("/api/video-learning/watching", json={"material_id": bad_id})
        assert created.status_code == 422, bad_id

    body = _start(client, MATERIAL_A)
    rebound = client.put(
        f"/api/video-learning/watching/{body['session_id']}", json={"material_id": "zzz!"}
    )
    assert rebound.status_code == 422
    still = client.get(f"/api/video-learning/watching/{body['session_id']}").json()
    assert still["material_id"] == MATERIAL_A


def test_unknown_session_is_rejected_for_read_and_write(client: TestClient) -> None:
    missing = "unified_1700000000000_0000dead"

    assert client.get(f"/api/video-learning/watching/{missing}").status_code == 404
    assert (
        client.put(
            f"/api/video-learning/watching/{missing}", json={"material_id": MATERIAL_A}
        ).status_code
        == 404
    )


def test_unknown_material_is_rejected_without_partial_persistence(
    client: TestClient,
) -> None:
    created = client.post("/api/video-learning/watching", json={"material_id": UNKNOWN_MATERIAL})
    assert created.status_code == 404

    body = _start(client, MATERIAL_A)
    rebound = client.put(
        f"/api/video-learning/watching/{body['session_id']}",
        json={"material_id": UNKNOWN_MATERIAL},
    )
    assert rebound.status_code == 404

    still = client.get(f"/api/video-learning/watching/{body['session_id']}").json()
    assert still["material_id"] == MATERIAL_A


def test_removed_material_degrades_to_an_empty_binding_not_a_lost_conversation(
    client: TestClient,
) -> None:
    body = _start(client, MATERIAL_A)
    (
        PathService.get_instance().get_workspace_feature_dir("timed_media") / f"{MATERIAL_A}.json"
    ).unlink()

    restored = client.get(f"/api/video-learning/watching/{body['session_id']}")

    assert restored.status_code == 200
    assert restored.json()["material_id"] == MATERIAL_A
    assert restored.json()["material"] is None


def test_legacy_watching_sessions_are_flagged_for_the_reading_migration(
    client: TestClient,
) -> None:
    import asyncio

    async def legacy_session() -> str:
        store = get_session_store()
        session = await store.create_session(title="Legacy watching")
        await store.update_session_preferences(
            session["id"],
            {
                "capability": "immersive_watching",
                "workspace_mode": "immersive_watching",
                "session_kind": "immersive_watching",
                "timed_media_id": MATERIAL_A,
            },
        )
        return session["id"]

    session_id = asyncio.run(legacy_session())

    flagged = client.get(f"/api/video-learning/watching/{session_id}").json()
    assert flagged["legacy_watching"] is True
    assert flagged["material_id"] == ""

    bound = _start(client, MATERIAL_A)
    assert not client.get(f"/api/video-learning/watching/{bound['session_id']}").json()[
        "legacy_watching"
    ]

    empty = client.get(f"/api/video-learning/watching/{bound['session_id']}")
    assert empty.json()["legacy_watching"] is False


def _current_user(root: Path, user_id: str) -> CurrentUser:
    return CurrentUser(
        id=user_id,
        username=user_id,
        role="user",
        scope=UserScope(kind="user", user_id=user_id, root=root / "users" / user_id),
    )


@pytest.mark.asyncio
async def test_bindings_are_invisible_to_another_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    monkeypatch.setattr(
        "deeptutor.video_learning.service.load_video_learning_settings",
        lambda: dict(DEFAULT_VIDEO_LEARNING_SETTINGS),
    )

    token = set_current_user(_current_user(tmp_path, "u_alice"))
    try:
        store = TimedMediaStore()
        store.save(
            _material(
                MATERIAL_A, video_id="aaaa11112222", title="Alice lecture", position=POSITION_A
            )
        )
        session = await get_session_store().create_session(title="Alice watching")
        await get_session_store().update_session_preferences(
            session["id"], {"watching_material_id": MATERIAL_A}
        )
    finally:
        reset_current_user(token)

    token = set_current_user(_current_user(tmp_path, "u_bob"))
    try:
        with pytest.raises(HTTPException) as read_error:
            await watching_router.get_watching_binding(session["id"])
        assert read_error.value.status_code == 404

        with pytest.raises(HTTPException) as write_error:
            await watching_router.bind_watching_material(
                session["id"],
                watching_router.WatchingBindingRequest(material_id=MATERIAL_A),
            )
        assert write_error.value.status_code == 404

        bob_store = TimedMediaStore()
        bob_store.save(
            _material(MATERIAL_B, video_id="bbbb33334444", title="Bob lecture", position=POSITION_B)
        )
        with pytest.raises(HTTPException) as hijack_error:
            await watching_router.bind_watching_material(
                session["id"],
                watching_router.WatchingBindingRequest(material_id=MATERIAL_B),
            )
        assert hijack_error.value.status_code == 404
    finally:
        reset_current_user(token)

    token = set_current_user(_current_user(tmp_path, "u_alice"))
    try:
        restored = await watching_router.get_watching_binding(session["id"])
        assert restored["material_id"] == MATERIAL_A
        assert restored["material"]["source"]["video_id"] == "aaaa11112222"
    finally:
        reset_current_user(token)
    PathService.reset_instance()
