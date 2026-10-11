from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from deeptutor.video_learning import service, subtitle_prefetch
from deeptutor.video_learning.subtitle_prefetch import RETRY_DELAYS, SubtitlePrefetchService

VIDEO_ID = "dQw4w9WgXcQ"


class _Paths:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_workspace_feature_dir(self, feature: str) -> Path:
        assert feature == "timed_media"
        return self.root / "workspace" / feature


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> service.TimedMediaStore:
    monkeypatch.setattr(service, "get_current_path_service", lambda: _Paths(tmp_path))
    return service.TimedMediaStore(root=tmp_path / "timed_media")


def material_id(video_id: str = VIDEO_ID) -> str:
    return service.material_id_for(video_id)


def save_material(
    store: service.TimedMediaStore,
    video_id: str = VIDEO_ID,
    *,
    cues: list[dict[str, Any]] | None = None,
    language: str = "",
    fetch: dict[str, Any] | None = None,
) -> None:
    transcript: dict[str, Any] = {"status": "unavailable", "reason": "unavailable", "cues": []}
    if cues:
        transcript = {"status": "ready", "reason": "", "language": language, "cues": cues}
    if fetch is not None:
        transcript["fetch"] = fetch
    store.save(
        {
            "version": 1,
            "type": "timed_media",
            "material_id": material_id(video_id),
            "source": {"video_id": video_id},
            "metadata": {},
            "transcript": transcript,
            "learning": {},
        }
    )


def grant_consent(monkeypatch: pytest.MonkeyPatch, *, enabled: bool = True) -> None:
    monkeypatch.setattr(
        subtitle_prefetch.HostChromeSessionStore,
        "enabled",
        classmethod(lambda cls, _owner_id: enabled),
    )


def stub_download(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cues: list[dict[str, Any]] | None = None,
    language: str = "en",
    code: str = "",
    gate: asyncio.Event | None = None,
    trace: dict[str, int] | None = None,
):
    async def fake_download(*_args: object, **_kwargs: object):
        if trace is not None:
            trace["started"] = trace.get("started", 0) + 1
            trace["in_flight"] = trace.get("in_flight", 0) + 1
            trace["max_in_flight"] = max(trace.get("max_in_flight", 0), trace["in_flight"])
        try:
            if gate is not None:
                await gate.wait()
            if trace is not None:
                await asyncio.sleep(0)
            return list(cues or []), language, code
        finally:
            if trace is not None:
                trace["in_flight"] -= 1

    monkeypatch.setattr(subtitle_prefetch, "download_ytdlp_subtitle", fake_download)


async def wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "condition not reached in time"
        await asyncio.sleep(0.01)


