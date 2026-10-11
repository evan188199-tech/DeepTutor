from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from deeptutor.multi_user import paths
from deeptutor.video_learning import service, subtitle_prefetch
from deeptutor.video_learning.subtitle_prefetch import RETRY_DELAYS, SubtitlePrefetchService

OWNER = "tester"


class _Paths:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_workspace_feature_dir(self, feature: str) -> Path:
        return self.root / "workspace" / feature


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> service.TimedMediaStore:
    monkeypatch.setattr(service, "get_current_path_service", lambda: _Paths(tmp_path))
    monkeypatch.setattr(paths, "SYSTEM_ROOT", tmp_path / "system")
    return service.TimedMediaStore()


def material_id() -> str:
    return service.material_id_for("dQw4w9WgXcQ")


def save_material(
    store: service.TimedMediaStore,
    *,
    cues: list[dict[str, Any]] | None = None,
    fetch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    transcript: dict[str, Any] = {"status": "unavailable", "reason": "unavailable", "cues": []}
    if cues:
        transcript = {"status": "ready", "reason": "", "language": "en", "cues": cues}
    if fetch is not None:
        transcript["fetch"] = fetch
    store.save(
        {
            "version": 1,
            "type": "timed_media",
            "material_id": material_id(),
            "source": {"video_id": "dQw4w9WgXcQ"},
            "metadata": {},
            "transcript": transcript,
            "learning": {},
        }
    )
    return store.get(material_id())


def grant_consent() -> None:
    subtitle_prefetch.HostChromeSessionStore.enable(OWNER)


def pretend_consented(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subtitle_prefetch.HostChromeSessionStore,
        "enabled",
        classmethod(lambda cls, _owner_id: True),
    )


async def drain(prefetch: SubtitlePrefetchService) -> None:
    for _ in range(200):
        if not prefetch._pending:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0)


def iso(moment: datetime) -> str:
    return moment.isoformat()


@pytest.mark.asyncio
async def test_enqueue_is_a_hit_when_cues_already_exist(
    isolated: service.TimedMediaStore,
) -> None:
    save_material(isolated, cues=[{"start": 0.0, "end": 1.0, "text": "Already here."}])
    calls: list[Any] = []

    async def unexpected_download(*_args: object, **_kwargs: object):
        calls.append(_args)

    prefetch = SubtitlePrefetchService()
    state = await prefetch.enqueue(OWNER, material_id(), isolated, manual=True)

    assert state == {}
    assert calls == []
    assert prefetch._pending == set()


@pytest.mark.asyncio
async def test_enqueue_requires_an_opted_in_host_chrome_session(
    isolated: service.TimedMediaStore,
) -> None:
    save_material(isolated)
    calls: list[Any] = []

    async def unexpected_download(*_args: object, **_kwargs: object):
        calls.append(_args)

    prefetch = SubtitlePrefetchService()
    state = await prefetch.enqueue(OWNER, material_id(), isolated, manual=True)

    assert state["status"] == "auth_required"
    assert state["error_code"] == "auth_required"
    persisted = isolated.get(material_id())["transcript"]["fetch"]
    assert persisted["status"] == "auth_required"
    assert calls == []
    assert prefetch._pending == set()


