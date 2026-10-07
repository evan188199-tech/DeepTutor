"""Async-task videogen adapter: task status transition coverage.

Drives ``AsyncTaskVideogenAdapter.generate`` / ``submit_task`` and the
DashScope variant end-to-end against scripted HTTP responses (everything
mocked): queued → running → succeeded ordering, every accepted success and
failure state spelling, timeouts for stuck tasks, progress notification
cadence, download edge cases, task-id extraction, and DashScope-specific
failure branches. No network access, no real renders.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from deeptutor.services.generation_http import GenerationProviderError
from deeptutor.services.videogen.adapters.async_task import AsyncTaskVideogenAdapter
from deeptutor.services.videogen.adapters.dashscope import DashScopeVideogenAdapter
from deeptutor.services.videogen.config import VideogenConfig

_POLL_SUFFIX = "contents/generations/tasks/task-1"


def _patch_http(
    monkeypatch: pytest.MonkeyPatch,
    *,
    post: Any = None,
    get: Any = None,
) -> dict[str, list[Any]]:
    """Patch ``httpx.AsyncClient`` post/get with url-routed fakes."""
    captured: dict[str, list[Any]] = {"posts": [], "gets": []}

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["posts"].append(
            {"url": url, "json": kwargs.get("json"), "headers": kwargs.get("headers")}
        )
        resp = post(url, kwargs) if callable(post) else post
        resp.request = httpx.Request("POST", url)
        return resp

    async def fake_get(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["gets"].append(url)
        resp = get(url, kwargs) if callable(get) else get
        resp.request = httpx.Request("GET", url)
        return resp

    if post is not None:
        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    if get is not None:
        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    return captured


def _config(**overrides: Any) -> VideogenConfig:
    values: dict[str, Any] = {
        "model": "seedance",
        "base_url": "https://ark/api/v3",
        "api_key": "k",
        "poll_interval": 0.0,
    }
    values.update(overrides)
    return VideogenConfig(**values)


def _download_response() -> httpx.Response:
    return httpx.Response(200, content=b"MP4DATA", headers={"content-type": "video/mp4"})


def _poll_then_download_router(sequence: list[dict[str, Any]]) -> Any:
    """GET router: serve poll payloads in order, then serve the video download."""
    pending = list(sequence)

    def router(url: str, _kwargs: Any) -> httpx.Response:
        if url.endswith(_POLL_SUFFIX):
            payload = pending.pop(0) if pending else sequence[-1]
            return httpx.Response(200, json=payload)
        return _download_response()

    return router


def _submit_response() -> httpx.Response:
    return httpx.Response(200, json={"id": "task-1"})


def _progress_recorder() -> tuple[Any, list[str]]:
    """Return ``(progress_fn, messages)`` recording every notification."""
    messages: list[str] = []

    async def on_progress(message: str) -> None:
        messages.append(message)

    return on_progress, messages


# ── success transitions ─────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["succeeded", "success", "completed", "done"])
async def test_success_state_spellings_complete_the_task(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    payload = {"status": status, "content": {"video_url": "https://cdn/v.mp4"}}
    _patch_http(monkeypatch, post=_submit_response(), get=_poll_then_download_router([payload]))
    video, content_type = await AsyncTaskVideogenAdapter().generate("a wave", _config())
    assert video == b"MP4DATA"
    assert content_type == "video/mp4"


@pytest.mark.asyncio
async def test_task_transitions_queued_running_then_succeeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sequence = [
        {"status": "queued"},
        {"status": "running"},
        {"status": "succeeded", "content": {"video_url": "https://cdn/v.mp4"}},
    ]
    captured = _patch_http(
        monkeypatch, post=_submit_response(), get=_poll_then_download_router(sequence)
    )
    progress, messages = _progress_recorder()

    video, content_type = await AsyncTaskVideogenAdapter().generate(
        "a wave", _config(), progress=progress
    )

    assert video == b"MP4DATA"
    assert content_type == "video/mp4"
    poll_urls = [url for url in captured["gets"] if url.endswith(_POLL_SUFFIX)]
    assert len(poll_urls) == 3
    assert captured["gets"][-1] == "https://cdn/v.mp4"
    assert messages == [
        "Submitted video task; rendering… (id=task-1)",
        "Downloading rendered video…",
    ]


@pytest.mark.asyncio
async def test_state_key_uppercase_and_url_aliases_are_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submit = httpx.Response(200, json={"task_id": "task-1"})
    payload = {"state": "COMPLETED", "data": {"url": "https://cdn/v.mp4"}}
    _patch_http(monkeypatch, post=submit, get=_poll_then_download_router([payload]))
    video, _ = await AsyncTaskVideogenAdapter().generate("x", _config())
    assert video == b"MP4DATA"


@pytest.mark.asyncio
async def test_progress_notified_every_third_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    sequence = [
        {"status": "queued"},
        {"status": "queued"},
        {"status": "queued"},
        {"status": "queued"},
        {"status": "succeeded", "content": {"video_url": "https://cdn/v.mp4"}},
    ]
    _patch_http(monkeypatch, post=_submit_response(), get=_poll_then_download_router(sequence))
    progress, messages = _progress_recorder()

    await AsyncTaskVideogenAdapter().generate("x", _config(), progress=progress)

    assert len([m for m in messages if m.startswith("Submitted")]) == 1
    assert len([m for m in messages if m.startswith("Downloading")]) == 1
    still = [m for m in messages if m.startswith("Still rendering")]
    assert len(still) == 1
    assert "queued" in still[0]


# ── failure transitions ─────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "error", "cancelled", "canceled", "expired"])
async def test_failure_state_spellings_abort_the_task(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    payload = {"status": status, "error": {"message": "content blocked"}}
    _patch_http(monkeypatch, post=_submit_response(), get=_poll_then_download_router([payload]))
    with pytest.raises(
        GenerationProviderError, match=f"Video task task-1 {status}: content blocked"
    ):
        await AsyncTaskVideogenAdapter().generate("x", _config())


@pytest.mark.asyncio
async def test_failure_error_string_is_surfaced(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"status": "failed", "error": "quota exhausted"}
    _patch_http(monkeypatch, post=_submit_response(), get=_poll_then_download_router([payload]))
    with pytest.raises(GenerationProviderError, match="failed: quota exhausted"):
        await AsyncTaskVideogenAdapter().generate("x", _config())


@pytest.mark.asyncio
async def test_stuck_task_times_out_with_last_status(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http(
        monkeypatch,
        post=_submit_response(),
        get=_poll_then_download_router([{"status": "generating"}]),
    )
    with pytest.raises(GenerationProviderError, match="timed out after 0s") as excinfo:
        await AsyncTaskVideogenAdapter().generate("x", _config(poll_timeout=0))
    assert "last status: generating" in str(excinfo.value)


@pytest.mark.asyncio
async def test_blank_status_times_out_as_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http(
        monkeypatch, post=_submit_response(), get=_poll_then_download_router([{"status": ""}])
    )
    with pytest.raises(GenerationProviderError, match="last status: unknown"):
        await AsyncTaskVideogenAdapter().generate("x", _config(poll_timeout=0))


@pytest.mark.asyncio
async def test_success_state_without_video_url_keeps_waiting_until_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_http(
        monkeypatch,
        post=_submit_response(),
        get=_poll_then_download_router([{"status": "succeeded"}]),
    )
    with pytest.raises(GenerationProviderError, match="timed out after 0s"):
        await AsyncTaskVideogenAdapter().generate("x", _config(poll_timeout=0))


# ── submit & download edges ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_requires_base_url() -> None:
    with pytest.raises(GenerationProviderError, match="No endpoint URL configured"):
        await AsyncTaskVideogenAdapter().submit_task("x", _config(base_url=""))


@pytest.mark.asyncio
async def test_submit_http_error_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", failing_post)
    with pytest.raises(GenerationProviderError, match="Video task submission error"):
        await AsyncTaskVideogenAdapter().submit_task("x", _config())


@pytest.mark.asyncio
async def test_empty_download_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def router(url: str, _kwargs: Any) -> httpx.Response:
        if url.endswith(_POLL_SUFFIX):
            return httpx.Response(
                200, json={"status": "succeeded", "content": {"video_url": "https://cdn/v.mp4"}}
            )
        return httpx.Response(200, content=b"", headers={"content-type": "video/mp4"})

    _patch_http(monkeypatch, post=_submit_response(), get=router)
    with pytest.raises(GenerationProviderError, match="empty file"):
        await AsyncTaskVideogenAdapter().generate("x", _config())


@pytest.mark.asyncio
async def test_non_video_content_type_is_coerced_to_mp4(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def router(url: str, _kwargs: Any) -> httpx.Response:
        if url.endswith(_POLL_SUFFIX):
            return httpx.Response(
                200, json={"status": "done", "content": {"video_url": "https://cdn/v.mp4"}}
            )
        return httpx.Response(
            200, content=b"MP4DATA", headers={"content-type": "application/octet-stream"}
        )

    _patch_http(monkeypatch, post=_submit_response(), get=router)
    _, content_type = await AsyncTaskVideogenAdapter().generate("x", _config())
    assert content_type == "video/mp4"


@pytest.mark.asyncio
async def test_download_http_error_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    def router(url: str, _kwargs: Any) -> httpx.Response:
        if url.endswith(_POLL_SUFFIX):
            return httpx.Response(
                200,
                json={"status": "succeeded", "content": {"video_url": "https://cdn/v.mp4"}},
            )
        return httpx.Response(403, text="denied")

    _patch_http(monkeypatch, post=_submit_response(), get=router)
    with pytest.raises(GenerationProviderError, match="Video download failed with HTTP 403"):
        await AsyncTaskVideogenAdapter().generate("x", _config())


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"id": "t1"}, "t1"),
        ({"task_id": "t2"}, "t2"),
        ({"data": {"id": "t3"}}, "t3"),
    ],
)
def test_extract_task_id_variants(payload: dict[str, Any], expected: str) -> None:
    resp = httpx.Response(200, json=payload)
    assert AsyncTaskVideogenAdapter._extract_task_id(resp) == expected


@pytest.mark.parametrize("payload", [{}, {"id": ""}, {"data": {}}, [1, 2]])
def test_extract_task_id_missing_raises(payload: Any) -> None:
    resp = httpx.Response(200, json=payload)
    with pytest.raises(GenerationProviderError, match="no task id"):
        AsyncTaskVideogenAdapter._extract_task_id(resp)


# ── DashScope variant branches ──────────────────────────────────────────────


def _dashscope_config(**overrides: Any) -> VideogenConfig:
    values: dict[str, Any] = {
        "model": "wan2.5-t2v-preview",
        "provider_name": "dashscope",
        "adapter": "dashscope",
        "base_url": "https://dashscope.aliyuncs.com/api/v1",
        "api_key": "dash-key",
        "poll_interval": 0.0,
    }
    values.update(overrides)
    return VideogenConfig(**values)


def _dashscope_submit() -> httpx.Response:
    return httpx.Response(200, json={"output": {"task_id": "ds-1"}})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "canceled", "cancelled", "expired", "unknown"])
async def test_dashscope_failure_statuses_abort_the_task(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    def router(url: str, _kwargs: Any) -> httpx.Response:
        if url.endswith("/tasks/ds-1"):
            return httpx.Response(
                200,
                json={"output": {"task_status": status.upper(), "message": "policy blocked"}},
            )
        return httpx.Response(500, text="download must not run")

    _patch_http(monkeypatch, post=_dashscope_submit(), get=router)
    with pytest.raises(
        GenerationProviderError, match=f"DashScope video task {status}: policy blocked"
    ):
        await DashScopeVideogenAdapter().generate("x", _dashscope_config())


@pytest.mark.asyncio
async def test_dashscope_success_without_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def router(url: str, _kwargs: Any) -> httpx.Response:
        if url.endswith("/tasks/ds-1"):
            return httpx.Response(200, json={"output": {"task_status": "SUCCEEDED"}})
        return httpx.Response(500, text="download must not run")

    _patch_http(monkeypatch, post=_dashscope_submit(), get=router)
    with pytest.raises(GenerationProviderError, match="Successful DashScope video task had no URL"):
        await DashScopeVideogenAdapter().generate("x", _dashscope_config())


@pytest.mark.asyncio
async def test_dashscope_poll_protocol_error_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def router(url: str, _kwargs: Any) -> httpx.Response:
        if url.endswith("/tasks/ds-1"):
            return httpx.Response(200, json={"code": "Throttling", "message": "throttled"})
        return httpx.Response(500, text="download must not run")

    _patch_http(monkeypatch, post=_dashscope_submit(), get=router)
    with pytest.raises(
        GenerationProviderError,
        match=r"DashScope video task status failed \(Throttling\): throttled",
    ):
        await DashScopeVideogenAdapter().generate("x", _dashscope_config())


@pytest.mark.asyncio
async def test_dashscope_malformed_poll_payload_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def router(url: str, _kwargs: Any) -> httpx.Response:
        if url.endswith("/tasks/ds-1"):
            return httpx.Response(200, json={"output": "not-a-dict"})
        return httpx.Response(500, text="download must not run")

    _patch_http(monkeypatch, post=_dashscope_submit(), get=router)
    with pytest.raises(GenerationProviderError, match="Malformed DashScope video task response"):
        await DashScopeVideogenAdapter().generate("x", _dashscope_config())


def test_dashscope_payload_rejects_non_numeric_duration() -> None:
    config = _dashscope_config(duration="soon")
    with pytest.raises(GenerationProviderError, match="Invalid DashScope video duration"):
        DashScopeVideogenAdapter._payload("x", config)


def test_dashscope_payload_includes_numeric_duration() -> None:
    config = _dashscope_config(duration="5")
    payload = DashScopeVideogenAdapter._payload("x", config)
    assert payload["parameters"]["duration"] == 5
