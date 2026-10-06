"""Unit tests for the Matrix channel typing-indicator error paths."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

nio = pytest.importorskip("nio", reason="matrix-nio not installed")

from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels import matrix as matrix_module
from deeptutor.partners.channels.matrix import MatrixChannel, MatrixConfig

ROOM_ID = "!room:example.com"


def _make_channel(**overrides) -> MatrixChannel:
    defaults: dict = {"enabled": True, "allow_from": ["*"]}
    defaults.update(overrides)
    config = MatrixConfig.model_validate(defaults)
    bus = MagicMock(spec=MessageBus)
    return MatrixChannel(config, bus)


def _fake_asyncio(sleep) -> SimpleNamespace:
    return SimpleNamespace(
        sleep=sleep,
        CancelledError=asyncio.CancelledError,
        create_task=asyncio.create_task,
    )


class TestSetTypingErrorVisibility:
    @pytest.mark.asyncio
    async def test_room_typing_exception_logged_and_swallowed(self):
        ch = _make_channel()
        ch.client = MagicMock()
        ch.client.room_typing = AsyncMock(side_effect=RuntimeError("network down"))

        with patch("deeptutor.partners.channels.matrix.logger.debug") as mock_debug:
            await ch._set_typing(ROOM_ID, True)

        ch.client.room_typing.assert_awaited_once()
        mock_debug.assert_called_once()
        assert "typing request error" in str(mock_debug.call_args)

    @pytest.mark.asyncio
    async def test_room_typing_error_response_logged_and_swallowed(self):
        ch = _make_channel()
        ch.client = MagicMock()
        error_response = MagicMock(spec=matrix_module.RoomTypingError)
        ch.client.room_typing = AsyncMock(return_value=error_response)

        with patch("deeptutor.partners.channels.matrix.logger.debug") as mock_debug:
            await ch._set_typing(ROOM_ID, False)

        ch.client.room_typing.assert_awaited_once()
        mock_debug.assert_called_once()
        assert "Matrix typing failed" in str(mock_debug.call_args)

    @pytest.mark.asyncio
    async def test_keepalive_loop_survives_typing_failures(self):
        ch = _make_channel()
        ch._running = True
        ch.client = MagicMock()
        ch.client.room_typing = AsyncMock(side_effect=RuntimeError("network down"))

        ticks: list[float] = []

        async def fast_sleep(delay: float) -> None:
            ticks.append(delay)
            if len(ticks) >= 2:
                ch._running = False

        with (
            patch.object(matrix_module, "asyncio", _fake_asyncio(fast_sleep)),
            patch("deeptutor.partners.channels.matrix.logger.debug") as mock_debug,
        ):
            await ch._start_typing_keepalive(ROOM_ID)
            task = ch._typing_tasks[ROOM_ID]
            await task

        # initial notice + two refreshes all failed, yet the loop kept running
        assert ch.client.room_typing.await_count == 3
        assert mock_debug.call_count == 3
