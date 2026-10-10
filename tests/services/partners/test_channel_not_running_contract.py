"""Contract: ``send`` on a never-started channel must raise, not silently drop.

``BaseChannel.send`` documents that a channel which cannot attempt delivery
because it is not running (``start()`` never completed, or ``stop()`` ran)
must raise :class:`ChannelNotRunningError` instead of silently returning, so
the channel manager's retry policy and the operator's logs see the failure.
This suite pins that contract for every channel implementation.

Stateless channels are exempt: their transport needs no started client, so
"not running" never blocks delivery for them (asserted separately below).
"""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock

import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.base import BaseChannel, ChannelNotRunningError
from deeptutor.partners.config import paths as partner_paths

#: (module, Channel class, Config class) for every stateful channel. All of
#: them construct a platform client in ``start()`` and clear it in ``stop()``,
#: so a freshly constructed instance is exactly the "not running" state.
STATEFUL_CHANNELS = [
    ("dingtalk", "DingTalkChannel", "DingTalkConfig"),
    ("discord", "DiscordChannel", "DiscordConfig"),
    ("feishu", "FeishuChannel", "FeishuConfig"),
    ("matrix", "MatrixChannel", "MatrixConfig"),
    ("mattermost", "MattermostChannel", "MattermostConfig"),
    ("mochat", "MochatChannel", "MochatConfig"),
    ("msteams", "MSTeamsChannel", "MSTeamsConfig"),
    ("napcat", "NapcatChannel", "NapcatConfig"),
    ("qq", "QQChannel", "QQConfig"),
    ("slack", "SlackChannel", "SlackConfig"),
    ("telegram", "TelegramChannel", "TelegramConfig"),
    ("wecom", "WecomChannel", "WecomConfig"),
    ("weixin", "WeixinChannel", "WeixinConfig"),
    ("whatsapp", "WhatsAppChannel", "WhatsAppConfig"),
    ("zulip", "ZulipChannel", "ZulipConfig"),
]


_MATRIX_NIO_NAMES = (
    "AsyncClient",
    "AsyncClientConfig",
    "DownloadError",
    "InviteEvent",
    "JoinError",
    "MatrixRoom",
    "MemoryDownloadResponse",
    "RoomEncryptedMedia",
    "RoomMessage",
    "RoomMessageMedia",
    "RoomMessageText",
    "RoomSendError",
    "RoomTypingError",
    "SyncError",
    "UploadError",
)


def _stub_matrix_modules() -> None:
    """Install minimal stand-ins so matrix.py imports without the extra.

    The not-running contract never touches the real SDK (the client stays
    ``None``), so placeholder names are enough to import the module and
    exercise the guard — and the suite stays meaningful on installs without
    ``deeptutor[matrix]``.
    """
    nio = types.ModuleType("nio")
    for name in _MATRIX_NIO_NAMES:
        setattr(nio, name, type(name, (), {}))
    mistune = types.ModuleType("mistune")
    mistune.create_markdown = lambda *args, **kwargs: lambda text: text
    nh3 = types.ModuleType("nh3")

    class _StubCleaner:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def clean(self, value: str) -> str:
            return value

    nh3.Cleaner = _StubCleaner
    nh3.escape = lambda value: value
    sys.modules.setdefault("nio", nio)
    sys.modules.setdefault("mistune", mistune)
    sys.modules.setdefault("nh3", nh3)


def _build_channel(module_name: str, class_name: str, config_name: str) -> BaseChannel:
    try:
        module = importlib.import_module(f"deeptutor.partners.channels.{module_name}")
    except ImportError as exc:
        if module_name != "matrix":
            pytest.skip(f"optional channel dependency missing: {exc}")
        _stub_matrix_modules()
        module = importlib.import_module(f"deeptutor.partners.channels.{module_name}")
    channel_cls = getattr(module, class_name)
    config_cls = getattr(module, config_name)
    bus = MagicMock(spec=MessageBus)
    return channel_cls(config_cls(), bus)


@pytest.fixture
def isolated_state_dir(tmp_path, monkeypatch):
    """Keep constructors that eagerly load state (msteams refs) inside tmp."""
    monkeypatch.setattr(partner_paths, "get_runtime_subdir", lambda name: tmp_path)
    return tmp_path


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "class_name", "config_name"),
    STATEFUL_CHANNELS,
    ids=[case[0] for case in STATEFUL_CHANNELS],
)
async def test_send_before_start_raises_not_running(
    isolated_state_dir, module_name: str, class_name: str, config_name: str
) -> None:
    channel = _build_channel(module_name, class_name, config_name)

    assert not channel.is_running
    msg = OutboundMessage(channel=module_name, chat_id="chat-1", content="hello")
    with pytest.raises(ChannelNotRunningError):
        await channel.send(msg)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "class_name", "config_name"),
    STATEFUL_CHANNELS,
    ids=[case[0] for case in STATEFUL_CHANNELS],
)
async def test_send_after_stop_raises_not_running(
    isolated_state_dir, module_name: str, class_name: str, config_name: str
) -> None:
    """A channel whose ``stop()`` ran is back in the not-running state."""
    channel = _build_channel(module_name, class_name, config_name)
    channel._running = True

    await channel.stop()

    assert not channel.is_running
    msg = OutboundMessage(channel=module_name, chat_id="chat-1", content="hello")
    with pytest.raises(ChannelNotRunningError):
        await channel.send(msg)


@pytest.mark.asyncio
async def test_stateless_email_send_never_enters_not_running() -> None:
    """Email needs no started client, so not-running is not a failure mode."""
    from deeptutor.partners.channels.email import EmailChannel, EmailConfig

    channel = EmailChannel(EmailConfig(), MagicMock(spec=MessageBus))
    assert not channel.is_running
    # Unconsented config makes send() return early — but never with the
    # not-running error: SMTP delivery does not depend on start().
    await channel.send(OutboundMessage(channel="email", chat_id="a@b.c", content="hi"))
