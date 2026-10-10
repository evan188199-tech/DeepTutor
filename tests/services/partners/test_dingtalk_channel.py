"""Unit tests for the DingTalk channel delivery contract and lifecycle.

Covers the three contract fixes: ``send()`` raises on delivery failure,
the shared HTTP client is created with an explicit timeout, and ``stop()``
closes the SDK stream client and interrupts the unbounded stream loop.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
import deeptutor.partners.channels.dingtalk as dingtalk_module
from deeptutor.partners.channels.dingtalk import DingTalkChannel, DingTalkConfig


def _make_channel(**overrides) -> DingTalkChannel:
    defaults = {
        "enabled": True,
        "client_id": "ding-client-id",
        "client_secret": "ding-client-secret",
        "allow_from": ["*"],
    }
    defaults.update(overrides)
    config = DingTalkConfig.model_validate(defaults)
    bus = MagicMock(spec=MessageBus)
    return DingTalkChannel(config, bus)


def _outbound(content: str = "", media: list[str] | None = None) -> OutboundMessage:
    return OutboundMessage(
        channel="dingtalk",
        chat_id="user-1",
        content=content,
        media=list(media or []),
    )


def _response(
    status: int = 200,
    json_body: dict | None = None,
    text: str | None = None,
) -> httpx.Response:
    kwargs: dict = {"json": json_body} if json_body is not None else {"text": text or ""}
    return httpx.Response(
        status,
        request=httpx.Request("POST", "https://api.dingtalk.com/"),
        **kwargs,
    )


def _http_with_responses(*responses: httpx.Response) -> MagicMock:
    http = MagicMock()
    http.post = AsyncMock(side_effect=list(responses))
    return http


def _prime_token(channel: DingTalkChannel) -> None:
    channel._access_token = "cached-token"
    channel._token_expiry = time.time() + 3600


class TestSendContract:
    @pytest.mark.asyncio
    async def test_send_raises_when_access_token_unavailable(self):
        channel = _make_channel()
        channel._http = _http_with_responses(_response(500, text="oauth down"))

        with pytest.raises(RuntimeError, match="access token"):
            await channel.send(_outbound(content="hello"))

    @pytest.mark.asyncio
    async def test_send_raises_when_text_delivery_fails(self):
        channel = _make_channel()
        _prime_token(channel)
        channel._http = _http_with_responses(_response(400, json_body={}))

        with pytest.raises(RuntimeError, match="text send failed"):
            await channel.send(_outbound(content="hello"))

    @pytest.mark.asyncio
    async def test_send_raises_when_api_returns_error_code(self):
        channel = _make_channel()
        _prime_token(channel)
        channel._http = _http_with_responses(
            _response(200, json_body={"errcode": 300001, "errmsg": "forbidden"})
        )

        with pytest.raises(RuntimeError, match="text send failed"):
            await channel.send(_outbound(content="hello"))

    @pytest.mark.asyncio
    async def test_send_media_failure_raises_when_fallback_also_fails(self):
        channel = _make_channel()
        _prime_token(channel)
        channel._http = _http_with_responses(_response(500, text="send down"))

        with pytest.raises(RuntimeError, match="media send failed"):
            await channel.send(_outbound(content="", media=["/nonexistent/dir/photo.png"]))

    @pytest.mark.asyncio
    async def test_send_media_failure_fallback_delivered_does_not_raise(self):
        channel = _make_channel()
        _prime_token(channel)
        channel._http = _http_with_responses(_response(200, json_body={}))

        await channel.send(_outbound(content="", media=["/nonexistent/dir/a.png"]))

        channel._http.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_delivers_text_and_http_image_media(self):
        channel = _make_channel()
        _prime_token(channel)
        channel._http = _http_with_responses(
            _response(200, json_body={}),  # markdown text
            _response(200, json_body={}),  # sampleImageMsg by URL
        )

        await channel.send(_outbound(content="hello", media=["https://example.com/a.png"]))

        assert channel._http.post.await_count == 2


class _FakeWebSocket:
    def __init__(self) -> None:
        self.close = AsyncMock()


class _FakeStreamClient:
    """Mimics the dingtalk_stream client lifecycle surface used by the channel."""

    def __init__(self) -> None:
        self.websocket = _FakeWebSocket()
        self.register_callback_handler = MagicMock()
        self.start_calls = 0
        self.cancelled = False
        self.entered = asyncio.Event()
        self._behaviors: list[str] = []

    def script(self, *behaviors: str) -> "_FakeStreamClient":
        self._behaviors = list(behaviors)
        return self

    async def start(self):
        self.start_calls += 1
        behavior = self._behaviors.pop(0) if self._behaviors else "block"
        self.entered.set()
        if behavior == "raise":
            raise RuntimeError("stream failed")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def _install_fake_sdk(monkeypatch: pytest.MonkeyPatch) -> _FakeStreamClient:
    client = _FakeStreamClient()
    fake_chatbot_message = MagicMock()
    fake_chatbot_message.TOPIC = "/fake/topic"
    monkeypatch.setattr(dingtalk_module, "DINGTALK_AVAILABLE", True)
    monkeypatch.setattr(dingtalk_module, "Credential", MagicMock())
    monkeypatch.setattr(dingtalk_module, "DingTalkStreamClient", MagicMock(return_value=client))
    monkeypatch.setattr(dingtalk_module, "ChatbotMessage", fake_chatbot_message)
    return client


async def _start_channel(channel: DingTalkChannel, fake: _FakeStreamClient) -> asyncio.Task:
    task = asyncio.create_task(channel.start())
    await asyncio.wait_for(fake.entered.wait(), timeout=5)
    return task


class TestLifecycleContract:
    @pytest.mark.asyncio
    async def test_start_creates_http_client_with_explicit_timeout(self, monkeypatch):
        channel = _make_channel()
        fake = _install_fake_sdk(monkeypatch)

        task = await _start_channel(channel, fake)

        assert channel._http is not None
        assert channel._http.timeout == httpx.Timeout(30.0)

        await channel.stop()
        await asyncio.wait_for(task, timeout=5)

    @pytest.mark.asyncio
    async def test_stop_interrupts_unbounded_stream_start(self, monkeypatch):
        channel = _make_channel()
        fake = _install_fake_sdk(monkeypatch)

        task = await _start_channel(channel, fake)
        await channel.stop()

        await asyncio.wait_for(task, timeout=5)
        assert fake.cancelled is True

    @pytest.mark.asyncio
    async def test_stop_closes_stream_client_websocket(self, monkeypatch):
        channel = _make_channel()
        fake = _install_fake_sdk(monkeypatch)

        task = await _start_channel(channel, fake)
        await channel.stop()
        await asyncio.wait_for(task, timeout=5)

        fake.websocket.close.assert_awaited_once()
        assert channel._client is None

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self):
        channel = _make_channel()

        await channel.stop()

        assert channel._client is None
        assert channel._http is None

    @pytest.mark.asyncio
    async def test_stream_error_triggers_reconnect(self, monkeypatch):
        channel = _make_channel()
        fake = _install_fake_sdk(monkeypatch)
        fake.script("raise")  # first attempt fails; later attempts block

        task = asyncio.create_task(channel.start())
        await asyncio.wait_for(fake.entered.wait(), timeout=5)

        async def _wait_for_second_start() -> None:
            deadline = time.monotonic() + 15
            while fake.start_calls < 2 and time.monotonic() < deadline:
                await asyncio.sleep(0.05)

        await asyncio.wait_for(_wait_for_second_start(), timeout=20)
        assert fake.start_calls == 2

        await channel.stop()
        await asyncio.wait_for(task, timeout=5)
