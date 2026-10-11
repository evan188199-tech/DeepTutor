"""Channel keep-running loops park on a stop event instead of a 1s sleep poll."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.queue import MessageBus


@pytest.mark.asyncio
async def test_telegram_start_parks_until_stop_event(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("telegram")
    import deeptutor.partners.channels.telegram as telegram_mod

    class _FakeApp:
        def __init__(self) -> None:
            self.updater = SimpleNamespace(
                start_polling=AsyncMock(),
                stop=AsyncMock(),
            )
            self.bot = SimpleNamespace(
                get_me=AsyncMock(return_value=SimpleNamespace(id=1, username="bot")),
                set_my_commands=AsyncMock(),
            )

        def add_error_handler(self, *_args) -> None:
            pass

        def add_handler(self, *_args) -> None:
            pass

        async def initialize(self) -> None:
            pass

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def shutdown(self) -> None:
            pass

    class _Builder:
        def token(self, _token):
            return self

        def request(self, _request):
            return self

        def get_updates_request(self, _request):
            return self

        def build(self) -> _FakeApp:
            return _FakeApp()

    monkeypatch.setattr(telegram_mod, "HTTPXRequest", lambda **_kwargs: object())
    monkeypatch.setattr(
        telegram_mod.Application, "builder", staticmethod(lambda: _Builder())
    )

    channel = telegram_mod.TelegramChannel(
        telegram_mod.TelegramConfig.model_validate({"enabled": True, "token": "t"}),
        MagicMock(spec=MessageBus),
    )

    task = asyncio.create_task(channel.start())
    await asyncio.sleep(0.15)
    # Parked on the stop event — no polling loop, still running.
    assert not task.done()
    assert channel._stop_event is not None

    loop = asyncio.get_running_loop()
    stopped_at = loop.time()
    await channel.stop()
    await asyncio.wait_for(task, timeout=2.0)
    # The event releases the parked start() within a loop tick, not a poll
    # interval.
    assert loop.time() - stopped_at < 0.5
    assert channel._stop_event is None
