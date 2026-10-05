"""QQ channel message parsing, dedup and send routing contract (coverage gap: qq.py zero tests).

Contract suite for ``deeptutor/partners/channels/qq.py`` on origin/main
(``f07029cfc``). Incoming messages are ``SimpleNamespace`` stand-ins for
botpy's ``C2CMessage``/``GroupMessage`` — ``_on_message`` only reads
attributes — and the SDK client is a ``SimpleNamespace`` with ``AsyncMock``
api methods, so no network access and no QQ credentials are involved.

Pinned contracts:

* C2C chat identity resolution: ``author.id`` → ``author.user_openid`` →
  literal ``unknown`` (only when the attribute is absent entirely).
* Group chats carry ``group_openid`` + ``author.member_openid`` and cache
  the chat type so replies route through ``post_group_message``.
* Dedup by message id happens before the blank-content check.
* Outbound payloads: plain vs markdown ``msg_type``, ``msg_seq`` bump,
  ``msg_id`` replayed from inbound metadata.
* ``start()`` without credentials reports ``action_required`` instead of
  touching the SDK; a broken handler is swallowed per-message.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("botpy")

from deeptutor.partners.bus.events import InboundMessage, OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.qq import QQChannel

pytestmark = pytest.mark.usefixtures("partners_root")


# ── fixtures / builders ──────────────────────────────────────────────


def _client() -> SimpleNamespace:
    return SimpleNamespace(
        api=SimpleNamespace(
            post_c2c_message=AsyncMock(),
            post_group_message=AsyncMock(),
        )
    )


def _channel(**overrides) -> QQChannel:
    config = {"enabled": True, "appId": "app", "secret": "sec", "allowFrom": ["*"]}
    config.update(overrides)
    return QQChannel(config, MessageBus())


def _c2c(*, id="m1", content="hello", user_id=None, user_openid=None) -> SimpleNamespace:
    author = SimpleNamespace(id=user_id, user_openid=user_openid)
    return SimpleNamespace(id=id, content=content, author=author)


def _group(*, id="g1", content="hi group", group_openid="grp1", member_openid="mem1"):
    author = SimpleNamespace(member_openid=member_openid)
    return SimpleNamespace(id=id, content=content, group_openid=group_openid, author=author)


async def _dispatched(channel: QQChannel, message, *, is_group: bool = False):
    channel._handle_message = AsyncMock()
    await channel._on_message(message, is_group=is_group)
    assert channel._handle_message.await_count == 1
    call = channel._handle_message.await_args
    return call.kwargs.get("sender_id"), call.kwargs.get("chat_id"), call.kwargs


# ── inbound parsing: c2c identity resolution ─────────────────────────


@pytest.mark.asyncio
async def test_c2c_message_uses_author_id_for_chat_and_sender() -> None:
    channel = _channel()

    sender_id, chat_id, kwargs = await _dispatched(channel, _c2c(user_id="u9"))

    assert sender_id == "u9"
    assert chat_id == "u9"
    assert kwargs["content"] == "hello"
    assert kwargs["metadata"] == {"message_id": "m1"}
    assert channel._chat_type_cache["u9"] == "c2c"


@pytest.mark.asyncio
async def test_c2c_message_falls_back_to_user_openid() -> None:
    channel = _channel()

    sender_id, chat_id, _ = await _dispatched(channel, _c2c(user_id=None, user_openid="open1"))

    assert sender_id == "open1"
    assert chat_id == "open1"
    assert channel._chat_type_cache["open1"] == "c2c"


@pytest.mark.asyncio
async def test_c2c_message_without_identity_resolves_to_unknown() -> None:
    channel = _channel()
    message = SimpleNamespace(
        id="m2", content="who?", author=SimpleNamespace(id=None)
    )  # no user_openid attribute at all

    sender_id, chat_id, _ = await _dispatched(channel, message)

    assert sender_id == "unknown"
    assert chat_id == "unknown"
    assert channel._chat_type_cache["unknown"] == "c2c"


# ── inbound parsing: group identity ──────────────────────────────────


@pytest.mark.asyncio
async def test_group_message_uses_group_openid_and_member_openid() -> None:
    channel = _channel()

    sender_id, chat_id, kwargs = await _dispatched(
        channel,
        _group(member_openid="mem7"),
        is_group=True,
    )

    assert sender_id == "mem7"
    assert chat_id == "grp1"
    assert kwargs["metadata"] == {"message_id": "g1"}
    assert channel._chat_type_cache["grp1"] == "group"


@pytest.mark.asyncio
async def test_group_message_content_is_stripped() -> None:
    channel = _channel()

    _, _, kwargs = await _dispatched(channel, _group(content="  padded  "), is_group=True)

    assert kwargs["content"] == "padded"


# ── dedup & blank-content guards ─────────────────────────────────────


@pytest.mark.asyncio
async def test_duplicate_message_id_is_dispatched_once() -> None:
    channel = _channel()
    channel._handle_message = AsyncMock()
    message = _c2c(id="dup1")

    await channel._on_message(message)
    await channel._on_message(message)
    await channel._on_message(_c2c(id="dup2"))

    assert channel._handle_message.await_count == 2
    assert channel._handle_message.await_args_list[1].kwargs["metadata"] == {"message_id": "dup2"}


@pytest.mark.asyncio
async def test_blank_content_is_not_dispatched() -> None:
    channel = _channel()
    channel._handle_message = AsyncMock()

    await channel._on_message(_c2c(id="blank", content="   \n"))

    assert channel._handle_message.await_count == 0


# ── error paths ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handler_failure_is_swallowed_and_next_message_still_flows() -> None:
    channel = _channel()
    channel._handle_message = AsyncMock(side_effect=RuntimeError("boom"))

    await channel._on_message(_c2c(id="m-err"))  # must not raise

    channel._handle_message = AsyncMock()
    await channel._on_message(_c2c(id="m-after"))
    assert channel._handle_message.await_count == 1


@pytest.mark.asyncio
async def test_start_without_credentials_sets_action_required() -> None:
    channel = _channel(appId="", secret="")

    await channel.start()

    state = channel.setup_state
    assert state["status"] == "action_required"
    assert "missing" in state["message"].lower()
    assert channel._client is None


@pytest.mark.asyncio
async def test_start_without_sdk_marks_channel_unavailable(monkeypatch) -> None:
    import deeptutor.partners.channels.qq as qq_module

    channel = _channel()
    monkeypatch.setattr(qq_module, "QQ_AVAILABLE", False)

    await channel.start()

    assert channel.setup_state["status"] == "unavailable"
    assert channel._client is None


# ── end-to-end into the bus ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_inbound_message_reaches_bus_with_qq_channel_name() -> None:
    channel = _channel()
    channel.bus.publish_inbound = AsyncMock()

    await channel._on_message(_c2c(id="bus1", content="ping", user_id="u5"))

    assert channel.bus.publish_inbound.await_count == 1
    inbound: InboundMessage = channel.bus.publish_inbound.await_args.args[0]
    assert inbound.channel == "qq"
    assert inbound.sender_id == "u5"
    assert inbound.chat_id == "u5"
    assert inbound.content == "ping"
    assert inbound.metadata["message_id"] == "bus1"
    assert inbound.session_key == "qq:u5"


# ── outbound send contract ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_plain_text_routes_c2c_with_replayed_msg_id() -> None:
    channel = _channel()
    channel._client = _client()
    channel._chat_type_cache["u5"] = "c2c"

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="u5",
            content="reply",
            metadata={"message_id": "m1"},
        )
    )

    kwargs = channel._client.api.post_c2c_message.await_args.kwargs
    assert kwargs["openid"] == "u5"
    assert kwargs["msg_type"] == 0
    assert kwargs["content"] == "reply"
    assert kwargs["msg_id"] == "m1"
    assert kwargs["msg_seq"] == 2  # starts at 1 and bumps per send
    assert channel._client.api.post_group_message.await_count == 0


@pytest.mark.asyncio
async def test_send_markdown_uses_msg_type_2_payload() -> None:
    channel = _channel(msgFormat="markdown")
    channel._client = _client()
    channel._chat_type_cache["u5"] = "c2c"

    await channel.send(OutboundMessage(channel="qq", chat_id="u5", content="**rich**"))

    kwargs = channel._client.api.post_c2c_message.await_args.kwargs
    assert kwargs["msg_type"] == 2
    assert kwargs["markdown"] == {"content": "**rich**"}
    assert "content" not in kwargs


@pytest.mark.asyncio
async def test_send_routes_cached_group_chat_to_group_api() -> None:
    channel = _channel()
    channel._client = _client()
    channel._chat_type_cache["grp1"] = "group"

    await channel.send(OutboundMessage(channel="qq", chat_id="grp1", content="hi"))

    kwargs = channel._client.api.post_group_message.await_args.kwargs
    assert kwargs["group_openid"] == "grp1"
    assert channel._client.api.post_c2c_message.await_count == 0


@pytest.mark.asyncio
async def test_send_without_client_is_silent_noop() -> None:
    channel = _channel()
    assert channel._client is None

    await channel.send(
        OutboundMessage(channel="qq", chat_id="u5", content="lost")
    )  # must not raise