@pytest.mark.parametrize("status", ["auth_required", "unavailable", "error"])
@pytest.mark.asyncio
async def test_enqueue_refuses_stalled_states_without_manual_retry(
    isolated: service.TimedMediaStore, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    save_material(isolated, fetch={"status": status, "error_code": "prior", "attempts": 2})
    pretend_consented(monkeypatch)
    calls: list[Any] = []

    async def unexpected_download(*_args: object, **_kwargs: object):
        calls.append(_args)

    prefetch = SubtitlePrefetchService()
    state = await prefetch.enqueue(OWNER, material_id(), isolated)

    assert state["status"] == status
    assert state["attempts"] == 2
    assert calls == []
    assert prefetch._pending == set()


@pytest.mark.asyncio
async def test_retry_wait_holds_until_the_deadline_then_refetches(
    isolated: service.TimedMediaStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    future = iso(datetime.now(timezone.utc) + timedelta(hours=1))
    save_material(
        isolated,
        fetch={
            "status": "retry_wait",
            "error_code": "rate_limited",
            "attempts": 2,
            "next_retry_at": future,
        },
    )
    pretend_consented(monkeypatch)
    calls: list[tuple[str, str]] = []

    async def success(_video_id: str, preferred_language: str = ""):
        calls.append((_video_id, preferred_language))
        return [{"start": 0.0, "end": 1.0, "text": "Late success."}], "en", "youtube-chrome"

    monkeypatch.setattr(subtitle_prefetch, "download_ytdlp_subtitle", success)
    prefetch = SubtitlePrefetchService()

    held = await prefetch.enqueue(OWNER, material_id(), isolated)
    assert held["status"] == "retry_wait"
    assert held["next_retry_at"] == future
    assert calls == []

    assert subtitle_prefetch._retry_deadline({}) is None
    assert subtitle_prefetch._retry_deadline({"next_retry_at": "not-a-timestamp"}) is None

    material = isolated.get(material_id())
    material["transcript"]["fetch"]["next_retry_at"] = iso(
        datetime.now(timezone.utc) - timedelta(minutes=1)
    )
    isolated.save(material)

    state = await prefetch.enqueue(OWNER, material_id(), isolated)
    assert state["status"] == "queued"
    await drain(prefetch)

    saved = isolated.get(material_id())["transcript"]["fetch"]
    assert saved["status"] == "ready"
    assert saved["attempts"] == 3
    assert calls == [("dQw4w9WgXcQ", "")]


@pytest.mark.asyncio
async def test_miss_fetches_ready_writes_cues_segments_and_is_idempotent(
    isolated: service.TimedMediaStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_material(isolated)
    pretend_consented(monkeypatch)
    calls: list[tuple[str, str]] = []
    cues = [
        {"start": 0.0, "end": 2.0, "text": "Hello"},
        {"start": 2.0, "end": 4.0, "text": "World"},
    ]

    async def success(_video_id: str, preferred_language: str = ""):
        calls.append((_video_id, preferred_language))
        return cues, "en", "youtube-chrome"

    monkeypatch.setattr(subtitle_prefetch, "download_ytdlp_subtitle", success)
    prefetch = SubtitlePrefetchService()

    queued = await prefetch.enqueue(OWNER, material_id(), isolated, manual=True)
    assert queued["status"] == "queued"
    await drain(prefetch)

    saved = isolated.get(material_id())
    assert saved["transcript"]["status"] == "ready"
    assert saved["transcript"]["reason"] == ""
    assert saved["transcript"]["language"] == "en"
    assert saved["transcript"]["source"] == "youtube-chrome"
    assert saved["transcript"]["cues"] == cues
    assert saved["segments"] == service.build_segments(cues)
    fetch = saved["transcript"]["fetch"]
    assert fetch["status"] == "ready"
    assert fetch["attempts"] == 1
    assert fetch["error_code"] is None
    assert fetch["next_retry_at"] is None
    assert prefetch._pending == set()

    again = await prefetch.enqueue(OWNER, material_id(), isolated, manual=True)
    assert again["status"] == "ready"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_auth_failure_marks_auth_required_and_blocks_automatic_retry(
    isolated: service.TimedMediaStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_material(isolated)
    pretend_consented(monkeypatch)
    calls: list[Any] = []

    async def unauthorized(_video_id: str, preferred_language: str = ""):
        calls.append(_video_id)
        return [], "", "auth_required"

    monkeypatch.setattr(subtitle_prefetch, "download_ytdlp_subtitle", unauthorized)
    prefetch = SubtitlePrefetchService()

    await prefetch.enqueue(OWNER, material_id(), isolated, manual=True)
    await drain(prefetch)

    saved = isolated.get(material_id())["transcript"]["fetch"]
    assert saved["status"] == "auth_required"
    assert saved["error_code"] == "auth_required"
    assert saved["attempts"] == 1
    assert saved["next_retry_at"] is None

    repeat = await prefetch.enqueue(OWNER, material_id(), isolated)
    assert repeat["status"] == "auth_required"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_unknown_failure_code_degrades_to_unavailable(
    isolated: service.TimedMediaStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_material(isolated)
    pretend_consented(monkeypatch)

    async def broken(_video_id: str, preferred_language: str = ""):
        return [], "", "captions_disabled"

    monkeypatch.setattr(subtitle_prefetch, "download_ytdlp_subtitle", broken)
    prefetch = SubtitlePrefetchService()

    await prefetch.enqueue(OWNER, material_id(), isolated, manual=True)
    await drain(prefetch)

    saved = isolated.get(material_id())["transcript"]["fetch"]
    assert saved["status"] == "unavailable"
    assert saved["error_code"] == "captions_disabled"
    assert saved["attempts"] == 1
    assert saved["next_retry_at"] is None


@pytest.mark.parametrize(
    ("preset_attempts", "expected_index"),
    [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (9, 4)],
)
@pytest.mark.asyncio
async def test_backoff_escalates_through_retry_delays_and_caps(
    isolated: service.TimedMediaStore,
    monkeypatch: pytest.MonkeyPatch,
    preset_attempts: int,
    expected_index: int,
) -> None:
    save_material(
        isolated,
        fetch={
            "status": "retry_wait",
            "error_code": "rate_limited",
            "attempts": preset_attempts,
            "next_retry_at": iso(datetime.now(timezone.utc) - timedelta(minutes=1)),
        },
    )
    pretend_consented(monkeypatch)
    calls: list[Any] = []

    async def rate_limited(_video_id: str, preferred_language: str = ""):
        calls.append(_video_id)
        return [], "", "rate_limited"

    monkeypatch.setattr(subtitle_prefetch, "download_ytdlp_subtitle", rate_limited)
    prefetch = SubtitlePrefetchService()

    await prefetch.enqueue(OWNER, material_id(), isolated)
    await drain(prefetch)

    saved = isolated.get(material_id())["transcript"]["fetch"]
    assert saved["status"] == "retry_wait"
    assert saved["attempts"] == preset_attempts + 1
    fetched_at = datetime.fromisoformat(saved["updated_at"])
    retry_at = datetime.fromisoformat(saved["next_retry_at"])
    expected = RETRY_DELAYS[expected_index]
    assert timedelta(seconds=expected.total_seconds() - 60) <= retry_at - fetched_at
    assert retry_at - fetched_at <= timedelta(seconds=expected.total_seconds() + 60)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_enqueue_dedupes_while_the_same_fetch_is_pending(
    isolated: service.TimedMediaStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_material(isolated, fetch={"status": "queued", "attempts": 0, "error_code": None})
    pretend_consented(monkeypatch)
    calls: list[Any] = []

    async def unexpected_download(*_args: object, **_kwargs: object):
        calls.append(_args)

    prefetch = SubtitlePrefetchService()
    prefetch._pending.add((OWNER, material_id()))

    state = await prefetch.enqueue(OWNER, material_id(), isolated, manual=True)

    assert state["status"] == "queued"
    assert calls == []
    assert prefetch._pending == {(OWNER, material_id())}


@pytest.mark.asyncio
async def test_fetch_keeps_cues_that_arrive_while_downloading(
    isolated: service.TimedMediaStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_material(isolated)
    pretend_consented(monkeypatch)
    writer_cues = [{"start": 0.0, "end": 1.0, "text": "Concurrent writer."}]

    async def racing_download(_video_id: str, preferred_language: str = ""):
        material = isolated.get(material_id())
        material["transcript"] = {
            "status": "ready",
            "reason": "",
            "language": "en",
            "cues": writer_cues,
        }
        isolated.save(material)
        return [{"start": 5.0, "end": 6.0, "text": "Stale download."}], "en", "youtube-chrome"

    monkeypatch.setattr(subtitle_prefetch, "download_ytdlp_subtitle", racing_download)
    prefetch = SubtitlePrefetchService()

    await prefetch.enqueue(OWNER, material_id(), isolated, manual=True)
    await drain(prefetch)

    saved = isolated.get(material_id())
    assert saved["transcript"]["cues"] == writer_cues
    assert "Stale download." not in saved["transcript"]["cues"][0]["text"]
    assert saved["transcript"].get("source") != "youtube-chrome"
    assert prefetch._pending == set()


def test_module_exposes_one_shared_service() -> None:
    first = subtitle_prefetch.get_subtitle_prefetch_service()
    second = subtitle_prefetch.get_subtitle_prefetch_service()
    assert first is second
    assert isinstance(first, SubtitlePrefetchService)
