"""QQ channel lifecycle, bot wiring and ephemeral-state contract (coverage gap: qq.py).

Complements ``test_qq_message_parsing.py`` (branch ``test/qq-lark-http-parsing-20261005``),
which pins inbound identity resolution and outbound payload shapes. This suite
pins the remaining behaviors on ``deeptutor/partners/channels/qq.py`` @ origin/main:

* ``start()`` builds the botpy client and forwards credentials to the SDK.
* The generated bot class routes SDK events to ``_on_message`` with the right
  ``is_group`` flag, and ``on_ready`` publishes the ``connected`` setup state.
* ``_run_bot`` publishes ``connecting``/``error`` states and reconnects after a
  dropped connection; it neither connects nor sleeps once ``_running`` is off.
* ``stop()`` clears the running flag and closes the client, swallowing close
  failures and tolerating a missing client.
* Volatile state: ``_msg_seq`` bumps monotonically per send, the dedup window
  (``_processed_ids``) is bounded at 1000 and re-allows evicted ids, and the
  chat-type cache populated by inbound group messages routes replies to the
  group API (unknown chats default to C2C).

The SDK client is a ``SimpleNamespace`` with ``AsyncMock`` api methods, so no
network access and no QQ credentials are involved.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import botpy
import pytest

pytest.importorskip("botpy")

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels import qq as qq_module
from deeptutor.partners.channels.qq import QQChannel

pytestmark = pytest.mark.usefixtures("partners_root")


# ── fixtures / builders ──────────────────────────────────────────────


def _client(**api_methods) -> SimpleNamespace:
    methods = {
        "post_c2c_message": AsyncMock(),
        "post_group_message": AsyncMock(),
    }
    methods.update(api_methods)
    return SimpleNamespace(api=SimpleNamespace(**methods))


def _channel(**overrides) -> QQChannel:
    config = {"enabled": True, "appId": "app", "secret": "sec", "allowFrom": ["*"]}
    config.update(overrides)
    return QQChannel(config, MessageBus())


def _c2c(*, id="m1", content="hello") -> SimpleNamespace:
    return SimpleNamespace(id=id, content=content, author=SimpleNamespace(id="u1"))


def _group(*, id="g1", content="hi", group_openid="grp1", member_openid="mem1") -> SimpleNamespace:
    author = SimpleNamespace(member_openid=member_openid)
    return SimpleNamespace(id=id, content=content, group_openid=group_openid, author=author)


# ── onboarding defaults ──────────────────────────────────────────────


def test_default_config_is_disabled_with_camel_case_keys() -> None:
    defaults = QQChannel.default_config()

    assert defaults["enabled"] is False
    assert defaults["appId"] == ""
    assert defaults["secret"] == ""
    assert defaults["allowFrom"] == []
    assert defaults["msgFormat"] == "plain"


# ── start: client construction and credential hand-off ───────────────


@pytest.mark.asyncio
async def test_start_builds_client_and_passes_credentials_to_sdk(monkeypatch) -> None:
    channel = _channel()
    sdk_start = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(botpy.Client, "start", sdk_start)

    with pytest.raises(asyncio.CancelledError):  # cancel breaks the reconnect loop
        await channel.start()

    assert channel._running is True
    assert isinstance(channel._client, botpy.Client)
    assert sdk_start.await_count == 1
    assert sdk_start.await_args.kwargs == {"appid": "app", "secret": "sec"}
    assert channel.setup_state["status"] == "connecting"


# ── bot class event wiring ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_bot_on_ready_publishes_connected_state(monkeypatch) -> None:
    channel = _channel()
    bot = qq_module._make_bot_class(channel)()
    monkeypatch.setattr(
        botpy.Client, "robot", property(lambda self: SimpleNamespace(name="Riona"))
    )

    await bot.on_ready()

    assert channel.setup_state["status"] == "connected"


@pytest.mark.asyncio
async def test_bot_routes_sdk_events_with_chat_type_flag() -> None:
    channel = _channel()
    bot = qq_module._make_bot_class(channel)()
    channel._on_message = AsyncMock()

    await bot.on_c2c_message_create(_c2c(id="w1"))
    await bot.on_direct_message_create(_c2c(id="w2"))
    await bot.on_group_at_message_create(_group(id="w3"))

    flags = [call.kwargs.get("is_group") for call in channel._on_message.await_args_list]
    assert flags == [False, False, True]


# ── _run_bot: connecting / error states and reconnect loop ───────────


@pytest.mark.asyncio
async def test_run_bot_reconnects_after_connection_failure(monkeypatch) -> None:
    channel = _channel()
    channel._running = True
    channel._client = SimpleNamespace(
        start=AsyncMock(side_effect=[RuntimeError("ws dropped"), asyncio.CancelledError])
    )

    async def _no_sleep(_):
        return None

    monkeypatch.setattr(qq_module.asyncio, "sleep", _no_sleep)

    with pytest.raises(asyncio.CancelledError):
        await channel._run_bot()

    assert channel._client.start.await_count == 2  # retried after the failure
    first_attempt = channel._client.start.await_args_list[0]
    assert first_attempt.kwargs == {"appid": "app", "secret": "sec"}


@pytest.mark.asyncio
async def test_run_bot_publishes_error_state_and_stops_retrying_once_stopped(
    monkeypatch,
) -> None:
    channel = _channel()
    channel._running = True
    channel._client = SimpleNamespace(start=AsyncMock(side_effect=RuntimeError("ws down")))
    sleeps: list[bool] = []

    async def _sleep(_):
        sleeps.append(True)
        channel._running = False  # stop arrives during the backoff window

    monkeypatch.setattr(qq_module.asyncio, "sleep", _sleep)

    await channel._run_bot()

    state = channel.setup_state
    assert state["status"] == "error"
    assert "retry" in state["message"].lower()
    assert channel._client.start.await_count == 1
    assert sleeps == [True]  # the backoff only runs while the channel is running


@pytest.mark.asyncio
async def test_run_bot_does_not_connect_when_already_stopped() -> None:
    channel = _channel()
    channel._running = False
    channel._client = SimpleNamespace(start=AsyncMock())

    await channel._run_bot()

    assert channel._client.start.await_count == 0
    assert channel.setup_state == {}


# ── stop: flag, close, failure tolerance ─────────────────────────────


@pytest.mark.asyncio
async def test_stop_clears_running_flag_and_closes_client() -> None:
    channel = _channel()
    channel._running = True
    channel._client = SimpleNamespace(close=AsyncMock())

    await channel.stop()

    assert channel._running is False
    assert channel._client.close.await_count == 1


@pytest.mark.asyncio
async def test_stop_swallows_close_failure_and_survives_missing_client() -> None:
    breaking = _channel()
    breaking._running = True
    breaking._client = SimpleNamespace(
        close=AsyncMock(side_effect=RuntimeError("already closed"))
    )
    await breaking.stop()  # must not raise
    assert breaking._running is False

    idle = _channel()
    await idle.stop()  # no client ever built
    assert idle._running is False


# ── volatile state: seq counter, dedup window, chat-type mapping ─────


@pytest.mark.asyncio
async def test_msg_seq_increments_monotonically_across_sends() -> None:
    channel = _channel()
    channel._client = _client()
    channel._chat_type_cache["u1"] = "c2c"

    await channel.send(OutboundMessage(channel="qq", chat_id="u1", content="first"))
    await channel.send(OutboundMessage(channel="qq", chat_id="u1", content="second"))

    seqs = [
        call.kwargs["msg_seq"]
        for call in channel._client.api.post_c2c_message.await_args_list
    ]
    assert seqs == [2, 3]  # starts at 1, bumps exactly once per send


@pytest.mark.asyncio
async def test_dedup_window_is_bounded_and_reallows_evicted_ids() -> None:
    channel = _channel()
    channel._handle_message = AsyncMock()
    assert channel._processed_ids.maxlen == 1000

    channel._processed_ids.append("m1")
    channel._processed_ids.extend(f"filler{i}" for i in range(1000))  # evicts "m1"

    await channel._on_message(_c2c(id="m1"))
    await channel._on_message(_c2c(id="m1"))  # within the fresh window: deduped

    assert channel._handle_message.await_count == 1


@pytest.mark.asyncio
async def test_inbound_group_message_maps_session_and_routes_reply_to_group_api() -> None:
    channel = _channel()
    channel._client = _client()
    channel.bus.publish_inbound = AsyncMock()

    await channel._on_message(
        _group(id="gm1", content="hi", group_openid="grp1", member_openid="mem1"),
        is_group=True,
    )

    inbound = channel.bus.publish_inbound.await_args.args[0]
    assert inbound.sender_id == "mem1"
    assert inbound.chat_id == "grp1"
    assert inbound.session_key == "qq:grp1"  # session keyed by the group chat

    await channel.send(
        OutboundMessage(
            channel="qq", chat_id="grp1", content="reply", metadata={"message_id": "gm1"}
        )
    )
    kwargs = channel._client.api.post_group_message.await_args.kwargs
    assert kwargs["group_openid"] == "grp1"  # cache populated by the inbound dispatch
    assert kwargs["msg_id"] == "gm1"
    assert channel._client.api.post_c2c_message.await_count == 0


@pytest.mark.asyncio
async def test_send_to_unknown_chat_defaults_to_c2c_api() -> None:
    channel = _channel()
    channel._client = _client()

    await channel.send(OutboundMessage(channel="qq", chat_id="stranger", content="yo"))

    kwargs = channel._client.api.post_c2c_message.await_args.kwargs
    assert kwargs["openid"] == "stranger"
    assert channel._client.api.post_group_message.await_count == 0