async def drain(prefetch: SubtitlePrefetchService) -> None:
    await wait_until(lambda: not prefetch._pending)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_enqueue_is_a_hit_when_cues_already_exist(
    isolated: service.TimedMediaStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_material(isolated, cues=[{"start": 0.0, "end": 1.0, "text": "Already here."}])
    trace: dict[str, int] = {}
    stub_download(monkeypatch, trace=trace)

    prefetch = SubtitlePrefetchService()
    state = await prefetch.enqueue("tester", material_id(), isolated, manual=True)

    assert state == {}
    assert prefetch._pending == set()
    assert trace == {}
    persisted = isolated.get(material_id())["transcript"]
    assert persisted.get("fetch", {}) == {}
    assert persisted["status"] == "ready"


@pytest.mark.asyncio
async def test_miss_fetches_and_persists_ready_transcript(
    isolated: service.TimedMediaStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_material(isolated, language="zh-CN")
    grant_consent(monkeypatch)
    cues = [
        {"start": 0.0, "end": 2.0, "text": "Hello"},
        {"start": 2.0, "end": 4.0, "text": "world."},
    ]
    trace: dict[str, int] = {}
    stub_download(monkeypatch, cues=cues, language="zh-CN", trace=trace)

    prefetch = SubtitlePrefetchService()
    state = await prefetch.enqueue("tester", material_id(), isolated)

    assert state["status"] == "queued"
    await drain(prefetch)

    assert trace["started"] == 1
    material = isolated.get(material_id())
    transcript = material["transcript"]
    assert transcript["status"] == "ready"
    assert transcript["cues"] == cues
    assert transcript["language"] == "zh-CN"
    assert transcript["source"] == "youtube-chrome"
    assert transcript["fetch"]["status"] == "ready"
    assert transcript["fetch"]["attempts"] == 1
    segments = material["segments"]
    assert segments and segments[0]["locator"] == 1
    assert prefetch._pending == set()


@pytest.mark.asyncio
async def test_miss_without_consent_persists_auth_required_and_skips_fetch(
    isolated: service.TimedMediaStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_material(isolated, fetch={"status": "error", "attempts": 2})
    grant_consent(monkeypatch, enabled=False)
    trace: dict[str, int] = {}
    stub_download(monkeypatch, trace=trace)

    prefetch = SubtitlePrefetchService()
    state = await prefetch.enqueue("tester", material_id(), isolated, manual=True)

    assert state["status"] == "auth_required"
    assert state["error_code"] == "auth_required"
    assert state["attempts"] == 2
    assert prefetch._pending == set()
    assert trace == {}
    persisted = isolated.get(material_id())["transcript"]["fetch"]
    assert persisted["status"] == "auth_required"
    assert persisted["attempts"] == 2
    assert persisted["next_retry_at"] is None


@pytest.mark.asyncio
async def test_terminal_failure_state_is_not_refetched_without_manual(
    isolated: service.TimedMediaStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_material(isolated, fetch={"status": "unavailable", "error_code": "no_captions"})
    grant_consent(monkeypatch)
    trace: dict[str, int] = {}
    stub_download(monkeypatch, trace=trace)

    prefetch = SubtitlePrefetchService()
    state = await prefetch.enqueue("tester", material_id(), isolated)

    assert state["status"] == "unavailable"
    assert state["error_code"] == "no_captions"
    assert prefetch._pending == set()
    assert trace == {}


@pytest.mark.asyncio
async def test_expired_retry_wait_is_refetched_and_backoff_restarts(
    isolated: service.TimedMediaStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    save_material(
        isolated,
        fetch={
            "status": "retry_wait",
            "error_code": "rate_limited",
            "attempts": 3,
            "next_retry_at": stale,
        },
    )
    grant_consent(monkeypatch)
    trace: dict[str, int] = {}
    stub_download(monkeypatch, code="rate_limited", trace=trace)

    prefetch = SubtitlePrefetchService()
    state = await prefetch.enqueue("tester", material_id(), isolated)

    assert state["status"] == "queued"
    assert state["attempts"] == 3
    await drain(prefetch)

    assert trace["started"] == 1
    persisted = isolated.get(material_id())["transcript"]["fetch"]
    assert persisted["status"] == "retry_wait"
    assert persisted["error_code"] == "rate_limited"
    assert persisted["attempts"] == 4
    deadline = datetime.fromisoformat(str(persisted["next_retry_at"]).replace("Z", "+00:00"))
    expected = datetime.now(timezone.utc) + RETRY_DELAYS[3]
    assert deadline > datetime.now(timezone.utc)
    assert abs((deadline - expected).total_seconds()) < 60


@pytest.mark.asyncio
async def test_concurrent_enqueues_share_a_single_in_flight_fetch(
    isolated: service.TimedMediaStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_material(isolated)
    grant_consent(monkeypatch)
    gate = asyncio.Event()
    trace: dict[str, int] = {}
    stub_download(
        monkeypatch, cues=[{"start": 0.0, "end": 1.0, "text": "Once."}], gate=gate, trace=trace
    )

    prefetch = SubtitlePrefetchService()
    first = await prefetch.enqueue("tester", material_id(), isolated)
    await wait_until(lambda: trace.get("started") == 1)
    second = await prefetch.enqueue("tester", material_id(), isolated)

    assert first["status"] == "queued"
    assert second["status"] == "fetching"
    assert second["attempts"] == 1
    assert trace["started"] == 1

    gate.set()
    await drain(prefetch)

    assert trace["started"] == 1
    assert trace["max_in_flight"] == 1
    fetch = isolated.get(material_id())["transcript"]["fetch"]
    assert fetch["status"] == "ready"
    assert prefetch._pending == set()


@pytest.mark.asyncio
async def test_fetches_for_different_materials_never_overlap(
    isolated: service.TimedMediaStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_material(isolated, "aaaaaaaaaaa")
    save_material(isolated, "bbbbbbbbbbb")
    grant_consent(monkeypatch)
    trace: dict[str, int] = {}
    stub_download(
        monkeypatch,
        cues=[{"start": 0.0, "end": 1.0, "text": "Serialized."}],
        trace=trace,
    )

    prefetch = SubtitlePrefetchService()
    states = await asyncio.gather(
        prefetch.enqueue("tester", material_id("aaaaaaaaaaa"), isolated),
        prefetch.enqueue("tester", material_id("bbbbbbbbbbb"), isolated),
    )
    assert all(state["status"] == "queued" for state in states)
    await drain(prefetch)

    assert trace["started"] == 2
    assert trace["max_in_flight"] == 1
    for video_id in ("aaaaaaaaaaa", "bbbbbbbbbbb"):
        transcript = isolated.get(material_id(video_id))["transcript"]
        assert transcript["status"] == "ready"
        assert transcript["fetch"]["attempts"] == 1


@pytest.mark.asyncio
async def test_completed_fetch_releases_the_dedup_key_for_manual_retry(
    isolated: service.TimedMediaStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_material(isolated)
    grant_consent(monkeypatch)
    trace: dict[str, int] = {}
    stub_download(monkeypatch, code="no_captions", trace=trace)

    prefetch = SubtitlePrefetchService()
    await prefetch.enqueue("tester", material_id(), isolated, manual=True)
    await drain(prefetch)

    assert trace["started"] == 1
    assert isolated.get(material_id())["transcript"]["fetch"]["status"] == "unavailable"

    retried = await prefetch.enqueue("tester", material_id(), isolated, manual=True)
    assert retried["status"] == "queued"
    await drain(prefetch)

    assert trace["started"] == 2
    persisted = isolated.get(material_id())["transcript"]["fetch"]
    assert persisted["attempts"] == 2
    assert persisted["status"] == "unavailable"
    assert prefetch._pending == set()
