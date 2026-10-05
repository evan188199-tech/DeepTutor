"""Concurrency tests: onboarding locks must not be held across provider calls."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from deeptutor.services.partners.channel_onboarding import (
    ChannelOnboardingError,
    ChannelOnboardingManager,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _manager(handler: Any, clock: FakeClock) -> ChannelOnboardingManager:
    transport = httpx.MockTransport(handler)
    return ChannelOnboardingManager(
        client_factory=lambda: httpx.AsyncClient(transport=transport),
        now=clock,
    )


def _wecom_generate() -> httpx.Response:
    return httpx.Response(200, json={"data": {"scode": "s", "auth_url": "https://auth"}})


def test_hung_start_does_not_block_other_channels() -> None:
    async def run() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host in ("accounts.feishu.cn", "accounts.larksuite.com"):
                entered.set()
                await release.wait()
                return httpx.Response(200, json={"supported_auth_methods": ["client_secret"]})
            if request.url.path == "/ai/qc/generate":
                return _wecom_generate()
            return httpx.Response(200, json={"data": {"status": "pending"}})

        manager = _manager(handler, FakeClock())
        hung = asyncio.create_task(manager.start("ada", "feishu"))
        await entered.wait()

        started = await asyncio.wait_for(manager.start("grace", "wecom"), timeout=1)
        assert started["status"] == "pending_scan"
        status = await asyncio.wait_for(manager.status("grace", started["session_id"]), timeout=1)
        assert status["status"] == "pending_scan"

        release.set()
        with pytest.raises(ChannelOnboardingError):
            await asyncio.wait_for(hung, timeout=1)
        assert ("ada", "feishu") not in manager._active_by_key

    asyncio.run(run())


def test_hung_poll_does_not_block_subsequent_status_calls() -> None:
    async def run() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        polls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal polls
            if request.url.path == "/ai/qc/generate":
                return _wecom_generate()
            polls += 1
            if polls == 1:
                entered.set()
                await release.wait()
            return httpx.Response(200, json={"data": {"status": "pending"}})

        manager = _manager(handler, FakeClock())
        started = await manager.start("ada", "wecom")
        hung = asyncio.create_task(manager.status("ada", started["session_id"]))
        await entered.wait()

        second = await asyncio.wait_for(manager.status("ada", started["session_id"]), timeout=1)
        assert second["status"] == "pending_scan"

        release.set()
        first = await asyncio.wait_for(hung, timeout=1)
        assert first["status"] == "pending_scan"
        # The in-flight poll served both status calls; no duplicate request
        # was sent while the first one hung.
        assert polls == 1

    asyncio.run(run())


def test_hung_poll_does_not_block_other_sessions() -> None:
    async def run() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        polls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal polls
            if request.url.path == "/ai/qc/generate":
                return _wecom_generate()
            polls += 1
            if polls == 1:
                entered.set()
                await release.wait()
            return httpx.Response(200, json={"data": {"status": "pending"}})

        manager = _manager(handler, FakeClock())
        first = await manager.start("ada", "wecom")
        second = await manager.start("grace", "wecom")
        hung = asyncio.create_task(manager.status("ada", first["session_id"]))
        await entered.wait()

        other = await asyncio.wait_for(manager.status("grace", second["session_id"]), timeout=1)
        assert other["status"] == "pending_scan"

        release.set()
        assert (await asyncio.wait_for(hung, timeout=1))["status"] == "pending_scan"

    asyncio.run(run())


def test_cancel_during_hung_poll_keeps_terminal_state() -> None:
    async def run() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        polls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal polls
            if request.url.path == "/ai/qc/generate":
                return _wecom_generate()
            polls += 1
            if polls == 1:
                entered.set()
                await release.wait()
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "status": "success",
                            "bot_info": {"botid": "bot-id", "secret": "bot-secret"},
                        }
                    },
                )
            return httpx.Response(200, json={"data": {"status": "pending"}})

        manager = _manager(handler, FakeClock())
        started = await manager.start("ada", "wecom")
        hung = asyncio.create_task(manager.status("ada", started["session_id"]))
        await entered.wait()

        cancelled = await asyncio.wait_for(manager.cancel("ada", started["session_id"]), timeout=1)
        assert cancelled["status"] == "cancelled"

        release.set()
        first = await asyncio.wait_for(hung, timeout=1)
        assert first["status"] == "cancelled"
        after = await asyncio.wait_for(manager.status("ada", started["session_id"]), timeout=1)
        assert after["status"] == "cancelled"
        assert manager._sessions[started["session_id"]].credentials == {}

    asyncio.run(run())


def test_concurrent_start_for_same_key_keeps_single_active_session() -> None:
    async def run() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        generates = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal generates
            if request.url.path == "/ai/qc/generate":
                generates += 1
                if generates == 1:
                    entered.set()
                    await release.wait()
                return _wecom_generate()
            return httpx.Response(200, json={"data": {"status": "pending"}})

        manager = _manager(handler, FakeClock())
        slow = asyncio.create_task(manager.start("ada", "wecom"))
        await entered.wait()

        fast = await asyncio.wait_for(manager.start("ada", "wecom"), timeout=1)
        release.set()
        slow_result = await asyncio.wait_for(slow, timeout=1)

        assert fast["status"] == "pending_scan"
        assert slow_result["status"] == "pending_scan"
        assert fast["session_id"] == slow_result["session_id"]
        assert len(manager._sessions) == 1

    asyncio.run(run())
