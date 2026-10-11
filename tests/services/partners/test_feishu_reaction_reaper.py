"""The working-reaction TTL runs on one heap reaper, not one sleeper per message.

Regression coverage for the fixed-delay治理 in AGEN-1648: the old
``_schedule_reaction_expiry`` pinned one 3600s ``asyncio.sleep`` task per
in-flight message; the reaper must keep identical expiry semantics with a
single waiter that wakes exactly when a receipt is due.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.feishu import FeishuChannel


def _response(*, ok: bool = True, data: object | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        success=lambda: ok,
        data=data,
        code=0 if ok else 500,
        msg="ok" if ok else "unavailable",
    )


def _channel() -> FeishuChannel:
    channel = FeishuChannel({"enabled": True, "appId": "app", "appSecret": "secret"}, MessageBus())
    reaction = SimpleNamespace(
        create=MagicMock(return_value=_response(data=SimpleNamespace(reaction_id="r"))),
        delete=MagicMock(return_value=_response()),
    )
    channel._client = SimpleNamespace(
        im=SimpleNamespace(v1=SimpleNamespace(message_reaction=reaction))
    )
    return channel


def _schedule(channel: FeishuChannel, message_id: str, *, ttl: float, age: float = 0.0) -> None:
    """Queue one expiry the way ``_add_reaction`` would (receipt at creation time)."""
    receipt = (f"reaction-{message_id}", time.monotonic() - age)
    channel._working_reactions[message_id] = receipt
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(channel, "_WORKING_REACTION_TTL", ttl)
        channel._schedule_reaction_expiry(message_id, receipt)


@pytest.mark.asyncio
async def test_many_receipts_share_one_reaper_and_expire_on_time() -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel()
    channel._remove_reaction_sync = MagicMock(return_value=True)

    for index in range(5):
        _schedule(channel, f"om_{index}", ttl=0.05)

    reaper = channel._reaction_reaper_task
    assert reaper is not None and not reaper.done()
    # One waiter regardless of receipt count (the old design held five tasks).
    for index in range(5):
        _schedule(channel, f"om_extra_{index}", ttl=0.05)
    assert channel._reaction_reaper_task is reaper

    await asyncio.sleep(0.3)
    assert channel._remove_reaction_sync.call_count == 10
    assert not channel._working_reactions
    assert not channel._reaction_expiry_heap


@pytest.mark.asyncio
async def test_cleared_receipt_is_not_finished_by_the_reaper() -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel()
    channel._remove_reaction_sync = MagicMock(return_value=True)

    receipt = ("reaction-keep", time.monotonic())
    channel._working_reactions["om_keep"] = receipt
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(channel, "_WORKING_REACTION_TTL", 0.05)
        channel._schedule_reaction_expiry("om_keep", receipt)
    channel._clear_reaction_receipt("om_keep", receipt)

    await asyncio.sleep(0.2)
    channel._remove_reaction_sync.assert_not_called()


@pytest.mark.asyncio
async def test_earlier_deadline_wakes_a_parked_reaper() -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel()
    channel._remove_reaction_sync = MagicMock(return_value=True)

    # Park the reaper behind a far deadline, then queue a due-now receipt.
    _schedule(channel, "om_far", ttl=3600.0)
    await asyncio.sleep(0)
    _schedule(channel, "om_due", ttl=3600.0, age=3600.0)

    await asyncio.sleep(0.2)
    channel._remove_reaction_sync.assert_called_once_with("om_due", "reaction-om_due")
    assert "om_due" not in channel._working_reactions
    assert "om_far" in channel._working_reactions


@pytest.mark.asyncio
async def test_stop_cancels_the_reaper_and_clears_state() -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel()
    _schedule(channel, "om_stop", ttl=3600.0)
    reaper = channel._reaction_reaper_task
    assert reaper is not None

    await channel.stop()
    assert reaper.done()
    assert channel._reaction_reaper_task is None
    assert not channel._reaction_expiry_heap
    assert not channel._working_reactions


@pytest.mark.asyncio
async def test_pruned_receipts_are_not_finished() -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel()
    channel._remove_reaction_sync = MagicMock(return_value=True)
    channel._MAX_WORKING_REACTIONS = 1

    _schedule(channel, "om_old", ttl=3600.0, age=7200.0)
    _schedule(channel, "om_new", ttl=3600.0)
    # The prune drops the over-TTL receipt without scheduling a delete.
    expired = channel._prune_working_reactions()
    assert [message_id for message_id, _ in expired] == ["om_old"]

    await asyncio.sleep(0.1)
    channel._remove_reaction_sync.assert_not_called()
