"""Regression tests for NapCat frame ``self_id`` parsing.

Targets the ``self_id`` coercion in ``NapcatChannel._dispatch_frame``
(``napcat.py``:216-220): ``int(sid)`` failures are swallowed by
``except (TypeError, ValueError): pass``, so a malformed ``self_id`` leaves
the channel identity unset (or stale) with no log trace — the channel's
self-identification fails silently.

Contract locked here for the follow-up fix:

1. A malformed ``self_id`` (non-numeric string / dict / list) must not raise
   out of ``_dispatch_frame`` and must not touch ``self._self_id``.
2. The rejection must be observable — at least one log record mentioning
   ``self_id``. These assertions FAIL against the current silent ``pass``
   and define the acceptance bar for the fix.
3. Normal frames (int or numeric-string ``self_id``) self-identify correctly,
   and frames without ``self_id`` leave the identity unset without crashing.

Found by a scan for silent exception handlers (``napcat.py:219``).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from loguru import logger
import pytest

from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.napcat import NapcatChannel, NapcatConfig


def _make_channel(**overrides) -> NapcatChannel:
    defaults = {
        "enabled": True,
        "ws_url": "ws://127.0.0.1:3001",
        "access_token": "",
        "allow_from": ["*"],
        "group_policy": "mention",
    }
    defaults.update(overrides)
    config = NapcatConfig.model_validate(defaults)
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return NapcatChannel(config, bus)


def _frame(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


@pytest.fixture
def log_sink():
    """loguru does not reach pytest's caplog; add a sink of our own."""
    lines: list[str] = []
    sink_id = logger.add(lines.append, level="DEBUG", format="{message}")
    try:
        yield lines
    finally:
        logger.remove(sink_id)


class TestSelfIdCapture:
    """Normal frames must set the channel identity (current behavior)."""

    @pytest.mark.asyncio
    async def test_meta_event_int_self_id(self):
        ch = _make_channel()
        await ch._dispatch_frame(
            _frame({"post_type": "meta_event", "meta_event_type": "heartbeat", "self_id": 123456})
        )
        assert ch._self_id == 123456

    @pytest.mark.asyncio
    async def test_message_event_numeric_string_self_id_coerced(self):
        ch = _make_channel()
        with (
            patch.object(ch, "_create_background_task") as mock_bg,
            patch.object(ch, "_on_message", new=MagicMock()),
        ):
            await ch._dispatch_frame(
                _frame(
                    {
                        "post_type": "message",
                        "message_type": "private",
                        "user_id": 42,
                        "self_id": "123456",
                    }
                )
            )
        assert ch._self_id == 123456
        mock_bg.assert_called_once()

    @pytest.mark.asyncio
    async def test_latest_valid_self_id_wins(self):
        ch = _make_channel()
        await ch._dispatch_frame(_frame({"post_type": "meta_event", "self_id": 111}))
        await ch._dispatch_frame(_frame({"post_type": "meta_event", "self_id": 222}))
        assert ch._self_id == 222


class TestMalformedSelfIdRejected:
    """Malformed ``self_id`` must not raise, must not set, and must log.

    The no-raise / value-preservation assertions hold today; the log-trace
    assertions fail against the silent ``except (TypeError, ValueError):
    pass`` and are the missing observability the fix must add.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bad_sid",
        [
            "not-a-number",  # int() -> ValueError
            {"user_id": 123},  # int() -> TypeError
            [123],  # int() -> TypeError
        ],
        ids=["non-numeric-string", "dict", "list"],
    )
    async def test_malformed_self_id_does_not_raise_set_or_stay_silent(self, log_sink, bad_sid):
        ch = _make_channel()
        await ch._dispatch_frame(_frame({"post_type": "meta_event", "self_id": bad_sid}))
        # No exception above; identity untouched.
        assert ch._self_id is None
        # The rejection must leave a trace naming the rejected field.
        assert any("self_id" in line.lower() for line in log_sink)

    @pytest.mark.asyncio
    async def test_malformed_self_id_keeps_previous_valid_value(self, log_sink):
        ch = _make_channel()
        await ch._dispatch_frame(_frame({"post_type": "meta_event", "self_id": 123456}))
        assert ch._self_id == 123456

        await ch._dispatch_frame(_frame({"post_type": "meta_event", "self_id": ["oops"]}))
        # A bad frame must not corrupt the previously identified identity.
        assert ch._self_id == 123456
        assert any("self_id" in line.lower() for line in log_sink)

    @pytest.mark.asyncio
    async def test_malformed_self_id_still_dispatches_message(self, log_sink):
        ch = _make_channel()
        with (
            patch.object(ch, "_create_background_task") as mock_bg,
            patch.object(ch, "_on_message", new=MagicMock()),
        ):
            await ch._dispatch_frame(
                _frame(
                    {
                        "post_type": "message",
                        "message_type": "private",
                        "user_id": 42,
                        "self_id": "oops",
                    }
                )
            )
        # Identity parsing must not drop the frame's own handling.
        mock_bg.assert_called_once()
        assert ch._self_id is None
        assert any("self_id" in line.lower() for line in log_sink)


class TestMissingSelfIdFields:
    """Frames without a usable ``self_id`` must not crash the channel."""

    @pytest.mark.asyncio
    async def test_notice_without_self_id_leaves_identity_unset(self):
        ch = _make_channel()
        with (
            patch.object(ch, "_create_background_task") as mock_bg,
            patch.object(ch, "_on_notice", new=MagicMock()),
        ):
            await ch._dispatch_frame(
                _frame(
                    {
                        "post_type": "notice",
                        "notice_type": "group_increase",
                        "group_id": 123,
                    }
                )
            )
        assert ch._self_id is None
        mock_bg.assert_called_once()

    @pytest.mark.asyncio
    async def test_self_id_null_is_skipped_by_design(self):
        ch = _make_channel()
        await ch._dispatch_frame(_frame({"post_type": "meta_event", "self_id": None}))
        # The explicit `is not None` guard treats null as "no identity claim".
        assert ch._self_id is None
