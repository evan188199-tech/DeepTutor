"""Shared bounded reconnect backoff replaces fixed channel sleep ladders (AGEN-1648)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from deeptutor.partners.bus.queue import MessageBus
import deeptutor.partners.channels.backoff as backoff_mod
from deeptutor.partners.channels.backoff import ReconnectBackoff, backoff_delay
from deeptutor.partners.channels.discord import DiscordChannel
from deeptutor.partners.channels.zulip import ZulipChannel, ZulipConfig


def _fixed_random() -> float:
    return 0.5  # middle of the jitter band: delay == ladder value exactly


class TestBackoffDelay:
    def test_midpoint_random_returns_the_ladder_value(self) -> None:
        assert backoff_delay(0, base=2.0, cap=30.0, rand=lambda: 0.5) == 2.0
        assert backoff_delay(1, base=2.0, cap=30.0, rand=lambda: 0.5) == 4.0
        assert backoff_delay(3, base=2.0, cap=30.0, rand=lambda: 0.5) == 16.0

    def test_jitter_stays_inside_the_band(self) -> None:
        for rand_value in (0.0, 0.25, 0.75, 0.999999):
            delay = backoff_delay(2, base=2.0, cap=30.0, jitter=0.25, rand=lambda: rand_value)
            assert 8.0 * 0.75 <= delay <= 8.0 * 1.25

    def test_cap_bounds_the_ladder(self) -> None:
        assert backoff_delay(30, base=2.0, cap=30.0, rand=lambda: 0.5) == 30.0

    def test_invalid_arguments_raise(self) -> None:
        with pytest.raises(ValueError):
            backoff_delay(0, base=0.0, cap=1.0)
        with pytest.raises(ValueError):
            backoff_delay(0, base=1.0, cap=-1.0)
        with pytest.raises(ValueError):
            backoff_delay(0, base=1.0, cap=1.0, jitter=1.0)


class TestReconnectBackoff:
    def test_escalates_then_resets(self) -> None:
        ladder = ReconnectBackoff(base=2.0, cap=30.0, rand=_fixed_random)
        assert [round(ladder.delay(), 6) for _ in range(6)] == [2.0, 4.0, 8.0, 16.0, 30.0, 30.0]
        assert ladder.failures == 6
        ladder.reset()
        assert ladder.failures == 0
        assert ladder.delay() == 2.0


def _zulip_channel() -> ZulipChannel:
    config = ZulipConfig.model_validate(
        {
            "enabled": True,
            "site": "https://example.zulipchat.com",
            "email": "bot@example.com",
            "api_key": "secret",
        }
    )
    channel = ZulipChannel(config, MagicMock(spec=MessageBus))
    channel._client = MagicMock()
    return channel


class TestZulipWiring:
    def test_call_with_retry_uses_jittered_ladder(self) -> None:
        channel = _zulip_channel()
        fn = MagicMock(side_effect=[Exception("fail"), Exception("fail"), {"result": "ok"}])
        with (
            patch.object(backoff_mod.random, "random", lambda: 0.5),
            patch("time.sleep") as sleeper,
        ):
            result = channel._call_with_retry(fn)
        assert result == {"result": "ok"}
        assert [call.args[0] for call in sleeper.call_args_list] == [1.0, 2.0]

    def test_listener_escalates_across_reconnects(self, monkeypatch: pytest.MonkeyPatch) -> None:
        channel = _zulip_channel()
        channel._running = True
        channel._register_queue = lambda: setattr(channel, "_queue_id", "q")
        channel._client.get_events = MagicMock(side_effect=RuntimeError("down"))
        sleeps: list[float] = []

        def fake_sleep(delay: float) -> None:
            sleeps.append(delay)
            if len(sleeps) >= 3:
                channel._running = False

        monkeypatch.setattr(backoff_mod.random, "random", lambda: 0.5)
        with patch("time.sleep", side_effect=fake_sleep):
            channel._run_listener()
        assert sleeps == [2.0, 4.0, 8.0]


@pytest.mark.asyncio
async def test_discord_reconnect_escalates_with_jitter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.partners.channels.discord import DiscordConfig

    channel = DiscordChannel(
        DiscordConfig.model_validate({"enabled": True, "token": "t"}), MagicMock(spec=MessageBus)
    )
    monkeypatch.setattr(backoff_mod.random, "random", lambda: 0.5)

    class _FailingConnect:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def __aenter__(self) -> "_FailingConnect":
            raise ConnectionError("gateway down")

        async def __aexit__(self, *_args) -> None:
            return None

    import deeptutor.partners.channels.discord as discord_mod

    monkeypatch.setattr(discord_mod.websockets, "connect", _FailingConnect)

    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        if len(sleeps) >= 2:
            channel._running = False

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    await channel.start()
    assert sleeps == [5.0, 10.0]
    await channel._http.aclose()
